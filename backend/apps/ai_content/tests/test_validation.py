"""The validation layer on its own.

Each rule tested against both a response it should pass and one it should
catch, because a validator that rejects everything is as useless as one that
rejects nothing.
"""

from __future__ import annotations

from apps.ai_content.models import ValidationStatus
from apps.ai_content.prompts import build_facts
from apps.ai_content.tests.base import AIContentTestCase
from apps.ai_content.validation import validate_generation


class ValidationRuleTests(AIContentTestCase):
    def _validate(self, caption: str, hashtags=None):
        facts = build_facts(self.listing)
        return validate_generation(
            {"caption": caption, "hashtags": hashtags or ["#manly"]}, self.listing, facts
        )

    def _codes(self, report):
        return {issue.code for issue in report.issues}

    # -- numbers ------------------------------------------------------------

    def test_verified_numbers_pass(self):
        report = self._validate(
            "Four bedrooms, 2.5 bathrooms and 2,400 sq ft in Manly. Guided at $1,850,000."
        )

        self.assertEqual(report.status, ValidationStatus.PASSED, report.as_list())

    def test_an_invented_number_is_an_error(self):
        report = self._validate("A short 350 m walk to the sand.")

        self.assertEqual(report.status, ValidationStatus.REJECTED)
        self.assertIn("unverified_number", self._codes(report))

    def test_a_wrong_price_is_caught(self):
        report = self._validate("Guided at $1,900,000.")

        self.assertEqual(report.status, ValidationStatus.REJECTED)

    def test_shorthand_price_forms_are_accepted(self):
        """$1.85m is the same fact as $1,850,000."""
        report = self._validate("Guided at $1.85m in Manly.")

        self.assertNotIn("unverified_number", self._codes(report))

    def test_numbers_from_the_listing_description_are_accepted(self):
        self.listing.description = "Set on the 4th floor of a 1920s building."
        self.listing.save()

        report = self._validate("A home on the 4th floor, built in 1920s Manly.")

        self.assertNotIn("unverified_number", self._codes(report))

    def test_a_written_out_count_that_is_not_a_fact_is_flagged(self):
        report = self._validate("Seven reasons to fall for this Manly home.")

        self.assertIn("unverified_number_word", self._codes(report))

    # -- features -----------------------------------------------------------

    def test_listed_features_pass(self):
        report = self._validate("Ocean views and a double garage.")

        self.assertEqual(report.status, ValidationStatus.PASSED, report.as_list())

    def test_an_unlisted_feature_is_an_error(self):
        report = self._validate("Ocean views, a double garage and a swimming pool.")

        self.assertEqual(report.status, ValidationStatus.REJECTED)
        self.assertIn("unverified_feature", self._codes(report))

    def test_a_feature_in_the_description_counts_as_verified(self):
        self.listing.description = "The home has a fireplace in the living room."
        self.listing.save()

        report = self._validate("A fireplace anchors the living room.")

        self.assertNotIn("unverified_feature", self._codes(report))

    # -- claims -------------------------------------------------------------

    def test_investment_claims_are_errors(self):
        for caption in (
            "A smart investment in Manly.",
            "Offering a strong rental yield.",
            "This home will appreciate over time.",
            "Guaranteed return for the astute buyer.",
            "Positively geared from day one.",
        ):
            with self.subTest(caption=caption):
                report = self._validate(caption)
                self.assertEqual(report.status, ValidationStatus.REJECTED)
                self.assertIn("investment_claim", self._codes(report))

    def test_legal_and_planning_claims_are_errors(self):
        for caption in (
            "Council approved plans for a second storey.",
            "Zoned for medium density.",
            "Heritage listed and beautifully kept.",
            "Torrens title.",
        ):
            with self.subTest(caption=caption):
                report = self._validate(caption)
                self.assertEqual(report.status, ValidationStatus.REJECTED)
                self.assertIn("legal_claim", self._codes(report))

    def test_comparative_superlatives_are_warnings_not_errors(self):
        """Puffery is a judgement call; unverifiable, but not a false fact."""
        report = self._validate("Quite simply the best in the street.")

        self.assertEqual(report.status, ValidationStatus.FLAGGED)
        self.assertIn("unverifiable_superlative", self._codes(report))

    def test_ordinary_warmth_is_not_penalised(self):
        """A validator that rejects adjectives gets switched off."""
        report = self._validate(
            "A calm, light-filled home in Manly with ocean views and a double garage."
        )

        self.assertEqual(report.status, ValidationStatus.PASSED, report.as_list())

    # -- locations ----------------------------------------------------------

    def test_the_listings_own_location_passes(self):
        report = self._validate("A house in Manly, NSW with ocean views.")

        self.assertEqual(report.status, ValidationStatus.PASSED, report.as_list())

    def test_an_unrelated_place_name_is_flagged(self):
        report = self._validate("Moments from Bondi Beach and the Manly ferry.")

        self.assertIn("possible_unverified_place", self._codes(report))
        # A warning, because capitalisation is a weak signal.
        self.assertEqual(report.status, ValidationStatus.FLAGGED)

    # -- hashtags -----------------------------------------------------------

    def test_hashtags_are_checked_for_invented_claims_too(self):
        report = self._validate("A house in Manly.", ["#Manly", "#8percentyield"])

        self.assertEqual(report.status, ValidationStatus.REJECTED)

    def test_malformed_hashtags_are_warnings(self):
        report = self._validate("A house in Manly.", ["not a hashtag", "#ok"])

        self.assertIn("malformed_hashtag", self._codes(report))

    # -- shape --------------------------------------------------------------

    def test_an_empty_caption_is_rejected(self):
        report = self._validate("   ")

        self.assertEqual(report.status, ValidationStatus.REJECTED)
        self.assertIn("empty_caption", self._codes(report))

    def test_a_sparse_listing_still_validates(self):
        """The case where a model is most tempted to invent."""
        sparse = self.make_listing(
            self.profile, address="5 Short Street", city="Newtown", state="NSW",
            bedrooms=None, bathrooms=None, square_footage=None, features=[],
            description="",
        )
        facts = build_facts(sparse)

        honest = validate_generation(
            {"caption": "An apartment in Newtown. Enquiries welcome.", "hashtags": ["#Newtown"]},
            sparse, facts,
        )
        padded = validate_generation(
            {"caption": "A 2-bedroom apartment in Newtown with a courtyard.", "hashtags": ["#Newtown"]},
            sparse, facts,
        )

        self.assertEqual(honest.status, ValidationStatus.PASSED, honest.as_list())
        self.assertEqual(padded.status, ValidationStatus.REJECTED)
