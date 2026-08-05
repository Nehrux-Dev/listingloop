"""The rule evaluator.

Takes a subject and a set of rules, returns a report. Deliberately dull: the
interesting behaviour lives in the rules, which are data.

ONE BAD RULE MUST NOT BREAK THE REVIEW
--------------------------------------
Rules are edited by non-engineers. A malformed regex or a stray key will
happen, and when it does the right outcome is a report saying "this rule could
not be applied", not a 500 that takes compliance offline for everyone. Each
rule is therefore evaluated inside its own try/except, and a rule that raises
is reported as an error *about the rule* rather than about the content.

That direction matters: a broken rule never invents a compliance failure
against an agent, and never silently passes content either — it is visibly
inconclusive.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Iterable

from apps.compliance.checks import CHECKS, CheckOutcome
from apps.compliance.models import (
    ComplianceRule,
    EvaluationStatus,
    LegalStatus,
    Severity,
)
from apps.compliance.subjects import ComplianceSubject

logger = logging.getLogger(__name__)


class ResultStatus:
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"
    RULE_ERROR = "rule_error"


@dataclass
class RuleResult:
    rule_id: str
    description: str
    check_type: str
    severity: str
    status: str
    message: str
    evidence: list[str] = field(default_factory=list)
    is_placeholder: bool = True
    details: dict = field(default_factory=dict)

    @property
    def blocks_export(self) -> bool:
        return self.status == ResultStatus.FAIL and self.severity == Severity.ERROR

    def as_dict(self) -> dict:
        data = asdict(self)
        data["blocks_export"] = self.blocks_export
        return data


@dataclass
class ComplianceReport:
    subject_kind: str
    subject_label: str
    results: list[RuleResult] = field(default_factory=list)

    @property
    def failures(self) -> list[RuleResult]:
        return [r for r in self.results if r.status == ResultStatus.FAIL]

    @property
    def errors(self) -> list[RuleResult]:
        return [r for r in self.failures if r.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[RuleResult]:
        return [r for r in self.failures if r.severity == Severity.WARNING]

    @property
    def rule_errors(self) -> list[RuleResult]:
        """Rules that could not be applied — a config problem, not content."""
        return [r for r in self.results if r.status == ResultStatus.RULE_ERROR]

    @property
    def blocks_export(self) -> bool:
        return bool(self.errors)

    @property
    def status(self) -> str:
        if self.errors:
            return EvaluationStatus.FAILED
        if self.warnings or self.rule_errors:
            return EvaluationStatus.FLAGGED
        return EvaluationStatus.PASSED

    @property
    def used_placeholder_rules(self) -> bool:
        """True if any rule that ran is still awaiting legal sign-off."""
        return any(result.is_placeholder for result in self.results)

    def as_dict(self) -> dict:
        return {
            "subject_kind": self.subject_kind,
            "subject_label": self.subject_label,
            "status": self.status,
            "blocks_export": self.blocks_export,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "rule_error_count": len(self.rule_errors),
            "used_placeholder_rules": self.used_placeholder_rules,
            "results": [result.as_dict() for result in self.results],
        }


def rules_for(subject: ComplianceSubject):
    """The active rules that apply to this subject."""
    return list(
        ComplianceRule.objects.active()
        .for_subject(subject.kind)
        .for_brokerage(subject.brokerage_id)
        .order_by("order", "rule_id")
    )


def evaluate(subject: ComplianceSubject, rules: Iterable[ComplianceRule] | None = None) -> ComplianceReport:
    """Run ``rules`` (or every applicable rule) against ``subject``."""
    if rules is None:
        rules = rules_for(subject)

    report = ComplianceReport(subject_kind=subject.kind, subject_label=subject.label)

    for rule in rules:
        report.results.append(_evaluate_one(rule, subject))

    return report


def _evaluate_one(rule: ComplianceRule, subject: ComplianceSubject) -> RuleResult:
    base = {
        "rule_id": rule.rule_id,
        "description": rule.description,
        "check_type": rule.check_type,
        "severity": rule.severity,
        "is_placeholder": rule.legal_status == LegalStatus.PENDING_REVIEW,
    }

    handler = CHECKS.get(rule.check_type)
    if handler is None:
        return RuleResult(
            **base,
            status=ResultStatus.RULE_ERROR,
            message=(
                f"This rule uses an unknown check type '{rule.check_type}' and "
                f"was not applied."
            ),
        )

    try:
        outcome: CheckOutcome = handler(rule, subject)
    except Exception as exc:
        # A rule row is user input. A bad one is a configuration problem to
        # report, never a crash and never a failure blamed on the content.
        logger.warning(
            "Compliance rule %r raised while evaluating %r", rule.rule_id, subject.label,
            exc_info=True,
        )
        return RuleResult(
            **base,
            status=ResultStatus.RULE_ERROR,
            message=(
                f"This rule could not be applied ({type(exc).__name__}). The "
                f"content was not checked against it."
            ),
            details={"exception": type(exc).__name__},
        )

    if outcome.details.get("rule_error"):
        return RuleResult(
            **base,
            status=ResultStatus.RULE_ERROR,
            message=outcome.message,
            evidence=outcome.evidence,
            details=outcome.details,
        )

    if outcome.details.get("skipped"):
        return RuleResult(
            **base,
            status=ResultStatus.SKIPPED,
            message=outcome.message,
            details=outcome.details,
        )

    return RuleResult(
        **base,
        status=ResultStatus.PASS if outcome.passed else ResultStatus.FAIL,
        message=outcome.message,
        evidence=outcome.evidence,
        details=outcome.details,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def store_evaluation(report: ComplianceReport, **links):
    """Persist a report against whatever it was run on.

    ``links`` takes ``design=``, ``generated_content=`` or ``content_variant=``.
    """
    from apps.compliance.models import ComplianceEvaluation

    return ComplianceEvaluation.objects.create(
        subject_kind=report.subject_kind,
        subject_label=report.subject_label[:255],
        status=report.status,
        results=[result.as_dict() for result in report.results],
        error_count=len(report.errors),
        warning_count=len(report.warnings),
        used_placeholder_rules=report.used_placeholder_rules,
        **links,
    )


def evaluate_and_store(subject: ComplianceSubject, **links):
    """Evaluate and persist in one step. Returns ``(report, evaluation)``."""
    report = evaluate(subject)
    return report, store_evaluation(report, **links)
