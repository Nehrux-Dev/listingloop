"""Verification state transitions.

Three properties are being pinned down here:

  1. Verification only ever happens through an explicit, confirmed action.
  2. It cannot happen while required data is missing.
  3. Editing the data undoes it — so "verified" always refers to the values
     that are in the record right now, not to values that used to be there.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied

from apps.listings.models import Listing, ListingStatus, VerificationStatus
from apps.listings.services import ListingNotVerifiedError, get_listing_for_content
from apps.listings.tests.base import ListingAPITestCase


class VerificationActionTests(ListingAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.listing = self.make_listing(self.profile)
        self.authenticate_as(self.agent)

    def test_agent_verifies_a_complete_listing(self):
        response = self.client.post(
            self.listing_verify_url(self.listing), {"confirmed": True}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["verification_status"], "verified")

        self.listing.refresh_from_db()
        self.assertTrue(self.listing.is_verified)
        self.assertIsNotNone(self.listing.verified_at)
        # Recorded so there is an audit trail of who confirmed it.
        self.assertEqual(self.listing.verified_by, self.agent)

    def test_confirmation_flag_is_required(self):
        """An empty POST must not verify anything."""
        without_flag = self.client.post(
            self.listing_verify_url(self.listing), {}, format="json"
        )
        explicit_no = self.client.post(
            self.listing_verify_url(self.listing), {"confirmed": False}, format="json"
        )

        self.assertEqual(without_flag.status_code, 400)
        self.assertEqual(explicit_no.status_code, 400)
        self.listing.refresh_from_db()
        self.assertFalse(self.listing.is_verified)

    def test_incomplete_listing_cannot_be_verified(self):
        incomplete = self.make_listing(
            self.profile, address="", city="", price=None, property_type=""
        )

        response = self.client.post(
            self.listing_verify_url(incomplete), {"confirmed": True}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        for field in ("address", "city", "price", "property_type"):
            self.assertIn(field, response.data)

        incomplete.refresh_from_db()
        self.assertFalse(incomplete.is_verified)

    def test_missing_required_fields_is_reported_to_the_client(self):
        incomplete = self.make_listing(self.profile, price=None, city="")

        response = self.client.get(self.listing_detail_url(incomplete))

        self.assertCountEqual(
            response.data["missing_required_fields"], ["city", "price"]
        )

    def test_agent_can_withdraw_verification(self):
        self.listing.mark_verified(self.agent)

        response = self.client.post(self.listing_unverify_url(self.listing), format="json")

        self.assertEqual(response.status_code, 200)
        self.listing.refresh_from_db()
        self.assertFalse(self.listing.is_verified)
        self.assertIsNone(self.listing.verified_at)
        self.assertIsNone(self.listing.verified_by)

    def test_verifying_twice_is_harmless(self):
        self.client.post(
            self.listing_verify_url(self.listing), {"confirmed": True}, format="json"
        )
        response = self.client.post(
            self.listing_verify_url(self.listing), {"confirmed": True}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.listing.refresh_from_db()
        self.assertTrue(self.listing.is_verified)


class VerificationResetTests(ListingAPITestCase):
    """Editing the data drops verification."""

    def setUp(self) -> None:
        super().setUp()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.listing = self.make_listing(self.profile)
        self.listing.mark_verified(self.agent)
        self.authenticate_as(self.agent)

    def test_changing_the_price_resets_verification(self):
        """The case this rule exists for."""
        response = self.client.patch(
            self.listing_detail_url(self.listing), {"price": "2100000.00"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["verification_status"], "unverified")

        self.listing.refresh_from_db()
        self.assertFalse(self.listing.is_verified)
        self.assertIsNone(self.listing.verified_by)

    def test_changing_the_address_resets_verification(self):
        self.client.patch(
            self.listing_detail_url(self.listing),
            {"address": "Somewhere else entirely"},
            format="json",
        )

        self.listing.refresh_from_db()
        self.assertFalse(self.listing.is_verified)

    def test_changing_features_resets_verification(self):
        self.client.patch(
            self.listing_detail_url(self.listing),
            {"features": ["Something new"]},
            format="json",
        )

        self.listing.refresh_from_db()
        self.assertFalse(self.listing.is_verified)

    def test_changing_only_the_sales_status_keeps_verification(self):
        """Marking a verified listing 'sold' does not change what it claims."""
        self.client.patch(
            self.listing_detail_url(self.listing),
            {"status": ListingStatus.SOLD},
            format="json",
        )

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, ListingStatus.SOLD)
        self.assertTrue(self.listing.is_verified)

    def test_saving_without_changes_keeps_verification(self):
        self.client.patch(
            self.listing_detail_url(self.listing),
            {"price": str(self.listing.price)},
            format="json",
        )

        self.listing.refresh_from_db()
        self.assertTrue(self.listing.is_verified)

    def test_reset_also_applies_outside_the_api(self):
        """The rule lives on the model, so the admin and shell obey it too."""
        listing = Listing.objects.get(pk=self.listing.pk)
        listing.bedrooms = 9
        listing.save()

        listing.refresh_from_db()
        self.assertEqual(listing.verification_status, VerificationStatus.UNVERIFIED)

    def test_brokerage_admin_edit_also_resets_verification(self):
        self.authenticate_as(self.broker_admin)

        self.client.patch(
            self.listing_detail_url(self.listing), {"bedrooms": 6}, format="json"
        )

        self.listing.refresh_from_db()
        self.assertFalse(self.listing.is_verified)


class ContentGateTests(ListingAPITestCase):
    """Only verified listings may be used by later steps."""

    def setUp(self) -> None:
        super().setUp()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)
        self.rival = self.make_brokerage("Rival Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.outsider, self.profile_out = self.make_agent_in(self.rival, "c@example.com")

    def test_unverified_listing_is_refused(self):
        listing = self.make_listing(self.profile)

        with self.assertRaises(ListingNotVerifiedError):
            get_listing_for_content(self.agent, listing.pk)

    def test_verified_listing_is_returned(self):
        listing = self.make_listing(self.profile)
        listing.mark_verified(self.agent)

        self.assertEqual(get_listing_for_content(self.agent, listing.pk), listing)

    def test_another_agents_listing_is_refused_even_when_verified(self):
        """Scoping is checked before verification, and does not leak the id."""
        listing = self.make_listing(self.profile_out)
        listing.mark_verified(self.outsider)

        with self.assertRaises(PermissionDenied):
            get_listing_for_content(self.agent, listing.pk)

    def test_editing_a_verified_listing_closes_the_gate_again(self):
        listing = self.make_listing(self.profile)
        listing.mark_verified(self.agent)

        listing.price = Decimal("1.00")
        listing.save()

        with self.assertRaises(ListingNotVerifiedError):
            get_listing_for_content(self.agent, listing.pk)

    def test_verified_queryset_helper(self):
        unverified = self.make_listing(self.profile)
        verified = self.make_listing(self.profile, address="Other")
        verified.mark_verified(self.agent)

        results = list(Listing.objects.for_user(self.agent).verified())

        self.assertEqual(results, [verified])
        self.assertNotIn(unverified, results)
