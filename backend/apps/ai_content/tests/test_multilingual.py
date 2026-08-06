"""Multilingual generation and its validation.

The central concern here is not that the model can write French. It is that the
fact-checker cannot *read* French, and that the system says so instead of
returning a green tick over copy nobody verified.
"""

from __future__ import annotations

from unittest import mock

from django.test import override_settings
from django.urls import reverse

from apps.ai_content.languages import (
    LANGUAGE_SPECIFIC_CHECKS,
    SOURCE_LANGUAGE,
    enabled_codes,
    get_language,
)
from apps.ai_content.models import GeneratedContent, JobStatus, ValidationStatus
from apps.ai_content.prompts import build_messages, language_instruction
from apps.ai_content.services import ListingNotUsable, generate_for_listing
from apps.ai_content.tests.base import GOOD_PAYLOAD, AIContentTestCase, fake_completion
from apps.ai_content.validation import validate_text

#: A clean French pack for the standard test listing. The numbers are the
#: listing's own, which is what the language-agnostic check verifies.
FRENCH_PAYLOAD = {
    "instagram_caption": (
        "Une maison de quatre chambres à Manly avec vue sur l'océan. "
        "2,400 pieds carrés et un garage double. Prix indicatif 1,850,000 $."
    ),
    "facebook_caption": (
        "Vue sur l'océan depuis cette maison de quatre chambres à Manly. "
        "Prix indicatif 1,850,000 $."
    ),
    "linkedin_caption": "Maintenant disponible à Manly : une maison de quatre chambres.",
    "sharing_message": "J'ai pensé à toi — une maison à Manly, 1,850,000 $.",
    "property_description": (
        "Cette maison de quatre chambres à Manly offre 2,400 pieds carrés. "
        "Une vue sur l'océan et un garage double. Prix indicatif 1,850,000 $."
    ),
    "hashtags": ["#Manly", "#immobilier", "#maison", "#aVendre"],
    "facts_used": ["city", "bedrooms", "price"],
}

#: French copy carrying an invented price. The number check is language
#: agnostic, so this must still be caught.
FRENCH_BAD_NUMBER_PAYLOAD = {
    **FRENCH_PAYLOAD,
    "instagram_caption": "Une maison à Manly. Prix indicatif 2,950,000 $.",
}


@override_settings(AI_CONTENT_LANGUAGES=["en", "fr", "es", "zh-hans"])
class LanguageConfigTests(AIContentTestCase):
    def test_english_is_always_available(self):
        with override_settings(AI_CONTENT_LANGUAGES=["fr"]):
            self.assertIn(SOURCE_LANGUAGE, enabled_codes())

    def test_only_configured_languages_are_offered(self):
        self.assertEqual(set(enabled_codes()), {"en", "fr", "es", "zh-hans"})

    def test_english_is_the_only_fully_validated_language(self):
        """Stated as a fact of the system, not an aspiration."""
        self.assertTrue(get_language("en").is_fully_covered)
        for code in ("fr", "es", "zh-hans", "ar", "hi"):
            with self.subTest(code=code):
                self.assertFalse(get_language(code).is_fully_covered)

    def test_a_language_reports_which_checks_it_lacks(self):
        missing = set(get_language("fr").missing_checks)

        self.assertEqual(missing, set(LANGUAGE_SPECIFIC_CHECKS))

    def test_the_api_publishes_validation_coverage(self):
        """An agent choosing a language deserves to know before they pick it."""
        self.authenticate_as(self.agent)

        response = self.client.get(reverse("ai_content:generatedcontent-languages"))

        self.assertEqual(response.status_code, 200)
        by_code = {row["code"]: row for row in response.data}
        self.assertTrue(by_code["en"]["fully_validated"])
        self.assertFalse(by_code["fr"]["fully_validated"])
        self.assertTrue(by_code["fr"]["unchecked"])

    def test_right_to_left_languages_are_marked(self):
        self.assertTrue(get_language("ar").rtl)
        self.assertFalse(get_language("fr").rtl)


@override_settings(AI_CONTENT_LANGUAGES=["en", "fr", "es"])
class PromptLanguageTests(AIContentTestCase):
    def test_english_gets_no_extra_instruction(self):
        self.assertEqual(language_instruction("en"), "")

    def test_another_language_is_asked_for_by_name(self):
        instruction = language_instruction("fr")

        self.assertIn("WRITE IN FRENCH", instruction)
        self.assertIn("French", instruction)

    def test_it_asks_for_native_writing_not_translation(self):
        """Translating English idiom word-for-word reads like a machine."""
        instruction = language_instruction("fr")

        self.assertIn("native", instruction.lower())
        self.assertIn("not translated word for", instruction.lower())

    def test_the_rules_are_restated_at_the_language_switch(self):
        """The moment a model is most likely to treat earlier rules as context."""
        instruction = language_instruction("es")

        self.assertIn("Every rule you were given still applies", instruction)
        self.assertIn("inventing a feature", instruction)

    def test_facts_must_not_change_with_the_language(self):
        instruction = language_instruction("fr")

        self.assertIn("do NOT change any of them", instruction)
        self.assertIn("same price", instruction)

    def test_the_facts_block_is_unchanged_across_languages(self):
        """One source of truth; only the output language differs."""
        english, facts_en = build_messages(self.listing, language_code="en")
        french, facts_fr = build_messages(self.listing, language_code="fr")

        self.assertEqual(facts_en, facts_fr)
        self.assertTrue(french[1]["content"].startswith(english[1]["content"]))


@override_settings(AI_CONTENT_LANGUAGES=["en", "fr", "es"])
class MultilingualGenerationTests(AIContentTestCase):
    def test_a_generation_records_its_language(self):
        generation = generate_for_listing(
            self.listing,
            self.agent,
            language="fr",
            completion_fn=fake_completion(FRENCH_PAYLOAD),
        )

        self.assertEqual(generation.language, "fr")
        self.assertEqual(generation.language_name, "French")
        self.assertEqual(generation.job_status, JobStatus.READY)

    def test_each_language_is_stored_as_its_own_pack(self):
        """“Approve the French copy” has to be expressible."""
        english = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )
        french = generate_for_listing(
            self.listing,
            self.agent,
            language="fr",
            completion_fn=fake_completion(FRENCH_PAYLOAD),
        )

        self.assertNotEqual(english.pk, french.pk)
        self.assertEqual(english.variants.count(), 6)
        self.assertEqual(french.variants.count(), 6)
        self.assertEqual(
            set(GeneratedContent.objects.filter(listing=self.listing).values_list(
                "language", flat=True
            )),
            {"en", "fr"},
        )

    def test_a_language_that_is_not_enabled_is_refused(self):
        with self.assertRaises(ListingNotUsable):
            generate_for_listing(
                self.listing, self.agent, language="ja",
                completion_fn=fake_completion(FRENCH_PAYLOAD),
            )

    def test_the_language_reaches_the_prompt(self):
        captured = {}

        def capture(messages, schema, **kwargs):
            captured["prompt"] = messages[1]["content"]
            return fake_completion(FRENCH_PAYLOAD)(messages, schema)

        generate_for_listing(
            self.listing, self.agent, language="fr", completion_fn=capture
        )

        self.assertIn("WRITE IN FRENCH", captured["prompt"])


@override_settings(AI_CONTENT_LANGUAGES=["en", "fr", "es"])
class MultilingualValidationTests(AIContentTestCase):
    """What is still checked, and what honestly is not."""

    def test_numbers_are_checked_in_every_language(self):
        """The highest-value check is language agnostic. A digit is a digit."""
        generation = generate_for_listing(
            self.listing,
            self.agent,
            language="fr",
            completion_fn=fake_completion(FRENCH_BAD_NUMBER_PAYLOAD),
        )

        instagram = generation.variants.get(kind="instagram_caption")
        codes = {issue["code"] for issue in instagram.validation_issues}

        self.assertIn("unverified_number", codes)
        self.assertEqual(instagram.validation_status, ValidationStatus.REJECTED)
        self.assertFalse(instagram.is_usable)

    def test_the_listings_own_numbers_pass_in_another_language(self):
        generation = generate_for_listing(
            self.listing,
            self.agent,
            language="fr",
            completion_fn=fake_completion(FRENCH_PAYLOAD),
        )

        instagram = generation.variants.get(kind="instagram_caption")
        codes = {issue["code"] for issue in instagram.validation_issues}

        self.assertNotIn("unverified_number", codes)

    def test_non_english_output_can_never_come_back_simply_passed(self):
        """The point of this whole file.

        The English claim patterns match nothing in French. Returning PASSED
        would tell an agent the copy was checked when it was not read.
        """
        generation = generate_for_listing(
            self.listing,
            self.agent,
            language="fr",
            completion_fn=fake_completion(FRENCH_PAYLOAD),
        )

        for variant in generation.variants.all():
            with self.subTest(kind=variant.kind):
                self.assertNotEqual(
                    variant.validation_status,
                    ValidationStatus.PASSED,
                    "French output must not report a clean bill of health",
                )

    def test_the_gap_is_named_in_the_report(self):
        generation = generate_for_listing(
            self.listing,
            self.agent,
            language="fr",
            completion_fn=fake_completion(FRENCH_PAYLOAD),
        )
        instagram = generation.variants.get(kind="instagram_caption")

        coverage = [
            issue
            for issue in instagram.validation_issues
            if issue["code"] == "partial_language_coverage"
        ]
        self.assertEqual(len(coverage), 1)
        message = coverage[0]["message"]
        self.assertIn("French", message)
        self.assertIn("partial", message.lower())
        # It says what still worked, so the warning is not read as "unchecked".
        self.assertIn("Numbers and prices were still verified", message)

    def test_english_output_is_not_burdened_with_the_warning(self):
        generation = generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )

        for variant in generation.variants.all():
            codes = {issue["code"] for issue in variant.validation_issues}
            self.assertNotIn("partial_language_coverage", codes)

        self.assertEqual(generation.validation_status, ValidationStatus.PASSED)

    def test_the_generation_is_marked_as_partially_validated(self):
        generation = generate_for_listing(
            self.listing,
            self.agent,
            language="fr",
            completion_fn=fake_completion(FRENCH_PAYLOAD),
        )

        self.assertTrue(generation.has_partial_validation)
        self.assertEqual(generation.validation_status, ValidationStatus.FLAGGED)

    def test_english_claim_patterns_are_not_applied_to_other_languages(self):
        """Not because they are safe, but because they are meaningless there —
        and pretending otherwise produces false confidence in both directions."""
        facts = {"city": "Manly"}
        text = "Un investissement intelligent avec un rendement garanti."

        english_report = validate_text(text, self.listing, facts, language_code="en")
        french_report = validate_text(text, self.listing, facts, language_code="fr")

        english_codes = {issue.code for issue in english_report.issues}
        french_codes = {issue.code for issue in french_report.issues}

        # The English patterns do not match French words either way — the point
        # is that French is FLAGGED as unchecked rather than reported clean.
        self.assertNotIn("partial_language_coverage", english_codes)
        self.assertIn("partial_language_coverage", french_codes)

    def test_an_unknown_language_code_falls_back_to_full_checking(self):
        """Fail closed: an unrecognised code gets the strictest rules, not none."""
        report = validate_text(
            "A guaranteed return awaits.",
            self.listing,
            {"city": "Manly"},
            language_code="not-a-language",
        )

        self.assertIn("investment_claim", {issue.code for issue in report.issues})


@override_settings(AI_CONTENT_LANGUAGES=["en", "fr", "es"])
class MultilingualApiTests(AIContentTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authenticate_as(self.agent)

    @mock.patch("apps.ai_content.views.generate_content.delay")
    def test_one_request_fans_out_to_one_job_per_language(self, delay):
        """Not one call returning six languages: truncation would silently lose
        the last one, and a failure would take them all down together."""
        response = self.client.post(
            self.generate_url,
            {"listing": self.listing.pk, "languages": ["en", "fr", "es"]},
            format="json",
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(response.data), 3)
        self.assertEqual(
            [row["language"] for row in response.data], ["en", "fr", "es"]
        )
        self.assertEqual(delay.call_count, 3)
        self.assertEqual(GeneratedContent.objects.count(), 3)

    @mock.patch("apps.ai_content.views.generate_content.delay")
    def test_the_default_is_english_only(self, delay):
        response = self.client.post(
            self.generate_url, {"listing": self.listing.pk}, format="json"
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["language"], "en")

    @mock.patch("apps.ai_content.views.generate_content.delay")
    def test_a_language_that_is_not_enabled_is_refused(self, delay):
        response = self.client.post(
            self.generate_url,
            {"listing": self.listing.pk, "languages": ["en", "ja"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("ja", str(response.data["languages"]))
        delay.assert_not_called()
        self.assertFalse(GeneratedContent.objects.exists())

    @mock.patch("apps.ai_content.views.generate_content.delay")
    def test_a_duplicated_language_is_not_paid_for_twice(self, delay):
        response = self.client.post(
            self.generate_url,
            {"listing": self.listing.pk, "languages": ["fr", "fr", "en"]},
            format="json",
        )

        self.assertEqual(len(response.data), 2)
        self.assertEqual(delay.call_count, 2)

    def test_content_can_be_filtered_by_language(self):
        generate_for_listing(
            self.listing, self.agent, completion_fn=fake_completion(GOOD_PAYLOAD)
        )
        generate_for_listing(
            self.listing, self.agent, language="fr",
            completion_fn=fake_completion(FRENCH_PAYLOAD),
        )

        french = self.client.get(self.content_url, {"language": "fr"})

        self.assertEqual(french.data["count"], 1)
        self.assertEqual(french.data["results"][0]["language"], "fr")

    def test_the_partial_validation_flag_reaches_the_client(self):
        generate_for_listing(
            self.listing, self.agent, language="fr",
            completion_fn=fake_completion(FRENCH_PAYLOAD),
        )
        generation = GeneratedContent.objects.get()

        response = self.client.get(self.content_detail_url(generation))

        self.assertTrue(response.data["has_partial_validation"])
        self.assertEqual(response.data["language_name"], "French")
