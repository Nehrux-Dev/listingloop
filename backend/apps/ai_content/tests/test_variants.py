"""Multi-variant generation: one call, six formats, each checked and reviewed.

The two properties that matter here:

  1. ONE API call produces all six. Six calls would cost roughly six times as
     much, because the facts block is most of the prompt and would be re-sent
     each time.
  2. The SAME validation runs over every variant. A rule enforced on the
     Instagram caption and forgotten on the property description would be worse
     than no rule, because the property description is the longest format and
     has the most room to invent.
"""

from __future__ import annotations

from apps.ai_content.models import (
    VARIANT_ORDER,
    ContentVariant,
    GeneratedContent,
    JobStatus,
    ReviewStatus,
    ValidationStatus,
    VariantKind,
)
from apps.ai_content.services import generate_for_listing
from apps.ai_content.tests.base import (
    GOOD_PAYLOAD,
    POISONED_PAYLOAD,
    AIContentTestCase,
    fake_completion,
)


class MultiVariantGenerationTests(AIContentTestCase):
    def test_one_call_produces_every_variant(self):
        calls = []

        def counting(messages, schema, **kwargs):
            calls.append(messages)
            return fake_completion(GOOD_PAYLOAD)(messages, schema)

        generation = generate_for_listing(self.listing, self.agent, completion_fn=counting)

        self.assertEqual(len(calls), 1, "the whole pack must come from one request")
        self.assertEqual(generation.variants.count(), 6)
        self.assertEqual(
            [variant.kind for variant in generation.variants.all()],
            list(VARIANT_ORDER),
        )

    def test_the_schema_asks_for_every_variant(self):
        """If the schema drifts from the model, a format silently disappears."""
        from apps.ai_content.prompts import RESPONSE_SCHEMA

        for kind in VARIANT_ORDER:
            self.assertIn(kind, RESPONSE_SCHEMA["properties"])
            self.assertIn(kind, RESPONSE_SCHEMA["required"])

    def test_each_variant_holds_its_own_copy(self):
        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )
        by_kind = {variant.kind: variant for variant in generation.variants.all()}

        self.assertIn("2,400 sq ft", by_kind[VariantKind.INSTAGRAM_CAPTION].text)
        self.assertIn("Thought of you", by_kind[VariantKind.SHARING_MESSAGE].text)
        self.assertEqual(by_kind[VariantKind.HASHTAGS].items[0], "#Manly")
        # The formats are not copies of one another.
        self.assertNotEqual(
            by_kind[VariantKind.INSTAGRAM_CAPTION].text,
            by_kind[VariantKind.PROPERTY_DESCRIPTION].text,
        )

    def test_all_variants_start_as_drafts(self):
        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )

        self.assertTrue(
            all(v.review_status == ReviewStatus.DRAFT for v in generation.variants.all())
        )

    def test_a_clean_pack_passes_every_variant(self):
        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )

        for variant in generation.variants.all():
            with self.subTest(kind=variant.kind):
                self.assertEqual(
                    variant.validation_status,
                    ValidationStatus.PASSED,
                    variant.validation_issues,
                )
                self.assertTrue(variant.is_usable)

        self.assertEqual(generation.usable_variant_count, 6)

    def test_cost_is_recorded_once_for_the_whole_pack(self):
        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )

        self.assertEqual(generation.total_tokens, 516)
        self.assertEqual(generation.variants.count(), 6)

    def test_regenerating_replaces_variants_rather_than_appending(self):
        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )
        from apps.ai_content.services import run_generation

        run_generation(generation, completion_fn=fake_completion(GOOD_PAYLOAD))

        self.assertEqual(generation.variants.count(), 6)

    def test_the_parent_mirrors_the_instagram_variant(self):
        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )

        instagram = generation.variants.get(kind=VariantKind.INSTAGRAM_CAPTION)
        self.assertEqual(generation.caption, instagram.text)
        self.assertEqual(generation.hashtags, GOOD_PAYLOAD["hashtags"])


class ValidationAcrossVariantsTests(AIContentTestCase):
    """Each format is poisoned differently; each rule must fire on its format."""

    def setUp(self) -> None:
        super().setUp()
        self.generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(POISONED_PAYLOAD)
        )
        self.by_kind = {v.kind: v for v in self.generation.variants.all()}

    def _codes(self, kind) -> set[str]:
        return {issue["code"] for issue in self.by_kind[kind].validation_issues}

    def test_invented_feature_and_number_caught_in_the_instagram_caption(self):
        codes = self._codes(VariantKind.INSTAGRAM_CAPTION)

        self.assertIn("unverified_feature", codes)   # pool, wine cellar
        self.assertIn("unverified_number", codes)    # 400 m, wrong price
        self.assertEqual(
            self.by_kind[VariantKind.INSTAGRAM_CAPTION].validation_status,
            ValidationStatus.REJECTED,
        )

    def test_invented_place_caught_in_the_facebook_caption(self):
        self.assertIn("possible_unverified_place", self._codes(VariantKind.FACEBOOK_CAPTION))

    def test_investment_claim_caught_in_the_linkedin_caption(self):
        codes = self._codes(VariantKind.LINKEDIN_CAPTION)

        self.assertIn("investment_claim", codes)
        self.assertEqual(
            self.by_kind[VariantKind.LINKEDIN_CAPTION].validation_status,
            ValidationStatus.REJECTED,
        )

    def test_legal_claim_caught_in_the_sharing_message(self):
        codes = self._codes(VariantKind.SHARING_MESSAGE)

        self.assertIn("legal_claim", codes)
        self.assertEqual(
            self.by_kind[VariantKind.SHARING_MESSAGE].validation_status,
            ValidationStatus.REJECTED,
        )

    def test_superlative_flags_the_property_description_without_rejecting_it(self):
        variant = self.by_kind[VariantKind.PROPERTY_DESCRIPTION]

        self.assertIn("unverifiable_superlative", self._codes(VariantKind.PROPERTY_DESCRIPTION))
        self.assertEqual(variant.validation_status, ValidationStatus.FLAGGED)
        # A warning does not block use.
        self.assertTrue(variant.is_usable)
        self.assertTrue(variant.text)

    def test_hashtags_are_validated_too(self):
        variant = self.by_kind[VariantKind.HASHTAGS]
        codes = self._codes(VariantKind.HASHTAGS)

        self.assertEqual(variant.validation_status, ValidationStatus.REJECTED)
        self.assertIn("unverified_feature", codes)   # #pool
        self.assertIn("high_risk_hashtag", codes)    # #7percentyield
        self.assertEqual(variant.items, [])
        self.assertEqual(variant.rejected_items, POISONED_PAYLOAD["hashtags"])

    def test_a_claim_glued_into_one_hashtag_is_still_caught(self):
        """"#7percentyield" has no word boundary before "yield", so the
        sentence-level patterns miss it. Hashtags need their own pass."""
        issues = self.by_kind[VariantKind.HASHTAGS].validation_issues
        evidence = {issue["evidence"] for issue in issues}

        self.assertIn("#7percentyield", evidence)

    def test_rejected_variants_keep_their_words_out_of_the_usable_field(self):
        rejected = [
            v for v in self.generation.variants.all()
            if v.validation_status == ValidationStatus.REJECTED
        ]

        self.assertTrue(rejected)
        for variant in rejected:
            with self.subTest(kind=variant.kind):
                self.assertEqual(variant.text, "")
                self.assertTrue(variant.rejected_text or variant.rejected_items)
                self.assertFalse(variant.is_usable)

    def test_one_bad_variant_does_not_spoil_a_good_one(self):
        """The reason variants are reviewed separately."""
        self.assertFalse(self.by_kind[VariantKind.LINKEDIN_CAPTION].is_usable)
        self.assertTrue(self.by_kind[VariantKind.PROPERTY_DESCRIPTION].is_usable)

    def test_the_generation_reports_the_worst_variant(self):
        """Four variants are rejected; the two only *flagged* survive."""
        self.assertEqual(self.generation.validation_status, ValidationStatus.REJECTED)
        self.assertEqual(self.generation.usable_variant_count, 2)

    def test_generation_issues_name_the_variant_at_fault(self):
        variants_in_issues = {
            issue.get("variant") for issue in self.generation.validation_issues
        }

        self.assertIn(VariantKind.LINKEDIN_CAPTION, variants_in_issues)
        self.assertIn(VariantKind.HASHTAGS, variants_in_issues)

    def test_the_parent_caption_is_empty_when_instagram_was_rejected(self):
        self.assertEqual(self.generation.caption, "")
        self.assertEqual(self.generation.hashtags, [])


class VariantApiTests(AIContentTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(POISONED_PAYLOAD)
        )
        self.by_kind = {v.kind: v for v in self.generation.variants.all()}
        self.authenticate_as(self.agent)

    def test_variants_are_returned_with_the_generation(self):
        response = self.client.get(self.content_detail_url(self.generation))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["variants"]), 6)
        self.assertEqual(response.data["usable_variant_count"], 2)

        kinds = {variant["kind"] for variant in response.data["variants"]}
        self.assertEqual(kinds, set(VARIANT_ORDER))

    def test_variants_can_be_listed_for_a_generation(self):
        response = self.client.get(self.content_url.replace("ai-content/", "ai-content-variants/"),
                                   {"generation": self.generation.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 6)

    def test_a_usable_variant_can_be_approved_on_its_own(self):
        variant = self.by_kind[VariantKind.PROPERTY_DESCRIPTION]

        response = self.client.post(
            self.variant_action_url(variant, "review"), {"decision": "approved"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        variant.refresh_from_db()
        self.assertEqual(variant.review_status, ReviewStatus.APPROVED)
        self.assertEqual(variant.reviewed_by, self.agent)

        # The others are untouched.
        other = self.by_kind[VariantKind.LINKEDIN_CAPTION]
        other.refresh_from_db()
        self.assertEqual(other.review_status, ReviewStatus.DRAFT)

    def test_a_rejected_variant_cannot_be_approved(self):
        variant = self.by_kind[VariantKind.LINKEDIN_CAPTION]

        response = self.client.post(
            self.variant_action_url(variant, "review"), {"decision": "approved"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("fact check", response.data["detail"])
        variant.refresh_from_db()
        self.assertEqual(variant.review_status, ReviewStatus.DRAFT)

    def test_a_rejected_variant_can_be_discarded(self):
        variant = self.by_kind[VariantKind.LINKEDIN_CAPTION]

        response = self.client.post(
            self.variant_action_url(variant, "review"), {"decision": "rejected"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        variant.refresh_from_db()
        self.assertEqual(variant.review_status, ReviewStatus.REJECTED)

    def test_review_all_skips_what_it_cannot_approve(self):
        response = self.client.post(
            self.content_action_url(self.generation, "review-all"),
            {"decision": "approved"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["applied"], 2)
        self.assertEqual(response.data["skipped"], 4)

    # -- editing ------------------------------------------------------------

    def test_an_agent_can_edit_a_variant(self):
        variant = self.by_kind[VariantKind.LINKEDIN_CAPTION]

        response = self.client.post(
            self.variant_action_url(variant, "edit"),
            {"text": "A four-bedroom house in Manly with ocean views."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        variant.refresh_from_db()
        self.assertEqual(variant.text, "A four-bedroom house in Manly with ocean views.")
        self.assertTrue(variant.is_edited)
        self.assertIsNotNone(variant.edited_at)

    def test_editing_re_runs_validation(self):
        variant = self.by_kind[VariantKind.LINKEDIN_CAPTION]

        self.client.post(
            self.variant_action_url(variant, "edit"),
            {"text": "A four-bedroom house in Manly with ocean views."},
            format="json",
        )

        variant.refresh_from_db()
        # The investment claim is gone, so the fresh report is clean.
        self.assertEqual(variant.validation_status, ValidationStatus.PASSED)
        self.assertEqual(variant.validation_issues, [])

    def test_editing_keeps_the_original_for_comparison(self):
        variant = self.by_kind[VariantKind.LINKEDIN_CAPTION]

        self.client.post(
            self.variant_action_url(variant, "edit"), {"text": "Rewritten."}, format="json"
        )

        variant.refresh_from_db()
        self.assertIn("smart investment", variant.original_text)

    def test_an_edit_is_advisory_not_blocking(self):
        """The validator stops the model inventing; it does not stop an agent
        writing a sentence they can stand behind."""
        variant = self.by_kind[VariantKind.LINKEDIN_CAPTION]

        self.client.post(
            self.variant_action_url(variant, "edit"),
            {"text": "Open for inspection Saturday at 11am."},
            format="json",
        )
        variant.refresh_from_db()

        # 11 is not a listing fact, so it is flagged...
        self.assertTrue(variant.has_errors)
        # ...but the agent owns these words now, so it can still be approved.
        self.assertTrue(variant.is_usable)
        response = self.client.post(
            self.variant_action_url(variant, "review"), {"decision": "approved"}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    def test_editing_returns_a_variant_to_draft(self):
        """An approval of words that are no longer on screen means nothing."""
        variant = self.by_kind[VariantKind.PROPERTY_DESCRIPTION]
        self.client.post(
            self.variant_action_url(variant, "review"), {"decision": "approved"}, format="json"
        )

        self.client.post(
            self.variant_action_url(variant, "edit"), {"text": "Rewritten copy."}, format="json"
        )

        variant.refresh_from_db()
        self.assertEqual(variant.review_status, ReviewStatus.DRAFT)
        self.assertIsNone(variant.reviewed_at)

    def test_hashtag_variants_are_edited_as_a_list(self):
        variant = self.by_kind[VariantKind.HASHTAGS]

        response = self.client.post(
            self.variant_action_url(variant, "edit"),
            {"items": ["#Manly", "#oceanviews"]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        variant.refresh_from_db()
        self.assertEqual(variant.items, ["#Manly", "#oceanviews"])
        self.assertEqual(variant.validation_status, ValidationStatus.PASSED)

    def test_sending_prose_to_a_hashtag_variant_is_refused(self):
        variant = self.by_kind[VariantKind.HASHTAGS]

        response = self.client.post(
            self.variant_action_url(variant, "edit"), {"text": "#Manly #oceanviews"}, format="json"
        )

        self.assertEqual(response.status_code, 400)

    # -- scoping ------------------------------------------------------------

    def test_another_agent_cannot_see_or_edit_a_variant(self):
        other_agent, _ = self.make_agent_in(self.acme, "b@example.com")
        variant = self.by_kind[VariantKind.PROPERTY_DESCRIPTION]
        self.authenticate_as(other_agent)

        self.assertEqual(self.client.get(self.variant_url(variant)).status_code, 404)
        self.assertEqual(
            self.client.post(
                self.variant_action_url(variant, "edit"), {"text": "mine"}, format="json"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                self.variant_action_url(variant, "review"),
                {"decision": "approved"},
                format="json",
            ).status_code,
            404,
        )

    def test_deleting_a_generation_removes_its_variants(self):
        generation_id = self.generation.pk
        GeneratedContent.objects.filter(pk=generation_id).delete()

        self.assertEqual(
            ContentVariant.objects.filter(generation_id=generation_id).count(), 0
        )


class PartialFailureTests(AIContentTestCase):
    def test_a_missing_variant_in_the_response_is_recorded_not_crashed(self):
        """`strict` schema mode should prevent this — but the pipeline must not
        fall over if a provider ever returns a partial object."""
        partial = {k: v for k, v in GOOD_PAYLOAD.items() if k != "linkedin_caption"}

        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(partial)
        )

        self.assertEqual(generation.job_status, JobStatus.READY)
        self.assertEqual(generation.variants.count(), 6)

        linkedin = generation.variants.get(kind=VariantKind.LINKEDIN_CAPTION)
        self.assertEqual(linkedin.validation_status, ValidationStatus.REJECTED)
        self.assertFalse(linkedin.is_usable)
        # The rest survived.
        self.assertTrue(
            generation.variants.get(kind=VariantKind.INSTAGRAM_CAPTION).is_usable
        )
