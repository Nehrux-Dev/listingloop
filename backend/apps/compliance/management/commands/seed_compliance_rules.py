"""Seed a PLACEHOLDER compliance rule set.

===========================================================================
NOTHING IN THIS FILE HAS BEEN THROUGH LEGAL REVIEW.
===========================================================================

Every rule below is seeded with ``legal_status = PENDING_REVIEW`` and an
``admin_notes`` entry saying so. They exist to prove the engine works end to
end and to give whoever writes the real rules something concrete to edit —
they are illustrative, not authoritative.

Do not treat any wording here as a compliance requirement. Do not enable
blocking severities in a real deployment until someone with the authority to
sign them off has reviewed each rule and set it to APPROVED.

Re-runnable: rules are matched on ``rule_id`` and updated in place. Rules that
have been moved to APPROVED are left alone, so a re-seed cannot quietly revert
wording that someone has since signed off.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.compliance.models import (
    AppliesTo,
    CheckType,
    ComplianceRule,
    LegalStatus,
    Severity,
)

PLACEHOLDER_NOTE = (
    "PENDING LEGAL REVIEW — placeholder seeded by seed_compliance_rules. "
    "The wording, severity and scope of this rule are illustrative and have "
    "NOT been approved. Replace or confirm before relying on it."
)

PLACEHOLDER_RULES: list[dict] = [
    {
        "rule_id": "placeholder-brokerage-name-present",
        "description": (
            "Marketing material should identify the brokerage it is published by."
        ),
        "check_type": CheckType.REQUIRED_FIELD_PRESENT,
        "rule_data": {"field": "brokerage_name", "label": "Brokerage name"},
        "severity": Severity.ERROR,
        "applies_to": AppliesTo.ALL,
        "order": 10,
    },
    {
        "rule_id": "placeholder-disclaimer-present",
        "description": (
            "The brokerage's required disclaimer should appear on the material."
        ),
        "check_type": CheckType.DISCLAIMER_PRESENT,
        "rule_data": {
            "text": (
                "All information is provided as a guide only. Prospective "
                "purchasers should make their own enquiries."
            ),
            "match": "all_words",
        },
        "severity": Severity.WARNING,
        "applies_to": AppliesTo.DESIGN,
        "order": 20,
    },
    {
        "rule_id": "placeholder-no-guaranteed-return-claims",
        "description": (
            "Marketing material should not promise a financial return."
        ),
        "check_type": CheckType.PROHIBITED_PHRASE,
        "rule_data": {
            "phrases": [
                "guaranteed return",
                "guaranteed rental",
                "guaranteed income",
                "risk free",
                "risk-free",
                "no risk",
                "assured return",
                "will double in value",
                "cannot lose",
            ],
            "whole_word": True,
        },
        "severity": Severity.ERROR,
        "applies_to": AppliesTo.ALL,
        "order": 30,
    },
    {
        "rule_id": "placeholder-no-numeric-yield-claims",
        "description": (
            "Marketing material should not state a numeric yield or return."
        ),
        "check_type": CheckType.PROHIBITED_PATTERN,
        "rule_data": {
            # One optional qualifier between the figure and the noun, so
            # "6.5% rental yield" and "7% net return" are caught along with
            # "6% yield". An earlier draft only allowed "gross"/"net" and
            # missed "rental yield", which is the commonest phrasing of all —
            # a rule that looks like coverage and is not is worse than none.
            # Capped at one word so "6% of buyers return" does not match.
            "pattern": (
                r"\b\d+(?:\.\d+)?\s*(?:%|per\s?cent)\s*(?:\w+\s+)?"
                r"(?:yield|returns?|roi|growth)\b"
            ),
            "flags": "i",
        },
        "severity": Severity.ERROR,
        "applies_to": AppliesTo.ALL,
        "order": 40,
    },
    {
        "rule_id": "placeholder-no-planning-approval-claims",
        "description": (
            "Marketing material should not assert planning or council approval."
        ),
        "check_type": CheckType.PROHIBITED_PHRASE,
        "rule_data": {
            "phrases": [
                "council approved",
                "da approved",
                "development approved",
                "planning permission granted",
                "fully approved",
            ],
            "whole_word": True,
        },
        "severity": Severity.WARNING,
        "applies_to": AppliesTo.ALL,
        "order": 50,
    },
    {
        "rule_id": "placeholder-caption-length",
        "description": (
            "Captions longer than the platform limit will be truncated when posted."
        ),
        "check_type": CheckType.LENGTH_LIMIT,
        "rule_data": {"field": "instagram_caption", "max": 2200},
        "severity": Severity.WARNING,
        "applies_to": AppliesTo.AI_CONTENT,
        "order": 60,
    },
    {
        "rule_id": "placeholder-agent-contact-present",
        "description": "Material should carry a contact number for the agent.",
        "check_type": CheckType.REQUIRED_FIELD_PRESENT,
        "rule_data": {"field": "agent_phone", "label": "Agent phone number"},
        "severity": Severity.WARNING,
        "applies_to": AppliesTo.DESIGN,
        "order": 70,
    },
    {
        "rule_id": "placeholder-example-custom-handler",
        "description": (
            "EXAMPLE of a code-backed rule: a price should carry a qualifier "
            "such as “guide” or “offers”."
        ),
        "check_type": CheckType.CUSTOM,
        "rule_data": {"handler": "example_price_needs_qualifier"},
        "severity": Severity.INFO,
        "applies_to": AppliesTo.ALL,
        "order": 80,
    },
]


class Command(BaseCommand):
    help = "Seed the PLACEHOLDER compliance rule set (pending legal review)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--reset-approved",
            action="store_true",
            help=(
                "Also overwrite rules that have been marked Approved. "
                "Destroys signed-off wording — you almost never want this."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        reset_approved = options["reset_approved"]
        created_count = updated_count = skipped_count = 0

        for spec in PLACEHOLDER_RULES:
            existing = ComplianceRule.objects.filter(rule_id=spec["rule_id"]).first()

            if (
                existing
                and existing.legal_status == LegalStatus.APPROVED
                and not reset_approved
            ):
                # Someone signed this off. A re-seed must not silently revert it.
                skipped_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"skipped (approved): {spec['rule_id']} — pass "
                        f"--reset-approved to overwrite"
                    )
                )
                continue

            defaults = {
                **spec,
                "legal_status": LegalStatus.PENDING_REVIEW,
                "admin_notes": PLACEHOLDER_NOTE,
                "is_active": True,
            }
            defaults.pop("rule_id")

            _, created = ComplianceRule.objects.update_or_create(
                rule_id=spec["rule_id"], defaults=defaults
            )
            if created:
                created_count += 1
            else:
                updated_count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"{'created' if created else 'updated'}: {spec['rule_id']}"
                )
            )

        total = ComplianceRule.objects.count()
        pending = ComplianceRule.objects.filter(
            legal_status=LegalStatus.PENDING_REVIEW
        ).count()

        self.stdout.write("")
        self.stdout.write(
            f"{created_count} created, {updated_count} updated, {skipped_count} skipped."
        )
        self.stdout.write(f"{total} rules total, {pending} PENDING LEGAL REVIEW.")
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "These are PLACEHOLDERS. No wording here has been reviewed or "
                "approved. Edit them in the Django admin at /admin/compliance/"
                "compliancerule/ and set each to Approved only once it has been "
                "signed off."
            )
        )
