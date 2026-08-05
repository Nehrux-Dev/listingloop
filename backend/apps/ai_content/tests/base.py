"""Shared helpers for the AI content tests."""

from __future__ import annotations

import json
from decimal import Decimal

from django.urls import reverse

from apps.ai_content.client import CompletionResult
from apps.listings.tests.base import ListingAPITestCase

__all__ = ["AIContentTestCase", "fake_completion", "GOOD_PAYLOAD", "POISONED_PAYLOAD"]

#: A well-behaved response for the standard test listing (see COMPLETE_LISTING
#: in the listings test base): 4 bed, 2.5 bath, 2,400 sq ft, $1,850,000, Manly
#: NSW, ocean views + double garage.
GOOD_PAYLOAD = {
    "caption": (
        "A four-bedroom house in Manly with ocean views and a double garage. "
        "Set across 2,400 sq ft. Guided at $1,850,000."
    ),
    "hashtags": ["#Manly", "#NSW", "#oceanviews", "#house", "#forsale"],
    "facts_used": ["city", "bedrooms", "features", "price", "square_footage"],
}

#: The dangerous kind of failure: fluent, confident, and containing claims that
#: are nowhere in the listing — a pool, a school zone, a yield, and a price
#: that does not match.
POISONED_PAYLOAD = {
    "caption": (
        "A four-bedroom house in Manly with ocean views, a heated swimming pool "
        "and a wine cellar. Zoned for Manly West Public School and just 400 m "
        "from the sand. A smart investment with a projected 6% rental yield — "
        "council approved plans for a second storey. Guided at $1,750,000."
    ),
    "hashtags": ["#Manly", "#investment", "#pool", "#7percentyield"],
    "facts_used": ["city", "bedrooms", "price"],
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

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.listing = self.make_listing(self.profile)
        self.listing.mark_verified(self.agent)
        self.listing.refresh_from_db()

    def make_unverified_listing(self):
        return self.make_listing(self.profile, address="2 Unverified Way", price=Decimal("500000"))
