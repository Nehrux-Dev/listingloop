"""Part B: the async API — job dispatch, polling, review, scoping, cost.

The most important test in this file is
``test_opening_a_listing_does_not_trigger_generation``: an expensive external
call that fires on a read is a bill that grows with page views.
"""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.test import override_settings

from apps.ai_content.models import (
    GeneratedContent,
    JobStatus,
    ReviewStatus,
    ValidationStatus,
)
from apps.ai_content.tests.base import (
    GOOD_PAYLOAD,
    POISONED_PAYLOAD,
    AIContentTestCase,
    fake_completion,
)


class GenerateEndpointTests(AIContentTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authenticate_as(self.agent)

    @mock.patch("apps.ai_content.views.generate_content.delay")
    def test_generate_returns_immediately_with_a_job(self, delay):
        response = self.client.post(
            self.generate_url, {"listing": self.listing.pk}, format="json"
        )

        self.assertEqual(response.status_code, 202)
        # A list, because one request can ask for several languages. English
        # only, here.
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["job_status"], JobStatus.QUEUED)
        self.assertEqual(response.data[0]["caption"], "")

        generation = GeneratedContent.objects.get()
        # Queued rather than executed inline: the request does not wait on
        # OpenAI.
        delay.assert_called_once_with(generation.pk)

    @mock.patch("apps.ai_content.views.generate_content.delay")
    def test_generating_from_an_unverified_listing_is_refused(self, delay):
        unverified = self.make_unverified_listing()

        response = self.client.post(
            self.generate_url, {"listing": unverified.pk}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("verified", str(response.data["listing"][0]).lower())
        delay.assert_not_called()
        self.assertFalse(GeneratedContent.objects.exists())

    @mock.patch("apps.ai_content.views.generate_content.delay")
    def test_generating_from_another_agents_listing_is_refused(self, delay):
        other_agent, other_profile = self.make_agent_in(self.acme, "b@example.com")
        theirs = self.make_listing(other_profile, address="Theirs")
        theirs.mark_verified(other_agent)

        response = self.client.post(self.generate_url, {"listing": theirs.pk}, format="json")

        self.assertEqual(response.status_code, 400)
        delay.assert_not_called()

    def test_generate_requires_authentication(self):
        self.client.credentials()

        response = self.client.post(
            self.generate_url, {"listing": self.listing.pk}, format="json"
        )

        self.assertEqual(response.status_code, 401)

    @mock.patch("apps.ai_content.views.generate_content.delay")
    def test_regenerate_creates_a_new_record(self, delay):
        self.client.post(self.generate_url, {"listing": self.listing.pk}, format="json")
        self.client.post(self.generate_url, {"listing": self.listing.pk}, format="json")

        self.assertEqual(GeneratedContent.objects.count(), 2)
        self.assertEqual(delay.call_count, 2)


class NoAccidentalGenerationTests(AIContentTestCase):
    """Generation must only ever happen on an explicit action."""

    def setUp(self) -> None:
        super().setUp()
        self.authenticate_as(self.agent)

    @mock.patch("apps.ai_content.views.generate_content.delay")
    @mock.patch("apps.ai_content.services.complete_json")
    def test_opening_a_listing_does_not_trigger_generation(self, complete, delay):
        """A bill that grows with page views is the failure being prevented."""
        for _ in range(3):
            self.client.get(self.listing_detail_url(self.listing))
        self.client.get(self.listings_url)

        complete.assert_not_called()
        delay.assert_not_called()
        self.assertFalse(GeneratedContent.objects.exists())

    @mock.patch("apps.ai_content.views.generate_content.delay")
    @mock.patch("apps.ai_content.services.complete_json")
    def test_reading_generated_content_does_not_regenerate_it(self, complete, delay):
        generation = GeneratedContent.objects.create(
            listing=self.listing, job_status=JobStatus.READY, caption="Existing copy."
        )

        self.client.get(self.content_url)
        self.client.get(self.content_detail_url(generation))
        for _ in range(5):
            self.client.get(self.content_action_url(generation, "status"))

        complete.assert_not_called()
        delay.assert_not_called()
        self.assertEqual(GeneratedContent.objects.count(), 1)

    @mock.patch("apps.ai_content.views.generate_content.delay")
    @mock.patch("apps.ai_content.services.complete_json")
    def test_editing_or_verifying_a_listing_does_not_trigger_generation(self, complete, delay):
        self.client.patch(
            self.listing_detail_url(self.listing), {"bedrooms": 5}, format="json"
        )
        self.client.post(
            self.listing_verify_url(self.listing), {"confirmed": True}, format="json"
        )

        complete.assert_not_called()
        delay.assert_not_called()
        self.assertFalse(GeneratedContent.objects.exists())


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class TaskExecutionTests(AIContentTestCase):
    """The Celery layer, run inline."""

    def setUp(self) -> None:
        super().setUp()
        self.authenticate_as(self.agent)

    @mock.patch("apps.ai_content.services.complete_json")
    def test_the_task_completes_the_job(self, complete):
        complete.side_effect = fake_completion(GOOD_PAYLOAD)

        response = self.client.post(
            self.generate_url, {"listing": self.listing.pk}, format="json"
        )

        self.assertEqual(response.status_code, 202)
        generation = GeneratedContent.objects.get()
        self.assertEqual(generation.job_status, JobStatus.READY)
        self.assertEqual(generation.validation_status, ValidationStatus.PASSED)
        self.assertIn("Manly", generation.caption)

    @mock.patch("apps.ai_content.services.complete_json")
    def test_a_poisoned_response_is_rejected_through_the_task_too(self, complete):
        complete.side_effect = fake_completion(POISONED_PAYLOAD)

        self.client.post(self.generate_url, {"listing": self.listing.pk}, format="json")

        generation = GeneratedContent.objects.get()
        self.assertEqual(generation.validation_status, ValidationStatus.REJECTED)
        self.assertEqual(generation.caption, "")

    @mock.patch("apps.ai_content.services.complete_json")
    def test_a_finished_job_is_not_re_run_on_redelivery(self, complete):
        """acks_late means a task can arrive twice; it must not bill twice."""
        from apps.ai_content.tasks import generate_content

        complete.side_effect = fake_completion(GOOD_PAYLOAD)
        self.client.post(self.generate_url, {"listing": self.listing.pk}, format="json")
        generation = GeneratedContent.objects.get()
        self.assertEqual(complete.call_count, 1)

        generate_content(generation.pk)

        self.assertEqual(complete.call_count, 1)

    def test_a_missing_record_does_not_crash_the_worker(self):
        from apps.ai_content.tasks import generate_content

        self.assertEqual(generate_content(999999)["status"], "missing")


class PollingAndReviewTests(AIContentTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authenticate_as(self.agent)
        self.generation = GeneratedContent.objects.create(
            listing=self.listing,
            job_status=JobStatus.READY,
            validation_status=ValidationStatus.PASSED,
            caption="A four-bedroom house in Manly.",
            hashtags=["#Manly"],
            total_tokens=516,
            estimated_cost_usd=Decimal("0.000121"),
        )

    def test_status_endpoint_is_small(self):
        response = self.client.get(self.content_action_url(self.generation, "status"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {"id", "job_status", "validation_status", "review_status", "is_usable", "error_message"},
        )

    def test_detail_exposes_the_facts_the_copy_was_written_from(self):
        response = self.client.get(self.content_detail_url(self.generation))

        self.assertEqual(response.status_code, 200)
        self.assertIn("prompt_facts", response.data)
        self.assertIn("validation_issues", response.data)
        self.assertEqual(response.data["review_status"], ReviewStatus.DRAFT)

    def test_no_secret_or_internal_config_is_exposed_in_the_payload(self):
        response = self.client.get(self.content_detail_url(self.generation))
        body = str(response.data).lower()

        for forbidden in ("api_key", "openai_api_key", "sk-", "authorization"):
            self.assertNotIn(forbidden, body)

    @override_settings(OPENAI_API_KEY="")
    def test_a_configuration_failure_does_not_name_internal_variables(self):
        """Operators read logs; API clients should not read our env schema."""
        from apps.ai_content.services import generate_for_listing

        generation = generate_for_listing(self.listing, self.agent)

        self.assertEqual(generation.job_status, JobStatus.FAILED)
        self.assertNotIn("OPENAI_API_KEY", generation.error_message)
        self.assertNotIn(".env", generation.error_message)
        self.assertIn("not configured", generation.error_message)

    def test_agent_approves_a_draft(self):
        response = self.client.post(
            self.content_action_url(self.generation, "review"),
            {"decision": "approved"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.generation.refresh_from_db()
        self.assertEqual(self.generation.review_status, ReviewStatus.APPROVED)
        self.assertEqual(self.generation.reviewed_by, self.agent)
        self.assertIsNotNone(self.generation.reviewed_at)

    def test_rejected_content_cannot_be_approved(self):
        self.generation.validation_status = ValidationStatus.REJECTED
        self.generation.caption = ""
        self.generation.save()

        response = self.client.post(
            self.content_action_url(self.generation, "review"),
            {"decision": "approved"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.generation.refresh_from_db()
        self.assertEqual(self.generation.review_status, ReviewStatus.DRAFT)

    def test_agent_can_reject_a_draft(self):
        response = self.client.post(
            self.content_action_url(self.generation, "review"),
            {"decision": "rejected"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.generation.refresh_from_db()
        self.assertEqual(self.generation.review_status, ReviewStatus.REJECTED)


class ScopingAndUsageTests(AIContentTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.other_agent, self.other_profile = self.make_agent_in(self.acme, "b@example.com")
        other_listing = self.make_listing(self.other_profile, address="Theirs")
        other_listing.mark_verified(self.other_agent)

        self.mine = GeneratedContent.objects.create(
            listing=self.listing, job_status=JobStatus.READY, caption="Mine",
            total_tokens=500, estimated_cost_usd=Decimal("0.000100"),
        )
        self.theirs = GeneratedContent.objects.create(
            listing=other_listing, job_status=JobStatus.READY, caption="Theirs",
            total_tokens=700, estimated_cost_usd=Decimal("0.000200"),
        )

    def test_agent_sees_only_their_own_content(self):
        self.authenticate_as(self.agent)

        response = self.client.get(self.content_url)

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["caption"], "Mine")

    def test_agent_cannot_open_another_agents_content(self):
        self.authenticate_as(self.agent)

        self.assertEqual(
            self.client.get(self.content_detail_url(self.theirs)).status_code, 404
        )

    def test_agent_cannot_review_another_agents_content(self):
        self.authenticate_as(self.agent)

        response = self.client.post(
            self.content_action_url(self.theirs, "review"),
            {"decision": "approved"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_usage_totals_are_scoped_to_the_caller(self):
        self.authenticate_as(self.agent)

        response = self.client.get(self.usage_url)

        self.assertEqual(response.data["generations"], 1)
        self.assertEqual(response.data["total_tokens"], 500)
        self.assertEqual(response.data["estimated_cost_usd"], "0.000100")

    def test_brokerage_admin_sees_the_brokerages_usage(self):
        broker_admin = self.make_brokerage_admin("admin@example.com")
        self.acme.admins.add(broker_admin)
        self.authenticate_as(broker_admin)

        response = self.client.get(self.usage_url)

        self.assertEqual(response.data["generations"], 2)
        self.assertEqual(response.data["total_tokens"], 1200)

    def test_unauthenticated_access_is_rejected(self):
        self.assertEqual(self.client.get(self.content_url).status_code, 401)
