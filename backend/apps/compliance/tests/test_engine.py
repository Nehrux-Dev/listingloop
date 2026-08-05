"""Rule evaluation logic.

Every rule in this file is constructed by the test. None of the placeholder
seed data is asserted on: that content is provisional and will be rewritten by
whoever owns it, and a test that pinned it would fail on the day someone did
their job. What is tested is the *engine* — given a known rule and known input,
does it produce the right verdict and a message a human can act on.
"""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from apps.compliance.checks import CheckOutcome, register_custom_handler
from apps.compliance.engine import ResultStatus, evaluate
from apps.compliance.models import (
    AppliesTo,
    CheckType,
    ComplianceRule,
    EvaluationStatus,
    LegalStatus,
    Severity,
)
from apps.compliance.subjects import ComplianceSubject, from_text


def make_rule(**overrides) -> ComplianceRule:
    """An unsaved rule. The engine never needs one persisted."""
    data = {
        "rule_id": "test-rule",
        "description": "A test rule.",
        "check_type": CheckType.PROHIBITED_PHRASE,
        "rule_data": {"phrases": ["forbidden"]},
        "severity": Severity.ERROR,
        "applies_to": AppliesTo.ALL,
        "legal_status": LegalStatus.APPROVED,
        "is_active": True,
    }
    data.update(overrides)
    return ComplianceRule(**data)


def subject(text: str = "", **kwargs) -> ComplianceSubject:
    base = from_text(text)
    for key, value in kwargs.items():
        setattr(base, key, value)
    return base


class ProhibitedPhraseTests(SimpleTestCase):
    def _run(self, text: str, phrases: list[str], **rule_kwargs):
        rule = make_rule(rule_data={"phrases": phrases, **rule_kwargs})
        return evaluate(subject(text), [rule]).results[0]

    def test_clean_text_passes(self):
        result = self._run("A lovely home by the sea.", ["guaranteed return"])

        self.assertEqual(result.status, ResultStatus.PASS)

    def test_prohibited_phrase_fails(self):
        result = self._run("A guaranteed return on your money.", ["guaranteed return"])

        self.assertEqual(result.status, ResultStatus.FAIL)
        self.assertIn("guaranteed return", result.message)
        self.assertEqual(result.evidence, ["guaranteed return"])

    def test_matching_ignores_case(self):
        result = self._run("A GUARANTEED RETURN awaits.", ["guaranteed return"])

        self.assertEqual(result.status, ResultStatus.FAIL)

    def test_matching_tolerates_extra_whitespace(self):
        """Copy gets reflowed; a line break is not compliance."""
        result = self._run("A guaranteed\n  return awaits.", ["guaranteed return"])

        self.assertEqual(result.status, ResultStatus.FAIL)

    def test_whole_word_matching_avoids_false_positives(self):
        result = self._run("The unguaranteed returns.", ["guaranteed"], whole_word=True)

        self.assertEqual(result.status, ResultStatus.PASS)

    def test_substring_matching_can_be_opted_into(self):
        result = self._run("Unguaranteed.", ["guaranteed"], whole_word=False)

        self.assertEqual(result.status, ResultStatus.FAIL)

    def test_every_hit_is_reported(self):
        result = self._run(
            "Risk free and a guaranteed return.", ["risk free", "guaranteed return"]
        )

        self.assertEqual(len(result.evidence), 2)

    def test_smart_punctuation_does_not_hide_a_phrase(self):
        result = self._run("It’s a guaranteed return.", ["guaranteed return"])

        self.assertEqual(result.status, ResultStatus.FAIL)


class RequiredFieldTests(SimpleTestCase):
    def _run(self, fields: dict, field_name: str = "brokerage_name"):
        rule = make_rule(
            check_type=CheckType.REQUIRED_FIELD_PRESENT,
            rule_data={"field": field_name, "label": "Brokerage name"},
        )
        return evaluate(subject("some text", fields=fields), [rule]).results[0]

    def test_present_field_passes(self):
        result = self._run({"brokerage_name": "Acme Realty"})

        self.assertEqual(result.status, ResultStatus.PASS)

    def test_empty_field_fails(self):
        result = self._run({"brokerage_name": ""})

        self.assertEqual(result.status, ResultStatus.FAIL)
        self.assertIn("required", result.message.lower())

    def test_whitespace_only_field_fails(self):
        result = self._run({"brokerage_name": "   "})

        self.assertEqual(result.status, ResultStatus.FAIL)

    def test_none_fails(self):
        result = self._run({"brokerage_name": None})

        self.assertEqual(result.status, ResultStatus.FAIL)

    def test_a_field_the_subject_does_not_have_is_skipped_not_failed(self):
        """A rule/subject mismatch is not a compliance failure by the agent."""
        result = self._run({"agent_name": "Test"}, field_name="brokerage_name")

        self.assertEqual(result.status, ResultStatus.SKIPPED)

    def test_a_falsey_non_string_still_counts_as_present(self):
        result = self._run({"brokerage_name": 0})

        self.assertEqual(result.status, ResultStatus.PASS)


class DisclaimerTests(SimpleTestCase):
    DISCLAIMER = "All information is provided as a guide only."

    def _run(self, text: str, match: str = "normalised"):
        rule = make_rule(
            check_type=CheckType.DISCLAIMER_PRESENT,
            rule_data={"text": self.DISCLAIMER, "match": match},
        )
        return evaluate(subject(text), [rule]).results[0]

    def test_exact_disclaimer_passes(self):
        self.assertEqual(self._run(f"Nice home. {self.DISCLAIMER}").status, ResultStatus.PASS)

    def test_missing_disclaimer_fails(self):
        result = self._run("Nice home.")

        self.assertEqual(result.status, ResultStatus.FAIL)
        self.assertIn("missing", result.message.lower())

    def test_case_and_spacing_differences_still_pass(self):
        result = self._run("ALL INFORMATION IS   PROVIDED as a Guide only.")

        self.assertEqual(result.status, ResultStatus.PASS)

    def test_all_words_mode_tolerates_reflowed_text(self):
        """A disclaimer split across design elements is still present."""
        result = self._run(
            "All information | is provided | as a guide only.", match="all_words"
        )

        self.assertEqual(result.status, ResultStatus.PASS)

    def test_all_words_mode_still_catches_a_missing_disclaimer(self):
        result = self._run("Completely different text.", match="all_words")

        self.assertEqual(result.status, ResultStatus.FAIL)

    def test_exact_mode_is_strict(self):
        result = self._run("all information is provided as a guide only.", match="exact")

        self.assertEqual(result.status, ResultStatus.FAIL)


class RequiredPhraseTests(SimpleTestCase):
    def _run(self, text: str, phrases: list[str], mode: str = "any"):
        rule = make_rule(
            check_type=CheckType.REQUIRED_PHRASE,
            rule_data={"phrases": phrases, "mode": mode},
        )
        return evaluate(subject(text), [rule]).results[0]

    def test_any_mode_passes_with_one_match(self):
        result = self._run("Contact our licensed agent.", ["licensed agent", "licensee"])

        self.assertEqual(result.status, ResultStatus.PASS)

    def test_any_mode_fails_with_none(self):
        result = self._run("Contact us.", ["licensed agent", "licensee"])

        self.assertEqual(result.status, ResultStatus.FAIL)

    def test_all_mode_needs_every_phrase(self):
        result = self._run("Contact our licensed agent.", ["licensed agent", "licensee"], "all")

        self.assertEqual(result.status, ResultStatus.FAIL)
        self.assertEqual(result.evidence, ["licensee"])


class PatternTests(SimpleTestCase):
    PATTERN = r"\b\d+(?:\.\d+)?\s*%\s*(?:yield|return)\b"

    def _run(self, text: str, pattern: str = PATTERN):
        rule = make_rule(
            check_type=CheckType.PROHIBITED_PATTERN, rule_data={"pattern": pattern}
        )
        return evaluate(subject(text), [rule]).results[0]

    def test_matching_pattern_fails(self):
        result = self._run("Offering a 6% yield.")

        self.assertEqual(result.status, ResultStatus.FAIL)
        self.assertEqual(result.evidence, ["6% yield"])

    def test_non_matching_text_passes(self):
        self.assertEqual(self._run("A lovely home.").status, ResultStatus.PASS)

    def test_an_invalid_pattern_reports_a_rule_problem_not_a_failure(self):
        """A typo in a regex must not be blamed on the agent's content."""
        result = self._run("Anything at all.", pattern="([unclosed")

        self.assertEqual(result.status, ResultStatus.RULE_ERROR)
        self.assertFalse(result.blocks_export)


class LengthTests(SimpleTestCase):
    def _run(self, blocks: dict, rule_data: dict):
        rule = make_rule(check_type=CheckType.LENGTH_LIMIT, rule_data=rule_data)
        return evaluate(subject(text_blocks=blocks), [rule]).results[0]

    def test_within_limit_passes(self):
        result = self._run({"caption": "short"}, {"field": "caption", "max": 100})

        self.assertEqual(result.status, ResultStatus.PASS)

    def test_over_limit_fails_and_says_by_how_much(self):
        result = self._run({"caption": "x" * 150}, {"field": "caption", "max": 100})

        self.assertEqual(result.status, ResultStatus.FAIL)
        self.assertIn("150", result.message)
        self.assertIn("100", result.message)

    def test_minimum_length(self):
        result = self._run({"caption": "hi"}, {"field": "caption", "min": 10})

        self.assertEqual(result.status, ResultStatus.FAIL)

    def test_a_field_the_subject_lacks_is_skipped(self):
        result = self._run({"caption": "hi"}, {"field": "nonexistent", "max": 5})

        self.assertEqual(result.status, ResultStatus.SKIPPED)

    def test_without_a_field_it_checks_everything(self):
        result = self._run({"a": "x" * 60, "b": "y" * 60}, {"max": 100})

        self.assertEqual(result.status, ResultStatus.FAIL)


class CustomHandlerTests(SimpleTestCase):
    def test_a_registered_handler_runs(self):
        @register_custom_handler("test_always_fails")
        def _always_fails(rule, subj):
            return CheckOutcome(False, "Deliberate failure.", evidence=["x"])

        rule = make_rule(
            check_type=CheckType.CUSTOM, rule_data={"handler": "test_always_fails"}
        )
        result = evaluate(subject("anything"), [rule]).results[0]

        self.assertEqual(result.status, ResultStatus.FAIL)
        self.assertEqual(result.message, "Deliberate failure.")

    def test_an_unregistered_handler_is_reported_never_imported(self):
        """Importing a path from a database row would be RCE by configuration."""
        rule = make_rule(
            check_type=CheckType.CUSTOM,
            rule_data={"handler": "os.system"},
        )
        result = evaluate(subject("anything"), [rule]).results[0]

        self.assertEqual(result.status, ResultStatus.RULE_ERROR)
        self.assertIn("not registered", result.message)

    def test_a_handler_that_raises_is_contained(self):
        @register_custom_handler("test_raises")
        def _raises(rule, subj):
            raise ValueError("boom")

        rule = make_rule(check_type=CheckType.CUSTOM, rule_data={"handler": "test_raises"})
        result = evaluate(subject("anything"), [rule]).results[0]

        self.assertEqual(result.status, ResultStatus.RULE_ERROR)
        self.assertIn("could not be applied", result.message)


class ReportTests(SimpleTestCase):
    def test_an_unknown_check_type_does_not_stop_the_others(self):
        broken = make_rule(rule_id="broken", check_type="not_a_real_check")
        working = make_rule(rule_id="working", rule_data={"phrases": ["forbidden"]})

        report = evaluate(subject("this is forbidden"), [broken, working])

        self.assertEqual(len(report.results), 2)
        self.assertEqual(report.results[0].status, ResultStatus.RULE_ERROR)
        self.assertEqual(report.results[1].status, ResultStatus.FAIL)

    def test_error_severity_blocks_export(self):
        rule = make_rule(severity=Severity.ERROR, rule_data={"phrases": ["forbidden"]})

        report = evaluate(subject("forbidden"), [rule])

        self.assertTrue(report.blocks_export)
        self.assertEqual(report.status, EvaluationStatus.FAILED)

    def test_warning_severity_does_not_block(self):
        rule = make_rule(severity=Severity.WARNING, rule_data={"phrases": ["forbidden"]})

        report = evaluate(subject("forbidden"), [rule])

        self.assertFalse(report.blocks_export)
        self.assertEqual(report.status, EvaluationStatus.FLAGGED)
        self.assertEqual(len(report.warnings), 1)

    def test_a_rule_error_flags_but_never_blocks(self):
        """An unusable rule must not stop an agent working."""
        rule = make_rule(severity=Severity.ERROR, check_type="not_a_real_check")

        report = evaluate(subject("anything"), [rule])

        self.assertFalse(report.blocks_export)
        self.assertEqual(report.status, EvaluationStatus.FLAGGED)

    def test_a_clean_run_passes(self):
        rule = make_rule(rule_data={"phrases": ["forbidden"]})

        report = evaluate(subject("perfectly fine"), [rule])

        self.assertEqual(report.status, EvaluationStatus.PASSED)
        self.assertFalse(report.blocks_export)

    def test_placeholder_rules_are_marked_in_the_report(self):
        """So a UI can say these checks are provisional."""
        placeholder = make_rule(rule_id="p", legal_status=LegalStatus.PENDING_REVIEW)
        approved = make_rule(rule_id="a", legal_status=LegalStatus.APPROVED)

        report = evaluate(subject("fine"), [placeholder, approved])

        self.assertTrue(report.used_placeholder_rules)
        self.assertTrue(report.results[0].is_placeholder)
        self.assertFalse(report.results[1].is_placeholder)

    def test_every_result_carries_a_human_readable_message(self):
        rules = [
            make_rule(rule_id="a", rule_data={"phrases": ["forbidden"]}),
            make_rule(
                rule_id="b",
                check_type=CheckType.REQUIRED_FIELD_PRESENT,
                rule_data={"field": "brokerage_name", "label": "Brokerage name"},
            ),
        ]

        report = evaluate(subject("forbidden", fields={"brokerage_name": ""}), rules)

        for result in report.results:
            with self.subTest(rule=result.rule_id):
                self.assertTrue(result.message)
                self.assertNotIn("None", result.message)
                self.assertTrue(result.message[0].isupper() or result.message[0] in "“\"")

    def test_no_rules_is_a_pass_not_an_error(self):
        report = evaluate(subject("anything"), [])

        self.assertEqual(report.status, EvaluationStatus.PASSED)
        self.assertEqual(report.results, [])

    def test_the_report_serialises_for_storage_and_api(self):
        rule = make_rule(rule_data={"phrases": ["forbidden"]})

        data = evaluate(subject("forbidden"), [rule]).as_dict()

        self.assertEqual(data["status"], EvaluationStatus.FAILED)
        self.assertTrue(data["blocks_export"])
        self.assertEqual(data["error_count"], 1)
        self.assertEqual(data["results"][0]["rule_id"], "test-rule")


class RuleSelectionTests(TestCase):
    """Which rules apply — needs the database."""

    def setUp(self) -> None:
        from apps.accounts.models import Brokerage

        self.acme = Brokerage.objects.create(name="Acme Realty")
        self.rival = Brokerage.objects.create(name="Rival Realty")

    def _rule(self, rule_id: str, **kwargs) -> ComplianceRule:
        return ComplianceRule.objects.create(
            rule_id=rule_id,
            description="x",
            check_type=CheckType.PROHIBITED_PHRASE,
            rule_data={"phrases": ["forbidden"]},
            **kwargs,
        )

    def test_inactive_rules_are_not_applied(self):
        from apps.compliance.engine import rules_for

        self._rule("active-rule", is_active=True)
        self._rule("inactive-rule", is_active=False)

        ids = [rule.rule_id for rule in rules_for(from_text("x"))]

        self.assertEqual(ids, ["active-rule"])

    def test_rules_are_filtered_by_what_they_apply_to(self):
        from apps.compliance.engine import rules_for

        self._rule("all-content", applies_to=AppliesTo.ALL)
        self._rule("designs-only", applies_to=AppliesTo.DESIGN)
        self._rule("ai-only", applies_to=AppliesTo.AI_CONTENT)

        subj = from_text("x", kind=AppliesTo.DESIGN)
        ids = sorted(rule.rule_id for rule in rules_for(subj))

        self.assertEqual(ids, ["all-content", "designs-only"])

    def test_brokerage_scoped_rules_do_not_leak_between_brokerages(self):
        from apps.compliance.engine import rules_for

        self._rule("global-rule")
        self._rule("acme-only", brokerage=self.acme)
        self._rule("rival-only", brokerage=self.rival)

        subj = from_text("x")
        subj.brokerage_id = self.acme.pk
        ids = sorted(rule.rule_id for rule in rules_for(subj))

        self.assertEqual(ids, ["acme-only", "global-rule"])

    def test_rules_are_reported_in_their_configured_order(self):
        from apps.compliance.engine import rules_for

        self._rule("third", order=30)
        self._rule("first", order=10)
        self._rule("second", order=20)

        ids = [rule.rule_id for rule in rules_for(from_text("x"))]

        self.assertEqual(ids, ["first", "second", "third"])


class RuleDataValidationTests(TestCase):
    """A rule that saves and then never fires is worse than an error."""

    def _clean(self, check_type: str, rule_data: dict):
        from django.core.exceptions import ValidationError

        rule = ComplianceRule(
            rule_id="x", description="x", check_type=check_type, rule_data=rule_data
        )
        try:
            rule.clean()
            return None
        except ValidationError as exc:
            return exc.message_dict["rule_data"]

    def test_valid_data_passes(self):
        self.assertIsNone(
            self._clean(CheckType.PROHIBITED_PHRASE, {"phrases": ["a"]})
        )

    def test_missing_phrases_is_rejected(self):
        errors = self._clean(CheckType.PROHIBITED_PHRASE, {})

        self.assertTrue(errors)
        self.assertIn("phrases", errors[0])

    def test_empty_phrase_list_is_rejected(self):
        self.assertTrue(self._clean(CheckType.PROHIBITED_PHRASE, {"phrases": []}))

    def test_invalid_regex_is_rejected_at_save_time(self):
        errors = self._clean(CheckType.PROHIBITED_PATTERN, {"pattern": "([unclosed"})

        self.assertTrue(errors)
        self.assertIn("not a valid regular expression", errors[0])

    def test_missing_field_name_is_rejected(self):
        self.assertTrue(self._clean(CheckType.REQUIRED_FIELD_PRESENT, {}))

    def test_unknown_custom_handler_is_rejected_with_the_available_list(self):
        errors = self._clean(CheckType.CUSTOM, {"handler": "does_not_exist"})

        self.assertTrue(errors)
        self.assertIn("Available", errors[0])

    def test_bad_disclaimer_match_mode_is_rejected(self):
        self.assertTrue(
            self._clean(CheckType.DISCLAIMER_PRESENT, {"text": "x", "match": "fuzzy"})
        )

    def test_length_limit_needs_a_bound(self):
        self.assertTrue(self._clean(CheckType.LENGTH_LIMIT, {"field": "caption"}))
