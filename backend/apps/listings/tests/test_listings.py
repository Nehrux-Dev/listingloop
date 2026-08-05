"""CRUD and permission-scoping tests for listings and photos.

The scoping tests are the important ones: agent A must not be able to see, let
alone touch, agent B's listings — including when B is a colleague at the same
brokerage.
"""

from __future__ import annotations

import shutil
import tempfile
from decimal import Decimal

from django.test import override_settings

from apps.listings.models import Listing, ListingPhoto, ListingStatus, PropertyType
from apps.listings.tests.base import COMPLETE_LISTING, ListingAPITestCase, make_image_file

MEDIA_ROOT = tempfile.mkdtemp(prefix="real-estate-listing-media-")


class ListingCrudTests(ListingAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)
        self.agent, self.profile = self.make_agent_in(self.acme, "a1@example.com")

    def test_agent_can_create_a_listing(self):
        self.authenticate_as(self.agent)

        response = self.client.post(
            self.listings_url,
            {
                "address": "1 Test Street",
                "city": "Sydney",
                "price": "999000.00",
                "bedrooms": 3,
                "bathrooms": "2.0",
                "square_footage": 1800,
                "property_type": PropertyType.HOUSE,
                "features": ["Pool", "Solar"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        listing = Listing.objects.get(pk=response.data["id"])
        # The owner is taken from the caller; no id was sent.
        self.assertEqual(listing.agent, self.profile)
        self.assertEqual(listing.features, ["Pool", "Solar"])

    def test_the_public_slug_is_exposed_but_not_writable(self):
        """The agent needs the link; nobody gets to change it."""
        listing = self.make_listing(self.profile)
        self.authenticate_as(self.agent)

        response = self.client.patch(
            self.listing_detail_url(listing),
            {"public_slug": "chosen-by-me", "latitude": "-33.797"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        listing.refresh_from_db()
        self.assertNotEqual(listing.public_slug, "chosen-by-me")
        self.assertEqual(response.data["public_slug"], listing.public_slug)
        # Coordinates, on the other hand, are the agent's to set.
        self.assertEqual(str(listing.latitude), "-33.797000")

    def test_a_new_listing_is_never_verified(self):
        self.authenticate_as(self.agent)

        response = self.client.post(
            self.listings_url, COMPLETE_LISTING_PAYLOAD, format="json"
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["verification_status"], "unverified")
        self.assertFalse(response.data["is_verified"])

    def test_client_cannot_set_verification_status_directly(self):
        """The whole point of the review step: it is not a writable field."""
        self.authenticate_as(self.agent)

        response = self.client.post(
            self.listings_url,
            {**COMPLETE_LISTING_PAYLOAD, "verification_status": "verified"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["verification_status"], "unverified")

    def test_agent_can_read_and_update_their_own_listing(self):
        listing = self.make_listing(self.profile)
        self.authenticate_as(self.agent)

        detail_url = self.listing_detail_url(listing)
        self.assertEqual(self.client.get(detail_url).status_code, 200)

        response = self.client.patch(detail_url, {"price": "1900000.00"}, format="json")
        self.assertEqual(response.status_code, 200)
        listing.refresh_from_db()
        self.assertEqual(listing.price, Decimal("1900000.00"))

    def test_agent_can_delete_their_own_listing(self):
        listing = self.make_listing(self.profile)
        self.authenticate_as(self.agent)

        response = self.client.delete(self.listing_detail_url(listing))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Listing.objects.filter(pk=listing.pk).exists())

    def test_features_must_be_a_list_of_strings(self):
        self.authenticate_as(self.agent)

        response = self.client.post(
            self.listings_url,
            {**COMPLETE_LISTING_PAYLOAD, "features": [{"nested": "object"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("features", response.data)

    def test_negative_price_is_rejected(self):
        self.authenticate_as(self.agent)

        response = self.client.post(
            self.listings_url,
            {**COMPLETE_LISTING_PAYLOAD, "price": "-5.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_summary_counts_the_callers_own_listings(self):
        self.make_listing(self.profile)
        verified = self.make_listing(self.profile, address="2 Other Street")
        verified.mark_verified(self.agent)
        self.authenticate_as(self.agent)

        response = self.client.get(self.listing_summary_url)

        self.assertEqual(response.data, {"total": 2, "verified": 1, "unverified": 1})

    def test_filtering_by_verification_status(self):
        self.make_listing(self.profile)
        verified = self.make_listing(self.profile, address="2 Other Street")
        verified.mark_verified(self.agent)
        self.authenticate_as(self.agent)

        response = self.client.get(self.listings_url, {"verification_status": "verified"})

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], verified.pk)

    def test_unauthenticated_access_is_rejected(self):
        self.assertEqual(self.client.get(self.listings_url).status_code, 401)


class ListingScopingTests(ListingAPITestCase):
    """Agent A cannot see or touch agent B's listings."""

    def setUp(self) -> None:
        super().setUp()
        self.nehrux = self.make_nehrux_admin()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)
        self.rival = self.make_brokerage("Rival Realty")

        self.agent_a, self.profile_a = self.make_agent_in(self.acme, "a@example.com")
        # A colleague at the *same* brokerage — the sharpest case, because
        # their profiles are mutually visible.
        self.agent_b, self.profile_b = self.make_agent_in(self.acme, "b@example.com")
        self.outsider, self.profile_out = self.make_agent_in(self.rival, "c@example.com")

        self.listing_a = self.make_listing(self.profile_a, address="A Street")
        self.listing_b = self.make_listing(self.profile_b, address="B Street")
        self.listing_out = self.make_listing(self.profile_out, address="C Street")

    def test_agent_list_contains_only_their_own_listings(self):
        self.authenticate_as(self.agent_a)

        response = self.client.get(self.listings_url)

        addresses = [row["address"] for row in response.data["results"]]
        self.assertEqual(addresses, ["A Street"])

    def test_agent_cannot_retrieve_a_colleagues_listing(self):
        """Same brokerage, still not visible: listings are per-agent."""
        self.authenticate_as(self.agent_a)

        response = self.client.get(self.listing_detail_url(self.listing_b))

        self.assertEqual(response.status_code, 404)

    def test_agent_cannot_update_or_delete_another_agents_listing(self):
        self.authenticate_as(self.agent_a)
        detail_url = self.listing_detail_url(self.listing_b)

        self.assertEqual(
            self.client.patch(detail_url, {"price": "1.00"}, format="json").status_code,
            404,
        )
        self.assertEqual(self.client.delete(detail_url).status_code, 404)

        self.listing_b.refresh_from_db()
        self.assertEqual(self.listing_b.price, COMPLETE_LISTING["price"])

    def test_agent_cannot_verify_another_agents_listing(self):
        self.authenticate_as(self.agent_a)

        response = self.client.post(
            self.listing_verify_url(self.listing_b), {"confirmed": True}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.listing_b.refresh_from_db()
        self.assertFalse(self.listing_b.is_verified)

    def test_agent_cannot_file_a_listing_under_another_agent(self):
        self.authenticate_as(self.agent_a)

        response = self.client.post(
            self.listings_url,
            {**COMPLETE_LISTING_PAYLOAD, "agent": self.profile_b.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("agent", response.data)

    def test_brokerage_admin_sees_every_listing_in_their_brokerage(self):
        self.authenticate_as(self.broker_admin)

        response = self.client.get(self.listings_url)

        addresses = sorted(row["address"] for row in response.data["results"])
        self.assertEqual(addresses, ["A Street", "B Street"])

    def test_brokerage_admin_can_edit_a_listing_in_their_brokerage(self):
        self.authenticate_as(self.broker_admin)

        response = self.client.patch(
            self.listing_detail_url(self.listing_a), {"city": "Edited"}, format="json"
        )

        self.assertEqual(response.status_code, 200)

    def test_brokerage_admin_cannot_see_another_brokerages_listing(self):
        self.authenticate_as(self.broker_admin)

        self.assertEqual(
            self.client.get(self.listing_detail_url(self.listing_out)).status_code, 404
        )

    def test_nehrux_admin_sees_everything(self):
        self.authenticate_as(self.nehrux)

        response = self.client.get(self.listings_url)

        self.assertEqual(response.data["count"], 3)


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ListingPhotoTests(ListingAPITestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)
        self.agent_a, self.profile_a = self.make_agent_in(self.acme, "a@example.com")
        self.agent_b, self.profile_b = self.make_agent_in(self.acme, "b@example.com")
        self.listing_a = self.make_listing(self.profile_a)
        self.listing_b = self.make_listing(self.profile_b, address="B Street")

    def test_agent_can_upload_photos_to_their_listing(self):
        self.authenticate_as(self.agent_a)

        for order in range(3):
            response = self.client.post(
                self.photos_url,
                {
                    "listing": self.listing_a.pk,
                    "image": make_image_file(f"photo{order}.png"),
                    "order": order,
                    "caption": f"Room {order}",
                },
                format="multipart",
            )
            self.assertEqual(response.status_code, 201, response.data)

        self.assertEqual(self.listing_a.photos.count(), 3)
        self.assertTrue(
            self.listing_a.photos.first().image.name.startswith("listings/photos/")
        )

    def test_photos_come_back_in_order(self):
        self.authenticate_as(self.agent_a)
        for order in (2, 0, 1):
            self.client.post(
                self.photos_url,
                {
                    "listing": self.listing_a.pk,
                    "image": make_image_file(f"p{order}.png"),
                    "order": order,
                },
                format="multipart",
            )

        response = self.client.get(self.listing_detail_url(self.listing_a))

        orders = [photo["order"] for photo in response.data["photos"]]
        self.assertEqual(orders, [0, 1, 2])

    def test_non_image_upload_is_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.authenticate_as(self.agent_a)

        response = self.client.post(
            self.photos_url,
            {
                "listing": self.listing_a.pk,
                "image": SimpleUploadedFile("x.png", b"not an image", "image/png"),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)

    def test_agent_cannot_upload_to_another_agents_listing(self):
        self.authenticate_as(self.agent_a)

        response = self.client.post(
            self.photos_url,
            {"listing": self.listing_b.pk, "image": make_image_file("sneak.png")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.listing_b.photos.count(), 0)

    def test_agent_cannot_see_or_delete_another_agents_photos(self):
        photo = ListingPhoto.objects.create(
            listing=self.listing_b, image=make_image_file("theirs.png")
        )
        self.authenticate_as(self.agent_a)

        self.assertEqual(self.client.get(self.photos_url).data["count"], 0)
        self.assertEqual(self.client.delete(self.photo_detail_url(photo)).status_code, 404)
        self.assertTrue(ListingPhoto.objects.filter(pk=photo.pk).exists())

    def test_deleting_a_listing_deletes_its_photos(self):
        photo = ListingPhoto.objects.create(
            listing=self.listing_a, image=make_image_file("gone.png")
        )
        self.authenticate_as(self.agent_a)

        self.client.delete(self.listing_detail_url(self.listing_a))

        self.assertFalse(ListingPhoto.objects.filter(pk=photo.pk).exists())


COMPLETE_LISTING_PAYLOAD = {
    "address": "12 Harbour View Terrace",
    "city": "Manly",
    "state": "NSW",
    "postcode": "2095",
    "country": "Australia",
    "price": "1850000.00",
    "bedrooms": 4,
    "bathrooms": "2.5",
    "square_footage": 2400,
    "property_type": PropertyType.HOUSE,
    "features": ["Ocean views"],
    "status": ListingStatus.DRAFT,
}
