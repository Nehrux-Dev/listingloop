"""Compliance wired into the review flow.

Two moments matter: after generation, so flags are waiting when the agent opens
the panel; and at export, which is the last point before material is published.
"""

from __future__ import annotations

from django.test import override_settings
from django.urls import reverse

from apps.ai_content.services import generate_for_listing
from apps.ai_content.tests.base import GOOD_PAYLOAD, AIContentTestCase, fake_completion
from apps.compliance.models import (
    AppliesTo,
    CheckType,
    ComplianceEvaluation,
    ComplianceRule,
    EvaluationStatus,
    LegalStatus,
    Severity,
)
from apps.templates.tests.base import TemplateAPITestCase


def prohibited_rule(phrase: str, **overrides) -> ComplianceRule:
    data = {
        "rule_id": f"test-no-{phrase.replace(' ', '-')}",
        "description": f"Content must not say “{phrase}”.",
        "check_type": CheckType.PROHIBITED_PHRASE,
        "rule_data": {"phrases": [phrase]},
        "severity": Severity.ERROR,
        "applies_to": AppliesTo.ALL,
        "legal_status": LegalStatus.APPROVED,
    }
    data.update(overrides)
    return ComplianceRule.objects.create(**data)


class GenerationWiringTests(AIContentTestCase):
    def test_compliance_runs_automatically_after_generation(self):
        prohibited_rule("ocean views")

        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )

        evaluations = ComplianceEvaluation.objects.filter(generated_content=generation)
        # One per variant, so a flag points at the format that caused it.
        self.assertEqual(evaluations.count(), 6)
        self.assertTrue(
            evaluations.filter(status=EvaluationStatus.FAILED).exists(),
            "the rule should have caught the variants mentioning ocean views",
        )

    def test_each_evaluation_is_linked_to_its_variant(self):
        prohibited_rule("ocean views")

        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )

        for variant in generation.variants.all():
            with self.subTest(kind=variant.kind):
                self.assertTrue(
                    ComplianceEvaluation.objects.filter(content_variant=variant).exists()
                )

    def test_clean_content_evaluates_as_passed(self):
        prohibited_rule("something not present anywhere")

        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )

        self.assertFalse(
            ComplianceEvaluation.objects.filter(
                generated_content=generation, status=EvaluationStatus.FAILED
            ).exists()
        )

    def test_a_broken_rule_does_not_fail_the_generation(self):
        """Compliance is a review aid layered on a finished, paid-for job."""
        ComplianceRule.objects.create(
            rule_id="broken",
            description="x",
            check_type="not_a_real_check_type",
            rule_data={},
        )

        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )

        self.assertEqual(generation.job_status, "ready")
        self.assertEqual(generation.variants.count(), 6)

    def test_evaluations_are_visible_through_the_api(self):
        prohibited_rule("ocean views")
        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )
        self.authenticate_as(self.agent)

        response = self.client.get(
            reverse("compliance:evaluation-list"), {"generated_content": generation.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 6)

    def test_another_agent_cannot_see_the_evaluations(self):
        prohibited_rule("ocean views")
        generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )
        other_agent, _ = self.make_agent_in(self.acme, "b@example.com")
        self.authenticate_as(other_agent)

        response = self.client.get(reverse("compliance:evaluation-list"))

        self.assertEqual(response.data["count"], 0)


class ExportGateTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.acme.required_disclaimer = "Figures are indicative only."
        self.acme.save()
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        # The template marks its hero photo required, and the export readiness
        # check refuses to render an element that would come out blank — so a
        # listing used for export tests needs a photo, exactly as a real one
        # would.
        from apps.accounts.tests.base import make_image_file
        from apps.listings.models import ListingPhoto

        ListingPhoto.objects.create(
            listing=self.listing, image=make_image_file("hero.png"), order=0
        )
        self.design = self.make_design(self.template, self.profile, self.listing)
        self.authenticate_as(self.agent)

    def _export(self):
        return self.client.post(
            self.design_action_url(self.design, "export"),
            {"dimensions": ["facebook"]},
            format="json",
        )

    def test_a_blocking_failure_stops_the_export(self):
        # The design's badge element renders "Just listed"; forbid it.
        prohibited_rule("just listed", severity=Severity.ERROR)

        response = self._export()

        self.assertEqual(response.status_code, 409)
        self.assertIn("compliance", response.data)
        self.assertTrue(response.data["compliance"]["blocks_export"])
        from apps.templates.models import DesignExport

        self.assertEqual(DesignExport.objects.count(), 0)

    def test_the_response_says_which_rule_blocked_it(self):
        rule = prohibited_rule("just listed", severity=Severity.ERROR)

        response = self._export()

        failing = [
            result
            for result in response.data["compliance"]["results"]
            if result["status"] == "fail"
        ]
        self.assertEqual(failing[0]["rule_id"], rule.rule_id)
        self.assertIn("just listed", failing[0]["message"])

    def test_a_warning_does_not_stop_the_export_but_is_returned(self):
        from unittest import mock

        from apps.templates.tests.test_rendering import FakeResponse

        prohibited_rule("just listed", severity=Severity.WARNING)

        with mock.patch("apps.templates.rendering.requests.post") as post:
            post.return_value = FakeResponse()
            response = self._export()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["exports"]), 1)
        self.assertEqual(response.data["compliance"]["warning_count"], 1)
        self.assertFalse(response.data["compliance"]["blocks_export"])

    def test_a_clean_design_exports_normally(self):
        from unittest import mock

        from apps.templates.tests.test_rendering import FakeResponse

        prohibited_rule("a phrase that is not in this design")

        with mock.patch("apps.templates.rendering.requests.post") as post:
            post.return_value = FakeResponse()
            response = self._export()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["compliance"]["status"], EvaluationStatus.PASSED)

    @override_settings(COMPLIANCE_BLOCK_EXPORTS=False)
    def test_blocking_can_be_turned_off_while_rules_are_provisional(self):
        """The seeded set is a placeholder; an operator may want advice only."""
        from unittest import mock

        from apps.templates.tests.test_rendering import FakeResponse

        prohibited_rule("just listed", severity=Severity.ERROR)

        with mock.patch("apps.templates.rendering.requests.post") as post:
            post.return_value = FakeResponse()
            response = self._export()

        self.assertEqual(response.status_code, 201)
        # Still reported — advisory, not silenced.
        self.assertTrue(response.data["compliance"]["blocks_export"])

    def test_the_export_attempt_is_recorded_even_when_blocked(self):
        prohibited_rule("just listed", severity=Severity.ERROR)

        self._export()

        evaluation = ComplianceEvaluation.objects.filter(design=self.design).first()
        self.assertIsNotNone(evaluation)
        self.assertEqual(evaluation.status, EvaluationStatus.FAILED)

    def test_the_editor_can_check_compliance_without_exporting(self):
        prohibited_rule("just listed", severity=Severity.ERROR)

        response = self.client.get(self.design_action_url(self.design, "compliance"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["blocks_export"])
        # A read must not write to the audit trail.
        self.assertEqual(ComplianceEvaluation.objects.count(), 0)

    def test_compliance_sees_locked_elements_the_agent_never_touched(self):
        """A disclaimer the agent cannot edit still has to be checked."""
        ComplianceRule.objects.create(
            rule_id="test-disclaimer",
            description="The disclaimer must appear.",
            check_type=CheckType.DISCLAIMER_PRESENT,
            rule_data={"text": "Figures are indicative only.", "match": "all_words"},
            severity=Severity.ERROR,
            applies_to=AppliesTo.DESIGN,
            legal_status=LegalStatus.APPROVED,
        )

        response = self.client.get(self.design_action_url(self.design, "compliance"))

        self.assertEqual(response.data["status"], EvaluationStatus.PASSED)


class ApiTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.authenticate_as(self.agent)

    def test_ad_hoc_text_can_be_checked(self):
        prohibited_rule("guaranteed return")

        response = self.client.post(
            reverse("compliance:evaluate"),
            {"text": "A guaranteed return on your money."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["blocks_export"])

    def test_exactly_one_target_is_required(self):
        response = self.client.post(
            reverse("compliance:evaluate"), {"text": "x", "design": 1}, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_another_agents_design_cannot_be_checked(self):
        other_agent, other_profile = self.make_agent_in(self.acme, "b@example.com")
        template = self.make_template()
        design = self.make_design(template, other_profile)

        response = self.client.post(
            reverse("compliance:evaluate"), {"design": design.pk}, format="json"
        )

        self.assertEqual(response.status_code, 404)

    def test_rules_are_readable_but_not_writable(self):
        prohibited_rule("guaranteed return")

        listed = self.client.get(reverse("compliance:rule-list"))
        created = self.client.post(
            reverse("compliance:rule-list"),
            {"rule_id": "mine", "description": "x", "check_type": "prohibited_phrase"},
            format="json",
        )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 1)
        # Agents are checked against the rules, not in charge of them.
        self.assertEqual(created.status_code, 405)

    def test_the_summary_reports_how_much_is_still_provisional(self):
        prohibited_rule("a", legal_status=LegalStatus.PENDING_REVIEW)
        prohibited_rule("b", legal_status=LegalStatus.APPROVED)

        response = self.client.get(reverse("compliance:rule-summary"))

        self.assertEqual(response.data["active"], 2)
        self.assertEqual(response.data["pending_legal_review"], 1)
        self.assertEqual(response.data["approved"], 1)

    def test_unauthenticated_access_is_rejected(self):
        self.client.credentials()

        self.assertEqual(self.client.get(reverse("compliance:rule-list")).status_code, 401)


class SeedCommandTests(TemplateAPITestCase):
    """The seed is placeholder data — tested for its *labelling*, not wording."""

    def test_every_seeded_rule_is_marked_pending_legal_review(self):
        from django.core.management import call_command
        from io import StringIO

        call_command("seed_compliance_rules", stdout=StringIO())

        self.assertTrue(ComplianceRule.objects.exists())
        for rule in ComplianceRule.objects.all():
            with self.subTest(rule=rule.rule_id):
                self.assertEqual(rule.legal_status, LegalStatus.PENDING_REVIEW)
                self.assertIn("PENDING LEGAL REVIEW", rule.admin_notes)
                self.assertTrue(rule.rule_id.startswith("placeholder-"))

    def test_seeded_rules_are_valid(self):
        """A seeded rule that would not save through the admin is a bug."""
        from django.core.management import call_command
        from io import StringIO

        call_command("seed_compliance_rules", stdout=StringIO())

        for rule in ComplianceRule.objects.all():
            with self.subTest(rule=rule.rule_id):
                rule.clean()  # raises if rule_data is malformed

    def test_reseeding_does_not_revert_an_approved_rule(self):
        from django.core.management import call_command
        from io import StringIO

        call_command("seed_compliance_rules", stdout=StringIO())
        rule = ComplianceRule.objects.first()
        rule.legal_status = LegalStatus.APPROVED
        rule.description = "Wording signed off by legal."
        rule.save()

        call_command("seed_compliance_rules", stdout=StringIO())

        rule.refresh_from_db()
        self.assertEqual(rule.legal_status, LegalStatus.APPROVED)
        self.assertEqual(rule.description, "Wording signed off by legal.")
