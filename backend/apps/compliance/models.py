"""Data-driven compliance rules.

WHY THERE IS NO BUSINESS LOGIC IN HERE
--------------------------------------
The actual rules — which disclaimer, which phrases, which fields — are not
settled and will be decided by people who do not write Python. So this app
ships *check types*, which are generic primitives, and the rules themselves
live in the database where a non-engineer can edit them in the admin.

Adding a new rule should never require a deployment. Adding a new *kind* of
check does, and that is the line: if a requirement can be expressed as "this
phrase must not appear" or "this field must be filled in", it is data.

EVERYTHING SEEDED IS A PLACEHOLDER
----------------------------------
``legal_status`` defaults to PENDING_REVIEW and the seeded set is explicitly
marked as such. It is there so the pipeline can be wired up and demonstrated,
not because anyone has approved the wording. Nothing should be treated as
final until someone with the authority to do so sets a rule to APPROVED.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class CheckType(models.TextChoices):
    """The generic primitives a rule can be built from.

    Each maps to a handler in ``apps.compliance.checks``. The shape of
    ``rule_data`` depends on which one is chosen — see ``RULE_DATA_HELP``.
    """

    REQUIRED_FIELD_PRESENT = "required_field_present", _("Required field present")
    DISCLAIMER_PRESENT = "disclaimer_present", _("Disclaimer present")
    PROHIBITED_PHRASE = "prohibited_phrase", _("Prohibited phrase")
    REQUIRED_PHRASE = "required_phrase", _("Required phrase")
    PROHIBITED_PATTERN = "prohibited_pattern", _("Prohibited pattern (regex)")
    LENGTH_LIMIT = "length_limit", _("Length limit")
    CUSTOM = "custom", _("Custom (registered handler)")


class Severity(models.TextChoices):
    """What a failure means.

    ERROR blocks an export; WARNING is shown and does not. Deciding this per
    rule rather than globally is what lets a genuinely regulatory requirement
    stop a publish while a house-style preference merely nags.
    """

    ERROR = "error", _("Error — blocks export")
    WARNING = "warning", _("Warning — shown, does not block")
    INFO = "info", _("Info — advisory only")


class LegalStatus(models.TextChoices):
    PENDING_REVIEW = "pending_review", _("PENDING LEGAL REVIEW — placeholder")
    APPROVED = "approved", _("Approved")
    SUPERSEDED = "superseded", _("Superseded")


class AppliesTo(models.TextChoices):
    """Which kinds of content a rule is checked against."""

    ALL = "all", _("All content")
    AI_CONTENT = "ai_content", _("AI-generated content")
    DESIGN = "design", _("Designs and exports")
    LISTING = "listing", _("Listings")


#: Shown in the admin so a non-engineer can see the shape each check expects.
RULE_DATA_HELP: dict[str, str] = {
    CheckType.REQUIRED_FIELD_PRESENT: (
        '{"field": "brokerage_name", "label": "Brokerage name"}'
    ),
    CheckType.DISCLAIMER_PRESENT: (
        '{"text": "All information is provided as a guide only.", '
        '"match": "normalised"}   — match: "normalised" | "exact" | "all_words"'
    ),
    CheckType.PROHIBITED_PHRASE: (
        '{"phrases": ["guaranteed return", "risk free"], "whole_word": true}'
    ),
    CheckType.REQUIRED_PHRASE: (
        '{"phrases": ["licensed agent"], "mode": "any"}   — mode: "any" | "all"'
    ),
    CheckType.PROHIBITED_PATTERN: (
        r'{"pattern": "\\b\\d+(\\.\\d+)?%\\s*(yield|return)\\b", "flags": "i"}'
    ),
    CheckType.LENGTH_LIMIT: (
        '{"field": "caption", "max": 2200, "min": 0}   — field optional; '
        "omit to check all text"
    ),
    CheckType.CUSTOM: (
        '{"handler": "example_no_bare_price"}   — must name a handler '
        "registered in code; arbitrary paths are never imported"
    ),
}


class ComplianceRuleQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def for_subject(self, subject_kind: str):
        """Rules that apply to this kind of content."""
        return self.filter(
            models.Q(applies_to=AppliesTo.ALL) | models.Q(applies_to=subject_kind)
        )

    def for_brokerage(self, brokerage_id):
        """Global rules plus this brokerage's own."""
        return self.filter(
            models.Q(brokerage__isnull=True) | models.Q(brokerage_id=brokerage_id)
        )


class ComplianceRule(TimeStampedModel):
    """One checkable requirement, defined entirely by data."""

    rule_id = models.SlugField(
        _("rule id"),
        max_length=80,
        unique=True,
        help_text=_(
            "Stable identifier used in reports and audit trails. Do not reuse "
            "an id for a different requirement — supersede it and add a new one."
        ),
    )
    description = models.CharField(
        _("description"),
        max_length=255,
        help_text=_("Shown to the agent when this rule fails. Write it as advice."),
    )
    check_type = models.CharField(
        _("check type"), max_length=40, choices=CheckType.choices, db_index=True
    )
    rule_data = models.JSONField(
        _("rule data"),
        default=dict,
        blank=True,
        help_text=_("The specifics. The shape depends on the check type."),
    )

    severity = models.CharField(
        _("severity"), max_length=16, choices=Severity.choices, default=Severity.WARNING
    )
    applies_to = models.CharField(
        _("applies to"), max_length=24, choices=AppliesTo.choices, default=AppliesTo.ALL
    )
    #: Null means the rule applies everywhere; set it to scope a rule to one
    #: brokerage without affecting anyone else.
    brokerage = models.ForeignKey(
        "accounts.Brokerage",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="compliance_rules",
        verbose_name=_("brokerage"),
        help_text=_("Leave blank for a rule that applies to every brokerage."),
    )

    is_active = models.BooleanField(
        _("active"),
        default=True,
        db_index=True,
        help_text=_("Uncheck to stop applying this rule without deleting it."),
    )
    legal_status = models.CharField(
        _("legal status"),
        max_length=24,
        choices=LegalStatus.choices,
        default=LegalStatus.PENDING_REVIEW,
        db_index=True,
        help_text=_(
            "Rules ship as PENDING LEGAL REVIEW. Only set this to Approved if "
            "you have the authority to sign the wording off."
        ),
    )
    admin_notes = models.TextField(
        _("notes"),
        blank=True,
        help_text=_("Provenance, source of the requirement, review history."),
    )

    order = models.PositiveIntegerField(
        _("order"), default=100, help_text=_("Lower numbers are reported first.")
    )

    objects = ComplianceRuleQuerySet.as_manager()

    class Meta:
        verbose_name = _("compliance rule")
        verbose_name_plural = _("compliance rules")
        ordering = ("order", "rule_id")
        indexes = [models.Index(fields=["is_active", "applies_to"])]

    def __str__(self) -> str:
        return f"{self.rule_id} ({self.get_check_type_display()})"

    @property
    def is_placeholder(self) -> bool:
        return self.legal_status == LegalStatus.PENDING_REVIEW

    @property
    def blocks_export(self) -> bool:
        return self.severity == Severity.ERROR

    def clean(self) -> None:
        """Validate ``rule_data`` for the chosen check type.

        Done here so a non-engineer editing a rule in the admin gets a clear
        message immediately, rather than a rule that saves cleanly and then
        silently never fires.
        """
        from django.core.exceptions import ValidationError

        from apps.compliance.checks import validate_rule_data

        errors = validate_rule_data(self.check_type, self.rule_data or {})
        if errors:
            raise ValidationError({"rule_data": errors})


class EvaluationStatus(models.TextChoices):
    PASSED = "passed", _("Passed")
    FLAGGED = "flagged", _("Passed with warnings")
    FAILED = "failed", _("Failed")


class ComplianceEvaluation(TimeStampedModel):
    """A stored result of running the engine over one piece of content.

    Kept as its own model with nullable links rather than columns on Design or
    GeneratedContent, so compliance stays decoupled: it can be pointed at
    something new without migrating that thing's table.
    """

    design = models.ForeignKey(
        "templates.Design",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="compliance_evaluations",
    )
    generated_content = models.ForeignKey(
        "ai_content.GeneratedContent",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="compliance_evaluations",
    )
    content_variant = models.ForeignKey(
        "ai_content.ContentVariant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="compliance_evaluations",
    )

    subject_kind = models.CharField(_("subject kind"), max_length=32)
    subject_label = models.CharField(_("subject"), max_length=255, blank=True)

    status = models.CharField(
        _("status"), max_length=16, choices=EvaluationStatus.choices, db_index=True
    )
    #: Full per-rule results, so a decision can be explained months later even
    #: if the rules have changed since.
    results = models.JSONField(_("results"), default=list, blank=True)
    error_count = models.PositiveIntegerField(_("errors"), default=0)
    warning_count = models.PositiveIntegerField(_("warnings"), default=0)
    #: True when any rule that contributed was still PENDING LEGAL REVIEW.
    used_placeholder_rules = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("compliance evaluation")
        verbose_name_plural = _("compliance evaluations")
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.subject_kind} {self.subject_label}: {self.status}"

    @property
    def blocks_export(self) -> bool:
        return self.error_count > 0
