"""Template library, saved designs, and the content calendar.

A TEMPLATE IS A STARTING POINT, NOT A CAGE
------------------------------------------
A template is a layout: a canvas, a background, and a set of elements. That is
all it is. Opening one for editing deep-copies its elements into a Design
(see ``document.py``), and from that moment the agent owns them outright —
every element can be moved, restyled, retyped, hidden, duplicated or deleted.

This used to be otherwise. Each template element carried a four-tier
``permission`` (locked / content_only / styled / free) that decided what an
agent could change, and most elements were locked, which the editor surfaced
as "FIXED BY TEMPLATE". That concept is gone: not renamed, not defaulted to
permissive — removed, along with the column that stored it. The only thing
that restricts editing now is ``locked`` on the design's own element, which
defaults to False and which the user sets and unsets themselves.

The checks that remain server-side (``document.validate_document``) were never
permission checks: they stop a colour or an image key from being interpolated
into HTML that a real browser then executes.

GEOMETRY IS FRACTIONAL
----------------------
Element positions are fractions of the canvas (0..1), not pixels, so one
template renders at Instagram Post, Story, Facebook and LinkedIn dimensions
without four separate layouts. Font sizes are likewise a fraction of canvas
height. Where a specific aspect ratio genuinely needs different placement, an
element can carry per-dimension overrides.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.storage import (
    design_export_upload_to,
    template_asset_upload_to,
    template_import_upload_to,
    template_source_page_upload_to,
)
from apps.core.validators import ImageUploadValidator

#: One shared instance, same pattern as apps/accounts/profiles.py — the size
#: limit is read from settings at validation time, so it is not frozen into
#: migrations.
image_upload_validator = ImageUploadValidator()


class TemplateCategory(models.TextChoices):
    # -- listing-led ---------------------------------------------------------
    NEW_LISTING = "new_listing", _("New Listing")
    COMING_SOON = "coming_soon", _("Coming Soon")
    OPEN_HOUSE = "open_house", _("Open House")
    JUST_SOLD = "just_sold", _("Just Sold")
    PRICE_REDUCED = "price_reduced", _("Price Reduced")
    LEASED = "leased", _("Leased")

    # -- agent-led -----------------------------------------------------------
    AGENT_INTRODUCTION = "agent_introduction", _("Agent Introduction")
    TESTIMONIAL = "testimonial", _("Testimonial")
    MARKET_UPDATE = "market_update", _("Market Update")
    NEIGHBOURHOOD_GUIDE = "neighbourhood_guide", _("Neighbourhood Guide")

    # -- seasonal and festival ----------------------------------------------
    # These never reference a property. An agent posts them to stay visible
    # between listings, which is the whole point of a content calendar.
    CHRISTMAS = "christmas", _("Christmas")
    NEW_YEAR = "new_year", _("New Year")
    LUNAR_NEW_YEAR = "lunar_new_year", _("Lunar New Year")
    DIWALI = "diwali", _("Diwali")
    EID = "eid", _("Eid")
    HANUKKAH = "hanukkah", _("Hanukkah")
    EASTER = "easter", _("Easter")
    THANKSGIVING = "thanksgiving", _("Thanksgiving")
    CANADA_DAY = "canada_day", _("Canada Day")
    AUSTRALIA_DAY = "australia_day", _("Australia Day")
    MOTHERS_DAY = "mothers_day", _("Mother's Day")
    FATHERS_DAY = "fathers_day", _("Father's Day")
    SEASONAL = "seasonal", _("Seasonal (general)")


#: Categories that are about the calendar rather than a property. Used to
#: decide which templates appear in the content calendar and which may be used
#: with no listing attached.
SEASONAL_CATEGORIES: frozenset[str] = frozenset(
    {
        TemplateCategory.CHRISTMAS,
        TemplateCategory.NEW_YEAR,
        TemplateCategory.LUNAR_NEW_YEAR,
        TemplateCategory.DIWALI,
        TemplateCategory.EID,
        TemplateCategory.HANUKKAH,
        TemplateCategory.EASTER,
        TemplateCategory.THANKSGIVING,
        TemplateCategory.CANADA_DAY,
        TemplateCategory.AUSTRALIA_DAY,
        TemplateCategory.MOTHERS_DAY,
        TemplateCategory.FATHERS_DAY,
        TemplateCategory.SEASONAL,
    }
)

#: Categories that describe a specific property and are meaningless without one.
LISTING_CATEGORIES: frozenset[str] = frozenset(
    {
        TemplateCategory.NEW_LISTING,
        TemplateCategory.COMING_SOON,
        TemplateCategory.OPEN_HOUSE,
        TemplateCategory.JUST_SOLD,
        TemplateCategory.PRICE_REDUCED,
        TemplateCategory.LEASED,
    }
)


class TemplateStyle(models.TextChoices):
    BOLD = "bold", _("Bold")
    MINIMAL = "minimal", _("Minimal")
    LUXURY = "luxury", _("Luxury")
    WARM = "warm", _("Warm")
    EDITORIAL = "editorial", _("Editorial")
    CLASSIC = "classic", _("Classic")


class ElementType(models.TextChoices):
    TEXT = "text", _("Text")
    IMAGE = "image", _("Image")
    COLOR_BLOCK = "color_block", _("Colour block")
    LOGO = "logo", _("Logo")
    BADGE = "badge", _("Badge")
    DIVIDER = "divider", _("Divider")
    #: Decorative artwork that is part of the template's design, not a photo
    #: of anything — a ribbon, an illustrated background shape. Distinct from
    #: IMAGE because an IMAGE element's content comes from listing/agent/brand
    #: data or an agent's own upload; a STATIC_GRAPHIC's content is the
    #: template's own `static_asset` file and nothing else ever resolves it.
    STATIC_GRAPHIC = "static_graphic", _("Static graphic")


class TemplateQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The library one user may browse.

        Two kinds of template share this table and they are not the same thing.
        A template with no ``owner`` is *product content* — seeded by Nehrux,
        curated, and shown to everybody. A template with an owner was imported
        from artwork that one agent uploaded, and belongs to them.

        Mixing the second kind into everyone's gallery is the failure this
        method exists to prevent: an agent's own flyer, with their brokerage's
        wording still in it, appearing in a competitor's template picker.

        Brokerage admins deliberately do *not* see their agents' imports. The
        scoping on designs and listings is about oversight of published work;
        an unfinished template someone dragged in is not that, and widening the
        rule here would be a surprise rather than a feature.
        """
        if not user.is_authenticated:
            return self.none()
        if user.is_nehrux_admin:
            return self
        return self.filter(models.Q(owner__isnull=True) | models.Q(owner__user=user))


class Template(TimeStampedModel):
    """A reusable design: canvas, background, and a set of elements."""

    #: Who imported this, or NULL for a Nehrux-authored library template.
    #:
    #: NULL is the meaningful default and the reason this is nullable rather
    #: than pointing at a "system" profile: every template that existed before
    #: imports were possible is product content, and a migration that had to
    #: invent an owner for them would have to invent the wrong answer.
    owner = models.ForeignKey(
        "accounts.AgentProfile",
        on_delete=models.CASCADE,
        related_name="templates",
        null=True,
        blank=True,
        verbose_name=_("owner"),
        help_text=_(
            "The agent who imported this template. Blank for the shared "
            "Nehrux library, which every agent can see."
        ),
    )

    #: The artwork this template was extracted from, rasterised. Shown as the
    #: gallery thumbnail — see TemplateThumb on the frontend, which falls back
    #: to a style swatch when this is empty. Carries no validator: it is
    #: written by the import pipeline from bytes Pillow has already decoded,
    #: never from an upload.
    source_image = models.ImageField(
        _("source artwork"),
        upload_to=template_source_page_upload_to,
        blank=True,
        null=True,
    )

    name = models.CharField(_("name"), max_length=160)
    slug = models.SlugField(_("slug"), max_length=160, unique=True)
    description = models.TextField(_("description"), blank=True)

    category = models.CharField(
        _("category"), max_length=32, choices=TemplateCategory.choices, db_index=True
    )
    style = models.CharField(
        _("style"), max_length=32, choices=TemplateStyle.choices, db_index=True
    )

    layout_definition = models.JSONField(
        _("layout definition"),
        default=dict,
        blank=True,
        help_text=_(
            "Canvas-level settings: base aspect ratio, background, padding. "
            "Element geometry lives on TemplateElement."
        ),
    )

    is_active = models.BooleanField(_("active"), default=True, db_index=True)

    allows_added_elements = models.BooleanField(
        _("allows added elements"),
        default=True,
        help_text=_(
            "Whether the editor offers to add new elements to a design made "
            "from this template. A hint about how the layout is meant to be "
            "used — not a restriction on the elements it already has, which "
            "are the agent's to change once the design exists."
        ),
    )

    default_dimension = models.CharField(
        _("native format"),
        max_length=40,
        default="instagram_post",
        help_text=_(
            "The format this template was composed for — the one the editor "
            "opens. Geometry is normalised so every template still renders at "
            "every size, but a layout drawn tall reads as a crop when opened "
            "square, so it should not open square."
        ),
    )

    objects = TemplateQuerySet.as_manager()

    class Meta:
        verbose_name = _("template")
        verbose_name_plural = _("templates")
        ordering = ("category", "style", "name")
        indexes = [
            models.Index(fields=["category", "style", "is_active"]),
            models.Index(fields=["owner", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_imported(self) -> bool:
        """Whether this came from uploaded artwork rather than the library."""
        return self.owner_id is not None

    @property
    def is_seasonal(self) -> bool:
        return self.category in SEASONAL_CATEGORIES

    @property
    def requires_listing(self) -> bool:
        """Whether a design on this template needs a property attached.

        Derived from the category rather than stored: a "Just Sold" template
        with no listing has nothing to say, and a Diwali card has nothing to do
        with one. Deriving it means a new seasonal category cannot forget to
        set the flag.

        An **imported** template is exempt whatever its category. The extractor
        keeps the artwork's own wording as ``default_content`` and its own
        pictures as ``static_asset``, so the layout opens fully formed with
        nothing attached — a listing binding overwrites text that is already
        there rather than filling a hole. Gating it would mean an agent cannot
        customise artwork they uploaded themselves until they have verified an
        unrelated property, which is the one case where the template is
        unambiguously theirs to work on. The category still describes the
        occasion and still drives browsing; it just no longer decides this.

        Attaching a listing remains entirely possible — and still has to be a
        verified one. This governs whether a property is *required*, never
        whether an unreviewed one may be used.
        """
        if self.is_imported:
            return False
        return self.category in LISTING_CATEGORIES


class TemplateElement(models.Model):
    """One element of a template: the starting state of a design's element."""

    template = models.ForeignKey(
        Template, on_delete=models.CASCADE, related_name="elements"
    )
    #: Stable identifier used as the key in ``Design.overrides``.
    key = models.SlugField(_("key"), max_length=80)
    label = models.CharField(_("label"), max_length=120, blank=True)

    element_type = models.CharField(
        _("element type"), max_length=32, choices=ElementType.choices
    )

    #: Fractions of the canvas, 0..1: {"x":.., "y":.., "width":.., "height":..}.
    #: An optional "rotation" (degrees, -180..180, default 0) may also be
    #: present — validated in overrides.py, applied in html_builder.py. Kept
    #: inside this JSONField rather than a new column: it is one more number
    #: in the same coordinate space, gated by the same FREE-only rule as the
    #: rest of geometry, so it needs no schema change to add.
    geometry = models.JSONField(_("geometry"), default=dict)
    #: Rendering properties: text, colour, font_size_ratio, align, weight, etc.
    style_properties = models.JSONField(_("style properties"), default=dict, blank=True)

    #: Where the content comes from when not overridden, e.g.
    #: "listing.price" or "brand_kit.primary_color". Resolved at render time.
    content_source = models.CharField(_("content source"), max_length=120, blank=True)
    #: Literal fallback when there is no source and no override.
    default_content = models.TextField(_("default content"), blank=True)
    #: The file behind a STATIC_GRAPHIC element. Meaningless on any other
    #: element_type — nothing reads it unless element_type is STATIC_GRAPHIC.
    #: Uploaded through the admin only, same as every other template asset;
    #: there is deliberately no override field that can ever touch this.
    static_asset = models.ImageField(
        _("static asset"),
        upload_to=template_asset_upload_to,
        blank=True,
        null=True,
        validators=[image_upload_validator],
    )

    z_index = models.PositiveIntegerField(_("z-index"), default=0)

    class Meta:
        verbose_name = _("template element")
        verbose_name_plural = _("template elements")
        ordering = ("z_index", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["template", "key"], name="unique_element_key_per_template"
            )
        ]

    def __str__(self) -> str:
        return f"{self.template_id}:{self.key}"


class ImportStatus(models.TextChoices):
    QUEUED = "queued", _("Queued")
    RUNNING = "running", _("Running")
    SUCCEEDED = "succeeded", _("Succeeded")
    FAILED = "failed", _("Failed")


#: States from which no further work happens. Used to stop a redelivered Celery
#: task re-running — and re-billing — a job that already finished.
TERMINAL_IMPORT_STATUSES: frozenset[str] = frozenset(
    {ImportStatus.SUCCEEDED, ImportStatus.FAILED}
)


class TemplateImport(TimeStampedModel):
    """One attempt at turning uploaded artwork into a template.

    WHY THIS IS A ROW AND NOT JUST A REQUEST
    ------------------------------------------------------------------------
    Extraction is a minute-scale call to a vision model. Doing it inside the
    POST would mean a gateway timeout is indistinguishable from a failure, and
    a failure leaves nothing behind to look at. So the upload creates this row
    and returns immediately; the worker fills it in.

    The row outlives the job on purpose. ``error`` is what the user is shown
    when extraction fails, and ``source_file`` is kept so a bad extraction can
    be retried against the same artwork rather than asking them to find the
    file again.
    """

    agent = models.ForeignKey(
        "accounts.AgentProfile",
        on_delete=models.CASCADE,
        related_name="template_imports",
        verbose_name=_("agent"),
    )

    #: The upload, exactly as it arrived. Not an ImageField: this is the one
    #: place a PDF is a first-class input, and ImageField's validation would
    #: reject it before the rasteriser ever saw it.
    source_file = models.FileField(
        _("source file"), upload_to=template_import_upload_to
    )
    original_filename = models.CharField(
        _("original filename"), max_length=255, blank=True
    )

    status = models.CharField(
        _("status"),
        max_length=16,
        choices=ImportStatus.choices,
        default=ImportStatus.QUEUED,
        db_index=True,
    )
    #: Shown to the user verbatim when the import fails, so it is written to be
    #: read by one — never a raw provider exception, which can carry request
    #: details and says nothing actionable.
    error = models.TextField(_("error"), blank=True)

    #: Set once extraction succeeds. NULL while running, and NULL forever on a
    #: failure — which is what makes "did this produce anything?" a single
    #: check rather than a status string comparison.
    template = models.ForeignKey(
        Template,
        on_delete=models.SET_NULL,
        related_name="imports",
        null=True,
        blank=True,
        verbose_name=_("template"),
    )

    #: What the user asked the extracted template to be filed under. Applied to
    #: the Template on success; kept here so a retry does not have to ask again.
    requested_name = models.CharField(_("requested name"), max_length=160, blank=True)
    category = models.CharField(
        _("category"),
        max_length=32,
        choices=TemplateCategory.choices,
        default=TemplateCategory.NEW_LISTING,
    )
    style = models.CharField(
        _("style"),
        max_length=32,
        choices=TemplateStyle.choices,
        default=TemplateStyle.MINIMAL,
    )

    #: Observability for a call that costs money. Same fields the content
    #: generator records, for the same reason: an import that quietly starts
    #: costing five times what it did is invisible without them.
    element_count = models.PositiveIntegerField(_("elements found"), default=0)
    model_used = models.CharField(_("model"), max_length=80, blank=True)
    prompt_tokens = models.PositiveIntegerField(_("prompt tokens"), default=0)
    completion_tokens = models.PositiveIntegerField(_("completion tokens"), default=0)
    duration_ms = models.PositiveIntegerField(_("duration (ms)"), default=0)

    started_at = models.DateTimeField(_("started at"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)

    class Meta:
        verbose_name = _("template import")
        verbose_name_plural = _("template imports")
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["agent", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.original_filename or self.source_file.name} ({self.status})"

    @property
    def is_finished(self) -> bool:
        return self.status in TERMINAL_IMPORT_STATUSES


class CalendarEvent(TimeStampedModel):
    """One dated occasion an agent might post about.

    DATES ARE STORED, NOT COMPUTED
    ------------------------------
    Christmas and Canada Day are fixed, but Diwali, Eid, Lunar New Year, Easter
    and Hanukkah all move — they follow lunar and lunisolar calendars, and Eid
    in particular depends on local moon sighting, so two countries can observe
    it on different days.

    Computing those from a rule would mean shipping an approximation and being
    quietly wrong for somebody's religious holiday. Each occurrence is therefore
    a row with an explicit date, seeded a few years ahead and maintained
    deliberately. ``needs_date_review`` marks the ones that cannot be
    extrapolated, so it is visible when the seeded years run out rather than
    the calendar just going quiet.
    """

    name = models.CharField(_("name"), max_length=120)
    slug = models.SlugField(_("slug"), max_length=140)
    category = models.CharField(
        _("template category"),
        max_length=32,
        choices=TemplateCategory.choices,
        db_index=True,
        help_text=_("Which templates this event surfaces."),
    )
    date = models.DateField(_("date"), db_index=True)
    description = models.TextField(_("description"), blank=True)

    #: Where the event is observed, as a hint for who should see it. Blank
    #: means everywhere. Not enforced — an agent in any market may have clients
    #: who celebrate anything, and filtering them out by geography would be
    #: both presumptuous and wrong.
    regions = models.JSONField(_("regions"), default=list, blank=True)

    needs_date_review = models.BooleanField(
        _("date needs review"),
        default=False,
        help_text=_(
            "Set for any event whose date is not fixed — lunar and lunisolar "
            "festivals, and nth-weekday holidays like Thanksgiving. None of "
            "them are calculated here, so each year's date must be confirmed."
        ),
    )
    is_active = models.BooleanField(_("active"), default=True, db_index=True)

    class Meta:
        verbose_name = _("calendar event")
        verbose_name_plural = _("calendar events")
        ordering = ("date", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["slug", "date"], name="unique_calendar_event_occurrence"
            )
        ]
        indexes = [models.Index(fields=["date", "is_active"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.date})"

    @property
    def days_away(self) -> int:
        from django.utils import timezone as tz

        return (self.date - tz.localdate()).days

    @property
    def is_past(self) -> bool:
        return self.days_away < 0


class DesignQuerySet(models.QuerySet):
    def for_user(self, user):
        """Same scoping rule as listings: own work, or the brokerage's."""
        if not user.is_authenticated:
            return self.none()
        if user.is_nehrux_admin:
            return self
        if user.is_brokerage_admin:
            return self.filter(agent__brokerage__admins=user).distinct()
        return self.filter(agent__user=user)


class Design(TimeStampedModel):
    """A saved instance of a Template filled with one Listing's data."""

    name = models.CharField(_("name"), max_length=160)
    template = models.ForeignKey(
        Template, on_delete=models.PROTECT, related_name="designs"
    )
    agent = models.ForeignKey(
        "accounts.AgentProfile", on_delete=models.CASCADE, related_name="designs"
    )
    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.CASCADE,
        related_name="designs",
        null=True,
        blank=True,
        help_text=_(
            "Optional: agent-introduction, market-update and seasonal templates "
            "need no listing. When set, it must be a verified listing."
        ),
    )
    #: Optional link to the occasion this design was made for, so the content
    #: calendar can show what has already been produced for Diwali this year.
    calendar_event = models.ForeignKey(
        "templates.CalendarEvent",
        on_delete=models.SET_NULL,
        related_name="designs",
        null=True,
        blank=True,
    )

    #: THE DESIGN'S OWN CANVAS. A full, deep copy of the template's elements,
    #: taken the moment the design is created, and independently mutable from
    #: then on. Nothing an agent does here ever reaches the Template.
    #:
    #: This replaced `overrides` (below), which stored only a diff against the
    #: template and therefore could only express changes the template's
    #: permission tiers allowed. Schema and validation live in `document.py`.
    elements = models.JSONField(_("elements"), default=list, blank=True)

    #: Superseded by `elements`, kept for one release so a design saved by the
    #: old editor is still readable and so the backfill in migration 0010 can
    #: be re-run or audited. Nothing writes it any more; `document.py` and
    #: `html_builder.py` do not read it.
    overrides = models.JSONField(
        _("overrides (legacy)"),
        default=dict,
        blank=True,
        help_text=_(
            "Superseded by `elements`. Retained so pre-canvas designs remain "
            "readable; no code path writes this field."
        ),
    )
    #: Superseded by `elements`, on which an added element is simply an element
    #: with no `original_element_id`. Kept alongside `overrides` for the same
    #: reason and folded into `elements` by the same backfill.
    extra_elements = models.JSONField(
        _("extra elements (legacy)"), default=list, blank=True
    )

    objects = DesignQuerySet.as_manager()

    class Meta:
        verbose_name = _("design")
        verbose_name_plural = _("designs")
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=["agent", "-updated_at"])]

    def __str__(self) -> str:
        return self.name

    # -- the design's document ---------------------------------------------

    def ensure_document(self) -> list[dict]:
        """This design's elements, copying from the template if it has none.

        The copy normally happens once, at creation (see
        ``DesignSerializer.create``). This is the safety net for the paths that
        do not go through the serializer — the admin, a shell, a fixture, a
        design created before ``elements`` existed. It copies rather than
        raising because a design with no elements is not an error state a user
        should ever be shown; it is a design that has not been opened yet.

        Deliberately does not save: the caller decides whether this read
        becomes a write. ``views.DesignViewSet`` saves; a render does not need
        to.
        """
        if self.elements:
            return self.elements

        from apps.templates.document import elements_from_template

        self.elements = elements_from_template(self.template)
        return self.elements

    def reset_element(self, element_id: str) -> dict | None:
        """Restore one element to how the template has it.

        Matched by ``original_element_id``, so it still works after the element
        has been renamed, restyled, moved, reordered or duplicated. Returns the
        restored element, or None if this element has no template original —
        which is the case for anything the agent added, and is not an error,
        just nothing to reset to.
        """
        from apps.templates.document import element_from_template

        for index, element in enumerate(self.elements or []):
            if element.get("id") != element_id:
                continue
            original_key = element.get("original_element_id")
            if not original_key:
                return None
            source = self.template.elements.filter(key=original_key).first()
            if source is None:
                # The template element was deleted after this design was made.
                return None
            restored = element_from_template(source)
            # Keep the design-local identity so selection, layer rows and any
            # in-flight undo entry still refer to the same element.
            restored["id"] = element["id"]
            self.elements[index] = restored
            return restored
        return None

    def reset_document(self) -> list[dict]:
        """Discard every edit and re-copy the whole canvas from the template."""
        from apps.templates.document import elements_from_template

        self.elements = elements_from_template(self.template)
        return self.elements

    def clean(self) -> None:
        # Enforced here as well as in the serializer so a shell or admin cannot
        # attach an unverified listing either.
        if self.listing_id and not self.listing.is_usable_for_content:
            raise ValidationError(
                {"listing": _("Only verified listings can be used in a design.")}
            )
        # A design on a property template with no property attached is allowed
        # to exist: it is a layout the agent has not decided the subject of
        # yet. What is not allowed is *exporting* one — see
        # readiness.assess_design, which blocks on any bound element that
        # resolves empty and names it.


class ExportFormat(models.TextChoices):
    PNG = "png", _("PNG")
    JPG = "jpg", _("JPG")
    PDF = "pdf", _("PDF")


class DesignExport(TimeStampedModel):
    """One rendered export: a design at a specific dimension and format."""

    design = models.ForeignKey(
        Design, on_delete=models.CASCADE, related_name="exports"
    )
    #: Key from apps.templates.dimensions.SOCIAL_DIMENSIONS.
    dimension = models.CharField(_("dimension"), max_length=40, db_index=True)
    export_format = models.CharField(
        _("format"), max_length=8, choices=ExportFormat.choices, default=ExportFormat.PNG
    )

    # Written through the same storage abstraction as every other upload, so
    # exports move to object storage with everything else — see
    # apps/core/storage.py.
    #
    # Stays an ImageField even for a PDF export: Django's ImageField only
    # validates content when a validator says to (this one carries none), so
    # it stores any bytes exactly as a FileField would. Renaming it purely for
    # accuracy would touch the serializer's `image_url` property and every
    # frontend reference to it for no behavioural gain — not worth it for a
    # field that already works correctly for both.
    image = models.ImageField(_("image"), upload_to=design_export_upload_to)
    width = models.PositiveIntegerField(_("width"))
    height = models.PositiveIntegerField(_("height"))
    bytes = models.PositiveIntegerField(_("bytes"), default=0)
    render_ms = models.PositiveIntegerField(_("render time (ms)"), default=0)

    class Meta:
        verbose_name = _("design export")
        verbose_name_plural = _("design exports")
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["design", "dimension", "export_format"])]

    def __str__(self) -> str:
        return f"{self.design_id} {self.dimension} {self.export_format}"
