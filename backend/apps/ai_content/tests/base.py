"""Shared helpers for the AI content tests."""

from __future__ import annotations

import json
from decimal import Decimal

from django.urls import reverse

from apps.ai_content.client import CompletionResult
from apps.listings.tests.base import ListingAPITestCase

__all__ = [
    "AIContentTestCase",
    "fake_completion",
    "GOOD_PAYLOAD",
    "LEGACY_PAYLOAD",
    "POISONED_PAYLOAD",
]

#: A well-behaved full pack for the standard test listing (see COMPLETE_LISTING
#: in the listings test base): 4 bed, 2.5 bath, 2,400 sq ft, $1,850,000, Manly
#: NSW, ocean views + double garage.
GOOD_PAYLOAD = {
    "instagram_caption": (
        "A four-bedroom house in Manly with ocean views. Set across 2,400 sq ft, "
        "with a double garage. Guided at $1,850,000."
    ),
    "facebook_caption": (
        "Ocean views from a four-bedroom house in Manly. There are 2.5 bathrooms "
        "across 2,400 sq ft, and a double garage. Guided at $1,850,000. "
        "Get in touch to arrange a time."
    ),
    "linkedin_caption": (
        "Now available in Manly, NSW: a four-bedroom house of 2,400 sq ft with "
        "2.5 bathrooms, ocean views and a double garage. Guided at $1,850,000."
    ),
    "sharing_message": (
        "Thought of you — a four-bedroom house in Manly with ocean views, guided "
        "at $1,850,000."
    ),
    # Only the two features this listing actually has. An earlier draft of this
    # fixture added a garden, a renovated kitchen and solar panels — all real
    # features of a *different* sample listing — and the validator rejected it,
    # which is exactly what it is for.
    "property_description": (
        "This four-bedroom house in Manly, NSW offers 2,400 sq ft of living "
        "space, with 2.5 bathrooms. Ocean views are a feature of the home, and "
        "there is a double garage. Guided at $1,850,000."
    ),
    "hashtags": ["#Manly", "#NSW", "#oceanviews", "#house", "#forsale"],
    "facts_used": ["city", "bedrooms", "features", "price", "square_footage"],
}

#: The dangerous kind of failure: fluent, confident, and containing claims that
#: are nowhere in the listing. Every variant is poisoned differently, so the
#: tests can prove each rule fires on each format rather than only on the first.
POISONED_PAYLOAD = {
    # invented feature + invented distance + wrong price
    "instagram_caption": (
        "A four-bedroom house in Manly with ocean views, a heated swimming pool "
        "and a wine cellar. Just 400 m from the sand. Guided at $1,750,000."
    ),
    # invented place
    "facebook_caption": (
        "Ocean views in Manly, moments from Bondi Beach and the ferry terminal."
    ),
    # investment claim — the format where it is most tempting
    "linkedin_caption": (
        "A smart investment in Manly with a projected 6% rental yield and strong "
        "capital growth ahead."
    ),
    # legal / planning claim
    "sharing_message": "Council approved plans for a second storey — worth a look.",
    # comparative superlative (warning) — the longest format, most room to drift
    "property_description": (
        "Quite simply the best in the street, this four-bedroom house in Manly "
        "offers ocean views and a double garage across 2,400 sq ft."
    ),
    "hashtags": ["#Manly", "#investment", "#pool", "#7percentyield"],
    "facts_used": ["city", "bedrooms", "price"],
}

#: Single-caption shape, for the legacy validate_generation path.
LEGACY_PAYLOAD = {
    "caption": GOOD_PAYLOAD["instagram_caption"],
    "hashtags": GOOD_PAYLOAD["hashtags"],
}


def fake_completion(payload: dict, *, model: str = "gpt-4o-mini", prompt_tokens: int = 420, completion_tokens: int = 96):
    """Build a stub completion function returning ``payload``."""

    def _complete(messages, schema, **kwargs):
        return CompletionResult(
            payload=payload,
            raw_text=json.dumps(payload),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            duration_ms=1234,
        )

    return _complete


class AIContentTestCase(ListingAPITestCase):
    generate_url = reverse("ai_content:generatedcontent-generate")
    content_url = reverse("ai_content:generatedcontent-list")
    usage_url = reverse("ai_content:generatedcontent-usage")

    @staticmethod
    def content_detail_url(generation) -> str:
        return reverse("ai_content:generatedcontent-detail", args=[generation.pk])

    @staticmethod
    def content_action_url(generation, action: str) -> str:
        return reverse(f"ai_content:generatedcontent-{action}", args=[generation.pk])

    @staticmethod
    def variant_url(variant) -> str:
        return reverse("ai_content:contentvariant-detail", args=[variant.pk])

    @staticmethod
    def variant_action_url(variant, action: str) -> str:
        return reverse(f"ai_content:contentvariant-{action}", args=[variant.pk])

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.listing = self.make_listing(self.profile)
        self.listing.mark_verified(self.agent)
        self.listing.refresh_from_db()

    def make_unverified_listing(self):
        return self.make_listing(self.profile, address="2 Unverified Way", price=Decimal("500000"))
