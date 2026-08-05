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
