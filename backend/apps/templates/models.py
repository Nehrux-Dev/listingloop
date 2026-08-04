"""Template library, controlled-editing model, and saved designs.

THE PERMISSION MODEL IS THE POINT
---------------------------------
A template is not just a layout — it is a layout plus a statement about *what
an agent is allowed to change*. Four levels, from most to least restricted:

    locked        nothing may be changed. Brokerage logos, compliance text.
    content_only  swap the text or the image; geometry and styling are fixed.
    styled        content, plus colour and size within an explicit allowlist.
    free          content, styling, and move/resize within declared bounds.

Every one of those rules is enforced server-side in ``overrides.py``. The
frontend disables the controls it should, but that is a UX affordance — the
API assumes the client is hostile and re-checks every field of every override.

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
from apps.core.storage import design_export_upload_to


class TemplateCategory(models.TextChoices):
    NEW_LISTING = "new_listing", _("New Listing")
    COMING_SOON = "coming_soon", _("Coming Soon")
    OPEN_HOUSE = "open_house", _("Open House")
    JUST_SOLD = "just_sold", _("Just Sold")
    PRICE_REDUCED = "price_reduced", _("Price Reduced")
    LEASED = "leased", _("Leased")
    AGENT_INTRODUCTION = "agent_introduction", _("Agent Introduction")
    TESTIMONIAL = "testimonial", _("Testimonial")
    MARKET_UPDATE = "market_update", _("Market Update")
    NEIGHBOURHOOD_GUIDE = "neighbourhood_guide", _("Neighbourhood Guide")


class TemplateStyle(models.TextChoices):
    BOLD = "bold", _("Bold")
    MINIMAL = "minimal", _("Minimal")
    LUXURY = "luxury", _("Luxury")
    WARM = "warm", _("Warm")
    EDITORIAL = "editorial", _("Editorial")
    CLASSIC = "classic", _("Classic")


class ElementPermission(models.TextChoices):
    """What an agent may change about an element."""

    LOCKED = "locked", _("Locked — no changes")
    CONTENT_ONLY = "content_only", _("Content only — swap text or image")
    STYLED = "styled", _("Styled — content plus limited colour and size")
    FREE = "free", _("Free — move, resize and restyle within bounds")


class ElementType(models.TextChoices):
    TEXT = "text", _("Text")
    IMAGE = "image", _("Image")
    COLOR_BLOCK = "color_block", _("Colour block")
    LOGO = "logo", _("Logo")
    BADGE = "badge", _("Badge")
    DIVIDER = "divider", _("Divider")


class Template(TimeStampedModel):
    """A reusable design: canvas, background, and a set of elements."""

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

    class Meta:
        verbose_name = _("template")
        verbose_name_plural = _("templates")
        ordering = ("category", "style", "name")
        indexes = [models.Index(fields=["category", "style", "is_active"])]

    def __str__(self) -> str:
        return self.name

    @property
    def permission_map(self) -> dict[str, str]:
        """``{element_key: permission}`` — the template's editing contract.

        Exposed as one object so a client can reason about the whole template
        without walking the element list, and so the contract is visible in the
        API rather than implied.
        """
        return {element.key: element.permission for element in self.elements.all()}

    def editable_keys(self) -> set[str]:
        return {
            element.key
            for element in self.elements.all()
            if element.permission != ElementPermission.LOCKED
        }


class TemplateElement(models.Model):
    """One element of a template, and the rules for changing it."""

    template = models.ForeignKey(
        Template, on_delete=models.CASCADE, related_name="elements"
    )
    #: Stable identifier used as the key in ``Design.overrides``.
    key = models.SlugField(_("key"), max_length=80)
    label = models.CharField(_("label"), max_length=120, blank=True)

    element_type = models.CharField(
        _("element type"), max_length=32, choices=ElementType.choices
    )
    permission = models.CharField(
        _("permission"),
        max_length=32,
        choices=ElementPermission.choices,
        default=ElementPermission.LOCKED,
        help_text=_("Locked by default: an element is not editable unless it says so."),
    )

    #: Fractions of the canvas, 0..1: {"x":.., "y":.., "width":.., "height":..}
    geometry = models.JSONField(_("geometry"), default=dict)
    #: Rendering properties: text, colour, font_size_ratio, align, weight, etc.
    style_properties = models.JSONField(_("style properties"), default=dict, blank=True)

    #: Where the content comes from when not overridden, e.g.
    #: "listing.price" or "brand_kit.primary_color". Resolved at render time.
    content_source = models.CharField(_("content source"), max_length=120, blank=True)
    #: Literal fallback when there is no source and no override.
    default_content = models.TextField(_("default content"), blank=True)

    constraints = models.JSONField(
        _("constraints"),
        default=dict,
        blank=True,
        help_text=_(
            "Limits applied to overrides: allowed_colors, min/max font size "
            "ratio, bounds for movement, max_length for text."
        ),
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

    # -- permission helpers -------------------------------------------------

    @property
    def is_locked(self) -> bool:
        return self.permission == ElementPermission.LOCKED

    @property
    def allows_content(self) -> bool:
        return self.permission != ElementPermission.LOCKED

    @property
    def allows_styling(self) -> bool:
        return self.permission in (ElementPermission.STYLED, ElementPermission.FREE)

    @property
    def allows_geometry(self) -> bool:
        return self.permission == ElementPermission.FREE


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
            "Optional: agent-introduction and market-update templates need no "
            "listing. When set, it must be a verified listing."
        ),
    )

    overrides = models.JSONField(
        _("overrides"),
        default=dict,
        blank=True,
        help_text=_(
            "{element_key: {field: value}}. Validated against each element's "
            "permission and constraints before it is ever stored."
        ),
    )

    objects = DesignQuerySet.as_manager()

    class Meta:
        verbose_name = _("design")
        verbose_name_plural = _("designs")
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=["agent", "-updated_at"])]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        # Enforced here as well as in the serializer so a shell or admin cannot
        # attach an unverified listing either.
        if self.listing_id and not self.listing.is_usable_for_content:
            raise ValidationError(
                {"listing": _("Only verified listings can be used in a design.")}
            )


class ExportFormat(models.TextChoices):
    PNG = "png", _("PNG")
    JPG = "jpg", _("JPG")


class DesignExport(TimeStampedModel):
    """One rendered image: a design at a specific dimension and format."""

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
