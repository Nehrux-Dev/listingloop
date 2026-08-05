"""Admin for compliance rules.

This is the product surface for whoever owns the rules, who will not be an
engineer. So it does more than register a model:

  * the shape of ``rule_data`` for the selected check type is shown inline,
    with a worked example, rather than left to be guessed;
  * bad ``rule_data`` is rejected on save with a readable message, because a
    rule that saves and then silently never fires is worse than an error;
  * placeholder rules are visually obvious in the list, so nobody assumes the
    seeded set is authoritative;
  * a rule can be tried against sample text from the change form, so the
    author can see what it does before it starts blocking exports.
"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.compliance.checks import (
    available_check_types,
    available_custom_handlers,
)
from apps.compliance.engine import evaluate
from apps.compliance.models import (
    ComplianceEvaluation,
    ComplianceRule,
    LegalStatus,
    Severity,
)
from apps.compliance.subjects import from_text


class ComplianceRuleForm(forms.ModelForm):
    """Adds a scratch field for trying the rule out."""

    test_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Try this rule against some text",
        help_text=(
            "Optional. Paste a sample caption here and save — the result is "
            "shown as a message at the top. Nothing is stored."
        ),
    )

    class Meta:
        model = ComplianceRule
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rule_data"].help_text = mark_safe(_rule_data_help())


def _rule_data_help() -> str:
    from apps.compliance.models import RULE_DATA_HELP

    rows = "".join(
        f"<tr><th style='text-align:left;padding-right:12px;vertical-align:top'>"
        f"<code>{check_type}</code></th><td><code>{example}</code></td></tr>"
        for check_type, example in RULE_DATA_HELP.items()
    )
    handlers = ", ".join(available_custom_handlers()) or "(none registered)"
    return (
        "<strong>What to put here, by check type:</strong>"
        f"<table style='margin-top:6px'>{rows}</table>"
        f"<p style='margin-top:6px'>Registered custom handlers: <code>{handlers}</code>. "
        "A handler must exist in code — naming one that does not will not run "
        "anything.</p>"
    )


@admin.register(ComplianceRule)
class ComplianceRuleAdmin(admin.ModelAdmin):
    form = ComplianceRuleForm

    list_display = (
        "rule_id",
        "severity_badge",
        "check_type",
        "applies_to",
        "scope",
        "is_active",
        "legal_badge",
        "order",
    )
    list_filter = ("legal_status", "is_active", "severity", "check_type", "applies_to")
    search_fields = ("rule_id", "description", "admin_notes")
    list_editable = ("is_active", "order")
    ordering = ("order", "rule_id")
    autocomplete_fields = ("brokerage",)
    save_on_top = True

    fieldsets = (
        (
            None,
            {
                "fields": ("rule_id", "description", "is_active"),
                "description": (
                    "<strong>Rules are data, not code.</strong> Anything you change "
                    "here takes effect immediately — no deployment needed."
                ),
            },
        ),
        (
            "What to check",
            {
                "fields": ("check_type", "rule_data", "test_text"),
            },
        ),
        (
            "When it applies and how hard",
            {
                "fields": ("severity", "applies_to", "brokerage", "order"),
                "description": (
                    "<strong>Error</strong> blocks an agent from exporting. "
                    "<strong>Warning</strong> is shown but does not block. "
                    "Leave <em>brokerage</em> blank to apply the rule everywhere."
                ),
            },
        ),
        (
            "Legal review",
            {
                "fields": ("legal_status", "admin_notes"),
                "description": (
                    "Seeded rules are <strong>PENDING LEGAL REVIEW</strong> and are "
                    "placeholders. Only set a rule to Approved once its wording has "
                    "actually been signed off."
                ),
            },
        ),
    )
    readonly_fields = ()

    @admin.display(description="Severity", ordering="severity")
    def severity_badge(self, obj: ComplianceRule):
        colours = {
            Severity.ERROR: "#b91c1c",
            Severity.WARNING: "#b45309",
            Severity.INFO: "#475569",
        }
        return format_html(
            '<span style="color:{};font-weight:600">{}</span>',
            colours.get(obj.severity, "#475569"),
            obj.get_severity_display().split(" —")[0],
        )

    @admin.display(description="Legal", ordering="legal_status")
    def legal_badge(self, obj: ComplianceRule):
        if obj.legal_status == LegalStatus.APPROVED:
            return format_html('<span style="color:#047857">Approved</span>')
        if obj.legal_status == LegalStatus.SUPERSEDED:
            return format_html('<span style="color:#64748b">Superseded</span>')
        return format_html(
            '<span style="color:#b45309;font-weight:600">PENDING REVIEW</span>'
        )

    @admin.display(description="Scope")
    def scope(self, obj: ComplianceRule) -> str:
        return obj.brokerage.name if obj.brokerage else "All brokerages"

    def changelist_view(self, request, extra_context=None):
        pending = ComplianceRule.objects.filter(
            legal_status=LegalStatus.PENDING_REVIEW, is_active=True
        ).count()
        if pending:
            messages.warning(
                request,
                f"{pending} active rule(s) are PENDING LEGAL REVIEW. These are "
                f"placeholders — their wording has not been approved and should "
                f"not be relied on.",
            )
        return super().changelist_view(request, extra_context)

    def save_model(self, request, obj, form, change) -> None:
        super().save_model(request, obj, form, change)

        # Try the rule out, if the author asked. Nothing is stored; this is a
        # scratchpad so a non-engineer can see what their rule does.
        sample = (form.cleaned_data.get("test_text") or "").strip()
        if not sample:
            return

        report = evaluate(from_text(sample, kind=obj.applies_to), [obj])
        result = report.results[0] if report.results else None
        if result is None:
            return

        level = {
            "pass": messages.SUCCESS,
            "fail": messages.ERROR,
            "skipped": messages.INFO,
            "rule_error": messages.WARNING,
        }.get(result.status, messages.INFO)
        self.message_user(
            request,
            f"Test against your sample text — {result.status.upper()}: {result.message}",
            level=level,
        )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "check_type" in form.base_fields:
            form.base_fields["check_type"].help_text = (
                "Available: " + ", ".join(available_check_types())
            )
        return form


@admin.register(ComplianceEvaluation)
class ComplianceEvaluationAdmin(admin.ModelAdmin):
    """Audit trail. Read-only — these are records of what happened."""

    list_display = (
        "created_at",
        "subject_kind",
        "subject_label",
        "status",
        "error_count",
        "warning_count",
        "used_placeholder_rules",
    )
    list_filter = ("status", "subject_kind", "used_placeholder_rules")
    search_fields = ("subject_label",)
    readonly_fields = tuple(field.name for field in ComplianceEvaluation._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
