"""AI-generated marketing copy, and the record of how it was produced.

TWO INDEPENDENT AXES, DELIBERATELY NOT COLLAPSED
------------------------------------------------
``job_status``     did the generation finish?      queued / running / ready / failed
``review_status``  has a human accepted it?        draft / approved / rejected
``validation``     did it survive the fact check?  passed / flagged / rejected

A generation can be ``ready`` (the API answered) and still be validation-
``rejected`` (it invented a number), and it starts as review-``draft`` either
way. Folding these into one field would make "the model returned something"
indistinguishable from "a person approved it", which is exactly the distinction
that matters for copy that goes out under an agent's name.

REJECTED TEXT IS NOT STORED AS USABLE COPY
------------------------------------------
When validation rejects a response, ``caption`` and ``hashtags`` stay empty and
the model's words go to ``rejected_output`` instead. The text is kept — it is
needed to debug the prompt — but it is not sitting in the field the UI renders,
where someone could copy an invented claim out of it by accident.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class JobStatus(models.TextChoices):
    QUEUED = "queued", _("Queued")
    RUNNING = "running", _("Running")
    READY = "ready", _("Ready")
    FAILED = "failed", _("Failed")


class ReviewStatus(models.TextChoices):
    DRAFT = "draft", _("Draft — awaiting agent review")
    APPROVED = "approved", _("Approved by agent")
    REJECTED = "rejected", _("Rejected by agent")


class ValidationStatus(models.TextChoices):
    PENDING = "pending", _("Not yet validated")
    PASSED = "passed", _("Passed")
    FLAGGED = "flagged", _("Passed with warnings")
    REJECTED = "rejected", _("Rejected — unverifiable claims")


class ContentKind(models.TextChoices):
    SOCIAL_CAPTION = "social_caption", _("Social caption and hashtags")
    CONTENT_PACK = "content_pack", _("Full content pack")


class VariantKind(models.TextChoices):
    """The pieces produced by one generation.

    All of these come back from a SINGLE API call. Asking six times would cost
    roughly six times as much and, worse, would let the variants drift apart —
    six independent calls can each pick a different fact to lead with.
    """

    INSTAGRAM_CAPTION = "instagram_caption", _("Instagram caption")
    FACEBOOK_CAPTION = "facebook_caption", _("Facebook caption")
    LINKEDIN_CAPTION = "linkedin_caption", _("LinkedIn caption")
    SHARING_MESSAGE = "sharing_message", _("Sharing message")
    PROPERTY_DESCRIPTION = "property_description", _("Property page description")
    HASHTAGS = "hashtags", _("Hashtags")


#: Order the UI displays them in.
VARIANT_ORDER: tuple[str, ...] = (
    VariantKind.INSTAGRAM_CAPTION,
    VariantKind.FACEBOOK_CAPTION,
    VariantKind.LINKEDIN_CAPTION,
    VariantKind.SHARING_MESSAGE,
    VariantKind.PROPERTY_DESCRIPTION,
    VariantKind.HASHTAGS,
)


class GeneratedContentQuerySet(models.QuerySet):
    def for_user(self, user):
        """Same scoping as listings and designs."""
        if not user.is_authenticated:
            return self.none()
        if user.is_nehrux_admin:
            return self
        if user.is_brokerage_admin:
            return self.filter(listing__agent__brokerage__admins=user).distinct()
        return self.filter(listing__agent__user=user)

    def in_language(self, code: str):
        return self.filter(language=code)

    def usable(self):
        """Content an agent may actually publish."""
        return self.filter(
            job_status=JobStatus.READY,
            validation_status__in=[ValidationStatus.PASSED, ValidationStatus.FLAGGED],
        )


class GeneratedContent(TimeStampedModel):
    """One generation attempt for one listing."""

    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.CASCADE,
        related_name="generated_content",
        verbose_name=_("listing"),
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="content_generations",
    )
    kind = models.CharField(
        _("kind"),
        max_length=32,
        choices=ContentKind.choices,
        default=ContentKind.SOCIAL_CAPTION,
    )
    #: One generation per language, so each language's pack is stored, reviewed
    #: and costed on its own. A single row holding six languages would make
    #: "approve the French copy" impossible to express.
    language = models.CharField(
        _("language"), max_length=16, default="en", db_index=True
    )

    # -- job lifecycle ------------------------------------------------------
    job_status = models.CharField(
        _("job status"),
        max_length=16,
        choices=JobStatus.choices,
        default=JobStatus.QUEUED,
        db_index=True,
    )
    error_message = models.TextField(_("error message"), blank=True)
    started_at = models.DateTimeField(_("started at"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)

    # -- result -------------------------------------------------------------
    caption = models.TextField(_("caption"), blank=True)
    hashtags = models.JSONField(_("hashtags"), default=list, blank=True)
    #: Populated INSTEAD of caption/hashtags when validation rejects the output.
    rejected_output = models.JSONField(_("rejected output"), default=dict, blank=True)

    # -- validation ---------------------------------------------------------
    validation_status = models.CharField(
        _("validation status"),
        max_length=16,
        choices=ValidationStatus.choices,
        default=ValidationStatus.PENDING,
        db_index=True,
    )
    validation_issues = models.JSONField(_("validation issues"), default=list, blank=True)

    # -- review -------------------------------------------------------------
    review_status = models.CharField(
        _("review status"),
        max_length=16,
        choices=ReviewStatus.choices,
        default=ReviewStatus.DRAFT,
        db_index=True,
    )
    reviewed_at = models.DateTimeField(_("reviewed at"), null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_content",
    )

    # -- provenance and cost ------------------------------------------------
    model_name = models.CharField(_("model"), max_length=80, blank=True)
    prompt_version = models.CharField(_("prompt version"), max_length=20, blank=True)
    #: The exact facts sent to the model. Without this a caption cannot be
    #: audited later, because the listing may have changed since.
    prompt_facts = models.JSONField(_("prompt facts"), default=dict, blank=True)

    prompt_tokens = models.PositiveIntegerField(_("prompt tokens"), default=0)
    completion_tokens = models.PositiveIntegerField(_("completion tokens"), default=0)
    total_tokens = models.PositiveIntegerField(_("total tokens"), default=0)
    estimated_cost_usd = models.DecimalField(
        _("estimated cost (USD)"),
        max_digits=10,
        # Six places because a single small-model call costs fractions of a
        # cent; rounding to four would store most generations as 0.0000.
        decimal_places=6,
        default=Decimal("0"),
    )
    duration_ms = models.PositiveIntegerField(_("duration (ms)"), default=0)

    objects = GeneratedContentQuerySet.as_manager()

    class Meta:
        verbose_name = _("generated content")
        verbose_name_plural = _("generated content")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["listing", "-created_at"]),
            models.Index(fields=["job_status", "-created_at"]),
            models.Index(fields=["listing", "language", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} for listing {self.listing_id} ({self.job_status})"

    @property
    def is_ready(self) -> bool:
        return self.job_status == JobStatus.READY

    @property
    def is_usable(self) -> bool:
        """Ready, and not rejected by the fact check."""
        return self.is_ready and self.validation_status in (
            ValidationStatus.PASSED,
            ValidationStatus.FLAGGED,
        )

    @property
    def has_errors(self) -> bool:
        return any(issue.get("severity") == "error" for issue in self.validation_issues)

    @property
    def usable_variant_count(self) -> int:
        return sum(1 for variant in self.variants.all() if variant.is_usable)

    @property
    def language_name(self) -> str:
        from apps.ai_content.languages import KNOWN_LANGUAGES

        known = KNOWN_LANGUAGES.get(self.language)
        return known.name if known else self.language

    @property
    def has_partial_validation(self) -> bool:
        """True when the fact-check could not fully read this language."""
        from apps.ai_content.languages import KNOWN_LANGUAGES

        known = KNOWN_LANGUAGES.get(self.language)
        return bool(known and not known.is_fully_covered)


class ContentVariant(TimeStampedModel):
    """One piece of copy from a generation, reviewed on its own.

    Variants are rows rather than columns on ``GeneratedContent`` because each
    is separately validated, separately editable and separately approved — an
    agent can publish the Instagram caption while rejecting the LinkedIn one.
    Columns would also mean a migration every time a platform is added.
    """

    generation = models.ForeignKey(
        GeneratedContent, on_delete=models.CASCADE, related_name="variants"
    )
    kind = models.CharField(_("kind"), max_length=32, choices=VariantKind.choices)

    #: Prose variants use ``text``; the hashtag variant uses ``items``.
    text = models.TextField(_("text"), blank=True)
    items = models.JSONField(_("items"), default=list, blank=True)

    #: Set instead of text/items when this variant failed the fact check, so
    #: rejected copy is never in the field the UI renders as publishable.
    rejected_text = models.TextField(_("rejected text"), blank=True)
    rejected_items = models.JSONField(_("rejected items"), default=list, blank=True)

    validation_status = models.CharField(
        _("validation status"),
        max_length=16,
        choices=ValidationStatus.choices,
        default=ValidationStatus.PENDING,
        db_index=True,
    )
    validation_issues = models.JSONField(_("validation issues"), default=list, blank=True)

    review_status = models.CharField(
        _("review status"),
        max_length=16,
        choices=ReviewStatus.choices,
        default=ReviewStatus.DRAFT,
        db_index=True,
    )
    reviewed_at = models.DateTimeField(_("reviewed at"), null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_variants",
    )

    #: True once an agent has changed the words themselves. Recorded because it
    #: changes who is responsible for the claims in them — see `is_usable`.
    is_edited = models.BooleanField(_("edited by agent"), default=False)
    original_text = models.TextField(_("original text"), blank=True)
    edited_at = models.DateTimeField(_("edited at"), null=True, blank=True)

    class Meta:
        verbose_name = _("content variant")
        verbose_name_plural = _("content variants")
        ordering = ("generation_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["generation", "kind"], name="unique_variant_kind_per_generation"
            )
        ]
        indexes = [models.Index(fields=["generation", "kind"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} ({self.validation_status})"

    @property
    def is_hashtags(self) -> bool:
        return self.kind == VariantKind.HASHTAGS

    @property
    def display_text(self) -> str:
        """What to show, whether it passed or not."""
        if self.is_hashtags:
            items = self.items or self.rejected_items
            return " ".join(items)
        return self.text or self.rejected_text

    @property
    def is_usable(self) -> bool:
        """May this variant be approved and published?

        For MODEL output the rule is strict: a fact-check error blocks it. That
        is the guarantee the whole pipeline exists to provide.

        For AGENT-EDITED text it is advisory. The validator's job is to stop the
        model inventing things, not to stop a licensed agent writing a sentence
        — they may well know something the listing does not record. Warnings are
        still shown, and ``is_edited`` records who the words belong to.
        """
        if self.is_edited:
            return bool(self.display_text.strip())
        return self.validation_status in (
            ValidationStatus.PASSED,
            ValidationStatus.FLAGGED,
        )

    @property
    def has_errors(self) -> bool:
        return any(issue.get("severity") == "error" for issue in self.validation_issues)
