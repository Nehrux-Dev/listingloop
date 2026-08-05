"""Property listings and their photos.

VERIFICATION IS THE CENTRAL INVARIANT
-------------------------------------
A listing carries data that will later drive generated marketing copy, so it
must not be usable until a human has looked at it and said so. Two rules
enforce that, and both live on the model rather than in a view:

  1. A listing starts ``UNVERIFIED``. It only becomes ``VERIFIED`` through the
     explicit verify action — never as a side effect of saving.
  2. Editing any field that changes what the listing *says* drops it straight
     back to ``UNVERIFIED``. Otherwise an agent could verify a listing and then
     quietly change the price, and everything downstream would still treat it
     as reviewed.

Rule 2 is implemented in ``save()`` rather than in the serializer so it also
holds for the Django admin, a shell session and a data migration.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.storage import listing_photo_upload_to
from apps.core.validators import ImageUploadValidator

image_upload_validator = ImageUploadValidator()


class PropertyType(models.TextChoices):
    HOUSE = "house", _("House")
    APARTMENT = "apartment", _("Apartment")
    TOWNHOUSE = "townhouse", _("Townhouse")
    CONDO = "condo", _("Condo")
    DUPLEX = "duplex", _("Duplex")
    LAND = "land", _("Land")
    COMMERCIAL = "commercial", _("Commercial")
    OTHER = "other", _("Other")


class ListingStatus(models.TextChoices):
    """Where the property is in its sales lifecycle."""

    DRAFT = "draft", _("Draft")
    ACTIVE = "active", _("Active")
    UNDER_OFFER = "under_offer", _("Under offer")
    SOLD = "sold", _("Sold")
    WITHDRAWN = "withdrawn", _("Withdrawn")


class VerificationStatus(models.TextChoices):
    """Whether a human has confirmed the data is correct.

    Deliberately separate from ``ListingStatus``: a listing can be live on the
    market and still awaiting review, and the two answer different questions.
    """

    UNVERIFIED = "unverified", _("Unverified")
    VERIFIED = "verified", _("Verified")


class ListingSource(models.TextChoices):
    MANUAL = "manual", _("Manual entry")
    IMPORT = "import", _("Imported from URL")


def validate_features(value) -> None:
    """``features`` must be a flat list of short, non-empty strings."""
    if not isinstance(value, list):
        raise ValidationError(_("Features must be a list."), code="invalid_features")
    if len(value) > 50:
        raise ValidationError(_("A listing may have at most 50 features."))
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(
                _("Each feature must be a non-empty string."), code="invalid_feature"
            )
        if len(item) > 120:
            raise ValidationError(_("Each feature must be 120 characters or fewer."))


class ListingQuerySet(models.QuerySet):
    def verified(self):
        """Listings a human has confirmed.

        Everything downstream (templates, AI content) must start from this
        queryset rather than from ``Listing.objects.all()``.
        """
        return self.filter(verification_status=VerificationStatus.VERIFIED)

    def publicly_visible(self):
        """Listings that may be served on an unauthenticated page.

        Verified, because unreviewed data must never be published; and not a
        draft or a withdrawn listing, because those are not on the market. The
        single definition all public views go through — a second, subtly
        different filter somewhere else is how an unverified listing ends up
        online.
        """
        return self.filter(
            verification_status=VerificationStatus.VERIFIED,
            public_slug__isnull=False,
        ).exclude(status__in=[ListingStatus.DRAFT, ListingStatus.WITHDRAWN])

    def for_user(self, user):
        """Scope to what ``user`` is allowed to see.

        Kept next to the model so every caller — viewset, management command,
        future Celery task — applies the same rule instead of reinventing it.
        """
        if not user.is_authenticated:
            return self.none()
        if user.is_nehrux_admin:
            return self
        if user.is_brokerage_admin:
            return self.filter(agent__brokerage__admins=user).distinct()
        # Agents see only their own listings.
        return self.filter(agent__user=user)


class Listing(TimeStampedModel):
    """A property listing owned by one agent."""

    agent = models.ForeignKey(
        "accounts.AgentProfile",
        on_delete=models.CASCADE,
        related_name="listings",
        verbose_name=_("agent"),
    )

    # -- address / location -------------------------------------------------
    # "Location" is modelled as structured components rather than one free-text
    # field: imports fill them individually, and later steps need the parts.
    address = models.CharField(_("street address"), max_length=255, blank=True)
    city = models.CharField(_("city or suburb"), max_length=120, blank=True)
    state = models.CharField(_("state or region"), max_length=120, blank=True)
    postcode = models.CharField(_("postcode"), max_length=20, blank=True)
    country = models.CharField(_("country"), max_length=120, blank=True)

    # Optional map pin. Left to the agent rather than geocoded automatically:
    # a geocoder is another external dependency with its own rate limits and
    # terms, and a wrong pin on a public page is worse than no pin.
    latitude = models.DecimalField(
        _("latitude"),
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("-90")), MaxValueValidator(Decimal("90"))],
    )
    longitude = models.DecimalField(
        _("longitude"),
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("-180")), MaxValueValidator(Decimal("180"))],
    )

    #: Stable identifier for the public URL. Generated once, then never changed
    #: — a shared link that stops working because someone edited the suburb is
    #: worse than a slug that no longer matches the address.
    public_slug = models.SlugField(
        _("public slug"), max_length=180, unique=True, null=True, blank=True
    )

    # -- core attributes ----------------------------------------------------
    # Every attribute is nullable: an import that cannot find a value must be
    # able to leave it blank rather than write a plausible-looking guess.
    price = models.DecimalField(
        _("price"),
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    bedrooms = models.PositiveSmallIntegerField(
        _("bedrooms"), null=True, blank=True, validators=[MaxValueValidator(100)]
    )
    bathrooms = models.DecimalField(
        _("bathrooms"),
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text=_("Halves are allowed, e.g. 2.5."),
    )
    square_footage = models.PositiveIntegerField(
        _("square footage"), null=True, blank=True
    )
    property_type = models.CharField(
        _("property type"),
        max_length=32,
        choices=PropertyType.choices,
        blank=True,
    )
    features = models.JSONField(
        _("features"), default=list, blank=True, validators=[validate_features]
    )
    description = models.TextField(_("description"), blank=True)

    status = models.CharField(
        _("listing status"),
        max_length=32,
        choices=ListingStatus.choices,
        default=ListingStatus.DRAFT,
        db_index=True,
    )

    # -- verification -------------------------------------------------------
    verification_status = models.CharField(
        _("verification status"),
        max_length=32,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
        db_index=True,
    )
    verified_at = models.DateTimeField(_("verified at"), null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_listings",
        verbose_name=_("verified by"),
    )

    # -- provenance ---------------------------------------------------------
    source = models.CharField(
        _("source"),
        max_length=16,
        choices=ListingSource.choices,
        default=ListingSource.MANUAL,
    )
    source_url = models.URLField(_("source URL"), max_length=1000, blank=True)
    imported_fields = models.JSONField(
        _("imported fields"),
        default=list,
        blank=True,
        help_text=_(
            "Names of the fields an import actually populated. Anything not "
            "listed here was left blank rather than guessed."
        ),
    )
    import_warnings = models.JSONField(
        _("import warnings"),
        default=list,
        blank=True,
        help_text=_("Human-readable notes about what an import could not extract."),
    )

    objects = ListingQuerySet.as_manager()

    #: Changing any of these changes what the listing claims, so verification
    #: has to be earned again. Presentation-only and workflow fields (status,
    #: the verification fields themselves, timestamps) are deliberately absent.
    VERIFIED_DATA_FIELDS = (
        "address",
        "city",
        "state",
        "postcode",
        "country",
        "price",
        "bedrooms",
        "bathrooms",
        "square_footage",
        "property_type",
        "features",
        "description",
    )

    #: The minimum a human must have filled in before they can verify.
    REQUIRED_FOR_VERIFICATION = ("address", "city", "price", "property_type")

    class Meta:
        verbose_name = _("listing")
        verbose_name_plural = _("listings")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["agent", "verification_status"]),
            models.Index(fields=["status", "verification_status"]),
        ]

    def __str__(self) -> str:
        return self.full_address or f"Listing #{self.pk}"

    @property
    def full_address(self) -> str:
        parts = [self.address, self.city, self.state, self.postcode, self.country]
        return ", ".join(part for part in parts if part)

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VerificationStatus.VERIFIED

    @property
    def is_usable_for_content(self) -> bool:
        """Gate for templates and AI content. Only verified listings qualify."""
        return self.is_verified

    @property
    def is_publicly_visible(self) -> bool:
        return (
            self.is_verified
            and bool(self.public_slug)
            and self.status not in (ListingStatus.DRAFT, ListingStatus.WITHDRAWN)
        )

    @property
    def has_map_pin(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def _build_public_slug(self) -> str:
        """A readable slug with a short random suffix.

        Readable because these get shared by hand; suffixed because two units
        in the same building would otherwise collide, and because a guessable
        slug invites scraping the whole set.
        """
        base = slugify(f"{self.address} {self.city}")[:150] or f"listing-{self.pk or ''}"
        return f"{base}-{uuid4().hex[:6]}".strip("-")

    def missing_required_fields(self) -> list[str]:
        """Which of ``REQUIRED_FOR_VERIFICATION`` are still empty."""
        missing = []
        for field in self.REQUIRED_FOR_VERIFICATION:
            value = getattr(self, field)
            if value is None or value == "":
                missing.append(field)
        return missing

    # -- verification transitions ------------------------------------------

    def mark_verified(self, user) -> None:
        """Record an explicit human confirmation.

        Raises ``ValidationError`` when required data is missing — "verified"
        has to mean someone confirmed real values, not that they clicked a
        button on an empty form.
        """
        missing = self.missing_required_fields()
        if missing:
            raise ValidationError(
                {
                    field: _("This field is required before a listing can be verified.")
                    for field in missing
                }
            )

        self.verification_status = VerificationStatus.VERIFIED
        self.verified_at = timezone.now()
        self.verified_by = user
        self.save(update_fields=["verification_status", "verified_at", "verified_by", "updated_at"])

    def mark_unverified(self) -> None:
        """Withdraw verification, e.g. when something looks wrong."""
        self.verification_status = VerificationStatus.UNVERIFIED
        self.verified_at = None
        self.verified_by = None
        self.save(update_fields=["verification_status", "verified_at", "verified_by", "updated_at"])

    def save(self, *args, **kwargs):
        """Reset verification whenever the underlying data changes.

        Compared against the stored row rather than tracked in memory, so it
        works no matter how the instance was loaded or mutated.
        """
        if not self.public_slug:
            self.public_slug = self._build_public_slug()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"public_slug"}

        update_fields = kwargs.get("update_fields")
        # The two mark_* helpers save an explicit field list; leaving them
        # alone here is what stops this check from immediately undoing them.
        touches_data = update_fields is None or any(
            field in self.VERIFIED_DATA_FIELDS for field in update_fields
        )

        if self.pk and touches_data and self.is_verified:
            previous = (
                type(self)
                .objects.filter(pk=self.pk)
                .values(*self.VERIFIED_DATA_FIELDS)
                .first()
            )
            if previous is not None and any(
                previous[field] != getattr(self, field)
                for field in self.VERIFIED_DATA_FIELDS
            ):
                self.verification_status = VerificationStatus.UNVERIFIED
                self.verified_at = None
                self.verified_by = None
                if update_fields is not None:
                    kwargs["update_fields"] = set(update_fields) | {
                        "verification_status",
                        "verified_at",
                        "verified_by",
                    }

        return super().save(*args, **kwargs)


class EnquiryStatus(models.TextChoices):
    NEW = "new", _("New")
    READ = "read", _("Read")
    REPLIED = "replied", _("Replied")
    ARCHIVED = "archived", _("Archived")
    SPAM = "spam", _("Spam")


class EnquiryQuerySet(models.QuerySet):
    def for_user(self, user):
        """Enquiries reach the agent whose listing they were sent about.

        Same scoping as everything else: an agent's own, a brokerage admin's
        brokerage, everything for a Nehrux Admin. Enquiries contain a member of
        the public's contact details, so the scoping matters more here than
        anywhere — this is the only place in the system holding data about
        people who never signed up.
        """
        if not user.is_authenticated:
            return self.none()
        if user.is_nehrux_admin:
            return self
        if user.is_brokerage_admin:
            return self.filter(agent__brokerage__admins=user).distinct()
        return self.filter(agent__user=user)

    def genuine(self):
        return self.exclude(status=EnquiryStatus.SPAM)


class Enquiry(TimeStampedModel):
    """A message from a member of the public about a listing.

    Never publicly readable. The public can create one; only the agent it was
    addressed to (and their brokerage) can read it back.
    """

    listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE, related_name="enquiries", verbose_name=_("listing")
    )
    #: Denormalised from the listing at submission time on purpose: if the
    #: listing is later reassigned, the enquiry stays with the agent who was
    #: actually contacted.
    agent = models.ForeignKey(
        "accounts.AgentProfile",
        on_delete=models.CASCADE,
        related_name="enquiries",
        verbose_name=_("agent"),
    )

    name = models.CharField(_("name"), max_length=120)
    email = models.EmailField(_("email"), blank=True)
    phone = models.CharField(_("phone"), max_length=40, blank=True)
    message = models.TextField(_("message"))

    status = models.CharField(
        _("status"),
        max_length=16,
        choices=EnquiryStatus.choices,
        default=EnquiryStatus.NEW,
        db_index=True,
    )
    read_at = models.DateTimeField(_("read at"), null=True, blank=True)

    # -- spam forensics -----------------------------------------------------
    # Kept so a flood can be traced and a rule tuned, not to profile anyone.
    ip_address = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    user_agent = models.CharField(_("user agent"), max_length=400, blank=True)
    #: Filled when the spam checks fired. The message is still stored: a false
    #: positive that silently discards a real buyer is the expensive failure.
    spam_reasons = models.JSONField(_("spam reasons"), default=list, blank=True)

    objects = EnquiryQuerySet.as_manager()

    class Meta:
        verbose_name = _("enquiry")
        verbose_name_plural = _("enquiries")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["agent", "-created_at"]),
            models.Index(fields=["listing", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} about listing {self.listing_id}"

    @property
    def is_spam(self) -> bool:
        return self.status == EnquiryStatus.SPAM

    @property
    def contact_summary(self) -> str:
        return " · ".join(part for part in (self.email, self.phone) if part)


class ListingPhoto(TimeStampedModel):
    """One image belonging to a listing.

    ``order`` drives display sequence; ties fall back to insertion order so the
    ordering is always deterministic.
    """

    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name="photos",
        verbose_name=_("listing"),
    )
    image = models.ImageField(
        _("image"),
        upload_to=listing_photo_upload_to,
        validators=[image_upload_validator],
    )
    caption = models.CharField(_("caption"), max_length=255, blank=True)
    order = models.PositiveIntegerField(_("order"), default=0, db_index=True)
    #: Where an imported photo came from, for provenance.
    source_url = models.URLField(_("source URL"), max_length=1000, blank=True)

    class Meta:
        verbose_name = _("listing photo")
        verbose_name_plural = _("listing photos")
        ordering = ("order", "id")

    def __str__(self) -> str:
        return f"Photo {self.order} for {self.listing_id}"
