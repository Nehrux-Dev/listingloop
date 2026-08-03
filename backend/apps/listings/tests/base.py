"""Shared helpers for the listings test suite."""

from __future__ import annotations

from decimal import Decimal

from django.urls import reverse

from apps.accounts.tests.base import AuthAPITestCase, make_image_file
from apps.listings.models import Listing, PropertyType

__all__ = ["ListingAPITestCase", "make_image_file", "COMPLETE_LISTING"]

#: The minimum a listing needs before it can be verified, plus a bit more.
COMPLETE_LISTING = {
    "address": "12 Harbour View Terrace",
    "city": "Manly",
    "state": "NSW",
    "postcode": "2095",
    "country": "Australia",
    "price": Decimal("1850000.00"),
    "bedrooms": 4,
    "bathrooms": Decimal("2.5"),
    "square_footage": 2400,
    "property_type": PropertyType.HOUSE,
    "features": ["Ocean views", "Double garage"],
}


class ListingAPITestCase(AuthAPITestCase):
    """Adds listing URLs and factories on top of the accounts helpers."""

    listings_url = reverse("listings:listing-list")
    listing_summary_url = reverse("listings:listing-summary")
    listing_import_url = reverse("listings:listing-import-url")
    photos_url = reverse("listings:listingphoto-list")

    @staticmethod
    def listing_detail_url(listing) -> str:
        return reverse("listings:listing-detail", args=[listing.pk])

    @staticmethod
    def listing_verify_url(listing) -> str:
        return reverse("listings:listing-verify", args=[listing.pk])

    @staticmethod
    def listing_unverify_url(listing) -> str:
        return reverse("listings:listing-unverify", args=[listing.pk])

    @staticmethod
    def photo_detail_url(photo) -> str:
        return reverse("listings:listingphoto-detail", args=[photo.pk])

    @staticmethod
    def make_listing(agent_profile, **overrides) -> Listing:
        data = {**COMPLETE_LISTING, **overrides}
        return Listing.objects.create(agent=agent_profile, **data)

    def verify(self, listing, user) -> None:
        """Verify through the model helper, as the API action does."""
        listing.mark_verified(user)
        listing.refresh_from_db()
