"""Brokerage, agent profile and brand kit models.

These live alongside ``User`` because they are all identity/organisation
concerns: a Brokerage is the org, an AgentProfile is the public face of a user
inside it, and a BrandKit is the visual identity of either.

Naming: the model is ``AgentProfile`` rather than ``Agent`` so it is never
confused with ``User`` or with ``Role.AGENT``. One user, one profile.

MEMBERSHIP vs ADMINISTRATION
----------------------------
Two distinct relationships, deliberately not collapsed into one field:

  * ``AgentProfile.brokerage``  — which brokerage an agent *belongs to*
    (``brokerage.agents`` in reverse).
  * ``Brokerage.admins``        — which users may *administer* a brokerage.
    A Brokerage Admin does not need an agent profile, and an agent is not
    automatically an admin of their own brokerage.

All queryset scoping in the API is derived from these two relations.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.storage import agent_photo_upload_to, brokerage_logo_upload_to
from apps.core.validators import ImageUploadValidator

#: One shared instance; the size limit is read from settings at validation
#: time, so it is not frozen into migrations.
image_upload_validator = ImageUploadValidator()

hex_color_validator = RegexValidator(
    regex=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$",
    message=_("Enter a hex colour such as #1F2937 or #FFF."),
    code="invalid_hex_color",
)


class DesignStyle(models.TextChoices):
    """Preferred look and feel, used later to pick templates and prompts."""

    MODERN = "modern", _("Modern")
    CLASSIC = "classic", _("Classic")
    MINIMAL = "minimal", _("Minimal")
    BOLD = "bold", _("Bold")
    LUXURY = "luxury", _("Luxury")
    WARM = "warm", _("Warm")


class Brokerage(TimeStampedModel):
    """A real estate brokerage: the organisation agents belong to."""

    name = models.CharField(_("name"), max_length=255, unique=True)
    # Written through the configured storage backend; see apps/core/storage.py.
    logo = models.ImageField(
        _("logo"),
        upload_to=brokerage_logo_upload_to,
        blank=True,
        null=True,
        validators=[image_upload_validator],
    )
    required_disclaimer = models.TextField(
        _("required disclaimer"),
        blank=True,
        help_text=_(
            "Regulatory text that must appear on marketing material produced "
            "for this brokerage."
        ),
    )
    website = models.URLField(_("website"), blank=True)
    phone = models.CharField(_("phone"), max_length=32, blank=True)

    admins = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="administered_brokerages",
        blank=True,
        verbose_name=_("administrators"),
        help_text=_(
            "Users who may manage this brokerage and its agents. Assigning an "
            "administrator does not by itself change their role."
        ),
    )

    class Meta:
        verbose_name = _("brokerage")
        verbose_name_plural = _("brokerages")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class AgentProfile(TimeStampedModel):
    """The public profile of an agent user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_profile",
        verbose_name=_("user"),
    )
    brokerage = models.ForeignKey(
        Brokerage,
        on_delete=models.SET_NULL,
        related_name="agents",
        null=True,
        blank=True,
        verbose_name=_("brokerage"),
        help_text=_(
            "Losing a brokerage must not delete an agent's profile, hence "
            "SET_NULL rather than CASCADE."
        ),
    )

    name = models.CharField(_("display name"), max_length=255, blank=True)
    photo = models.ImageField(
        _("photo"),
        upload_to=agent_photo_upload_to,
        blank=True,
        null=True,
        validators=[image_upload_validator],
    )
    phone = models.CharField(_("phone"), max_length=32, blank=True)
    # Public contact address, which is not necessarily the login address.
    email = models.EmailField(_("public email"), blank=True)
    job_title = models.CharField(_("job title"), max_length=120, blank=True)
    tagline = models.CharField(_("tagline"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("agent profile")
        verbose_name_plural = _("agent profiles")
        ordering = ("name", "user__email")

    def __str__(self) -> str:
        return self.name or self.user.email

    def save(self, *args, **kwargs):
        # Sensible defaults on first save so a freshly created profile is not
        # blank; the agent can overwrite either field afterwards.
        if not self.name:
            self.name = self.user.full_name or self.user.email
        if not self.email:
            self.email = self.user.email
        return super().save(*args, **kwargs)


class BrandKit(TimeStampedModel):
    """Visual identity belonging to exactly one agent OR one brokerage.

    Modelled as two nullable one-to-one links plus a database constraint rather
    than a generic foreign key: only two owner types are possible, and this
    keeps the joins, the admin and the constraint all straightforward.
    """

    agent = models.OneToOneField(
        AgentProfile,
        on_delete=models.CASCADE,
        related_name="brand_kit",
        null=True,
        blank=True,
        verbose_name=_("agent"),
    )
    brokerage = models.OneToOneField(
        Brokerage,
        on_delete=models.CASCADE,
        related_name="brand_kit",
        null=True,
        blank=True,
        verbose_name=_("brokerage"),
    )

    name = models.CharField(_("name"), max_length=120, blank=True)

    primary_color = models.CharField(
        _("primary colour"),
        max_length=7,
        default="#1F2937",
        validators=[hex_color_validator],
    )
    secondary_color = models.CharField(
        _("secondary colour"),
        max_length=7,
        default="#4B5563",
        validators=[hex_color_validator],
    )
    accent_color = models.CharField(
        _("accent colour"),
        max_length=7,
        default="#2563EB",
        validators=[hex_color_validator],
    )

    heading_font = models.CharField(_("heading font"), max_length=120, default="Inter")
    body_font = models.CharField(_("body font"), max_length=120, default="Inter")

    design_style = models.CharField(
        _("preferred design style"),
        max_length=32,
        choices=DesignStyle.choices,
        default=DesignStyle.MODERN,
    )

    class Meta:
        verbose_name = _("brand kit")
        verbose_name_plural = _("brand kits")
        ordering = ("-updated_at",)
        constraints = [
            # Enforced in the database, not just in serializers: a brand kit
            # with no owner (or two) has no meaning, and application-layer
            # checks are easy to bypass from a shell or a data migration.
            models.CheckConstraint(
                condition=models.Q(agent__isnull=False, brokerage__isnull=True)
                | models.Q(agent__isnull=True, brokerage__isnull=False),
                name="brandkit_belongs_to_exactly_one_owner",
            )
        ]

    def __str__(self) -> str:
        return self.name or f"Brand kit for {self.owner}"

    @property
    def owner(self):
        """The AgentProfile or Brokerage this kit belongs to."""
        return self.agent or self.brokerage

    @property
    def owner_type(self) -> str:
        return "agent" if self.agent_id else "brokerage"

    def save(self, *args, **kwargs):
        if not self.name and self.owner is not None:
            self.name = f"{self.owner} brand kit"
        return super().save(*args, **kwargs)
