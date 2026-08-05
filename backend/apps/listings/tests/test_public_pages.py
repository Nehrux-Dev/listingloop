"""Public listing pages and enquiries.

The load-bearing test in this file is that an unverified listing is not
publicly reachable. Everything else in the project has an authenticated caller
whose scope can be checked; here the caller is anonymous, so the only thing
standing between an unreviewed listing and the open internet is one queryset.
"""

from __future__ import annotations

import shutil
import tempfile
from decimal import Decimal

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from apps.accounts.tests.base import make_image_file
from apps.listings.models import (
    Enquiry,
    EnquiryStatus,
    Listing,
    ListingPhoto,
    ListingStatus,
)
from apps.listings.spam import issue_form_token
from apps.listings.tests.base import ListingAPITestCase

MEDIA_ROOT = tempfile.mkdtemp(prefix="real-estate-public-media-")


# The timing check is disabled for most tests: a test client submits in
# milliseconds, so every payload would trip it and mask what is actually being
# asserted. SpamProtectionTests re-enables it to prove it fires.
@override_settings(MEDIA_ROOT=MEDIA_ROOT, ENQUIRY_MIN_FILL_SECONDS=0)
class PublicPageTestCase(ListingAPITestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        # The enquiry endpoint is rate limited per IP, and every test comes
        # from the same one.
        cache.clear()

        self.acme = self.make_brokerage("Acme Realty")
        self.acme.required_disclaimer = "Figures are indicative only."
        self.acme.phone = "+61 2 5550 0000"
        self.acme.save()

        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.profile.name = "Alex Agent"
        self.profile.phone = "+61 400 000 000"
        self.profile.email = "alex@acme.test"
        self.profile.job_title = "Principal Agent"
        self.profile.save()

        self.listing = self.make_listing(
            self.profile,
            status=ListingStatus.ACTIVE,
            latitude=Decimal("-33.797"),
            longitude=Decimal("151.288"),
        )
        self.listing.mark_verified(self.agent)
        self.listing.refresh_from_db()

    def page_url(self, listing=None) -> str:
        return reverse(
            "listings:public-listing", args=[(listing or self.listing).public_slug]
        )

    def enquiry_url(self, listing=None) -> str:
        return reverse(
            "listings:public-enquiry", args=[(listing or self.listing).public_slug]
        )

    def enquiry_payload(self, **overrides) -> dict:
        payload = {
            "name": "Jamie Buyer",
            "email": "jamie@example.com",
            "phone": "0400 111 222",
            "message": "I would like to arrange an inspection this weekend, please.",
            "form_token": issue_form_token(),
        }
        payload.update(overrides)
        return payload


class PublicVisibilityTests(PublicPageTestCase):
    def test_a_verified_active_listing_is_public(self):
        response = self.client.get(self.page_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["address"], self.listing.address)

    def test_no_authentication_is_required(self):
        self.client.credentials()  # explicitly anonymous

        self.assertEqual(self.client.get(self.page_url()).status_code, 200)

    def test_an_unverified_listing_is_not_publicly_accessible(self):
        """The one that matters. Unreviewed data must never reach the public."""
        self.listing.mark_unverified()

        response = self.client.get(self.page_url())

        self.assertEqual(response.status_code, 404)

    def test_editing_a_verified_listing_takes_it_off_the_public_page(self):
        """Editing resets verification, and the page must follow immediately."""
        self.listing.price = Decimal("1")
        self.listing.save()

        self.assertEqual(self.client.get(self.page_url()).status_code, 404)

    def test_a_draft_listing_is_not_public(self):
        self.listing.status = ListingStatus.DRAFT
        self.listing.save(update_fields=["status"])

        self.assertEqual(self.client.get(self.page_url()).status_code, 404)

    def test_a_withdrawn_listing_is_not_public(self):
        self.listing.status = ListingStatus.WITHDRAWN
        self.listing.save(update_fields=["status"])

        self.assertEqual(self.client.get(self.page_url()).status_code, 404)

    def test_a_sold_listing_stays_public(self):
        """Sold listings are marketing material in their own right."""
        self.listing.status = ListingStatus.SOLD
        self.listing.save(update_fields=["status"])

        self.assertEqual(self.client.get(self.page_url()).status_code, 200)

    def test_an_unknown_slug_is_404(self):
        response = self.client.get(
            reverse("listings:public-listing", args=["no-such-listing-abc123"])
        )

        self.assertEqual(response.status_code, 404)

    def test_a_hidden_listing_is_indistinguishable_from_one_that_never_existed(self):
        """Both 404 — otherwise the response leaks that the record exists."""
        self.listing.mark_unverified()

        hidden = self.client.get(self.page_url())
        missing = self.client.get(
            reverse("listings:public-listing", args=["definitely-not-real-zz9999"])
        )

        self.assertEqual(hidden.status_code, missing.status_code)


class PublicPayloadTests(PublicPageTestCase):
    def test_the_page_carries_everything_it_needs_to_render(self):
        ListingPhoto.objects.create(
            listing=self.listing, image=make_image_file("hero.png"), order=0
        )

        data = self.client.get(self.page_url()).data

        self.assertEqual(data["full_address"], self.listing.full_address)
        self.assertEqual(data["bedrooms"], 4)
        self.assertEqual(len(data["photos"]), 1)
        self.assertTrue(data["photos"][0]["image_url"].startswith("http"))
        self.assertEqual(data["agent"]["name"], "Alex Agent")
        self.assertEqual(data["agent"]["phone"], "+61 400 000 000")
        self.assertEqual(data["brokerage"]["name"], "Acme Realty")
        self.assertEqual(
            data["brokerage"]["required_disclaimer"], "Figures are indicative only."
        )

    def test_map_coordinates_are_published_when_a_pin_is_set(self):
        data = self.client.get(self.page_url()).data

        self.assertTrue(data["location"]["has_pin"])
        self.assertAlmostEqual(data["location"]["latitude"], -33.797, places=3)

    def test_a_listing_without_a_pin_says_so_rather_than_sending_nulls_silently(self):
        self.listing.latitude = None
        self.listing.longitude = None
        self.listing.save(update_fields=["latitude", "longitude"])

        location = self.client.get(self.page_url()).data["location"]

        self.assertFalse(location["has_pin"])
        self.assertIsNone(location["latitude"])
        self.assertTrue(location["label"])

    def test_internal_fields_are_never_published(self):
        """The serializer is an allowlist; this is the test that keeps it one."""
        self.listing.source_url = "https://internal.example/secret"
        self.listing.import_warnings = ["internal note"]
        self.listing.save(update_fields=["source_url", "import_warnings"])

        body = str(self.client.get(self.page_url()).data)

        for forbidden in (
            "verification_status",
            "source_url",
            "import_warnings",
            "imported_fields",
            "verified_by",
            "internal.example",
        ):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, body)

    def test_the_page_issues_an_enquiry_form_token(self):
        data = self.client.get(self.page_url()).data

        self.assertTrue(data["enquiry_form_token"])


class EnquirySubmissionTests(PublicPageTestCase):
    def test_an_enquiry_is_stored_against_the_listing_and_agent(self):
        response = self.client.post(
            self.enquiry_url(), self.enquiry_payload(), format="json"
        )

        self.assertEqual(response.status_code, 201)

        enquiry = Enquiry.objects.get()
        self.assertEqual(enquiry.listing, self.listing)
        self.assertEqual(enquiry.agent, self.profile)
        self.assertEqual(enquiry.name, "Jamie Buyer")
        self.assertEqual(enquiry.email, "jamie@example.com")
        self.assertEqual(enquiry.status, EnquiryStatus.NEW)
        self.assertIsNotNone(enquiry.created_at)

    def test_an_anonymous_visitor_can_submit(self):
        self.client.credentials()

        response = self.client.post(
            self.enquiry_url(), self.enquiry_payload(), format="json"
        )

        self.assertEqual(response.status_code, 201)

    def test_the_submitters_ip_and_agent_are_recorded_for_forensics(self):
        self.client.post(
            self.enquiry_url(),
            self.enquiry_payload(),
            format="json",
            HTTP_USER_AGENT="Mozilla/5.0 Test",
        )

        enquiry = Enquiry.objects.get()
        self.assertTrue(enquiry.ip_address)
        self.assertEqual(enquiry.user_agent, "Mozilla/5.0 Test")

    def test_an_enquiry_cannot_be_sent_about_an_unverified_listing(self):
        self.listing.mark_unverified()

        response = self.client.post(
            self.enquiry_url(), self.enquiry_payload(), format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Enquiry.objects.exists())

    def test_a_name_and_message_are_required(self):
        response = self.client.post(
            self.enquiry_url(), self.enquiry_payload(name="", message=""), format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Enquiry.objects.exists())

    def test_a_very_short_message_is_refused(self):
        response = self.client.post(
            self.enquiry_url(), self.enquiry_payload(message="hi"), format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_some_way_to_reply_is_required(self):
        response = self.client.post(
            self.enquiry_url(),
            self.enquiry_payload(email="", phone=""),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

    def test_the_agent_recorded_is_the_one_who_was_contacted(self):
        """Reassigning the listing later must not move the message."""
        self.client.post(self.enquiry_url(), self.enquiry_payload(), format="json")
        other_agent, other_profile = self.make_agent_in(self.acme, "b@example.com")

        self.listing.agent = other_profile
        self.listing.save(update_fields=["agent"])

        self.assertEqual(Enquiry.objects.get().agent, self.profile)


class SpamProtectionTests(PublicPageTestCase):
    def test_the_honeypot_rejects_without_storing(self):
        """No person can fill a field they cannot see."""
        response = self.client.post(
            self.enquiry_url(),
            self.enquiry_payload(website="http://spam.example"),
            format="json",
        )

        # Reported as success on purpose — telling a bot which check caught it
        # is free tuning advice.
        self.assertEqual(response.status_code, 201)
        self.assertFalse(Enquiry.objects.exists())

    @override_settings(ENQUIRY_MIN_FILL_SECONDS=3)
    def test_an_instant_submission_is_flagged_as_too_fast(self):
        """A form filled in faster than it can be read was not read."""
        response = self.client.post(
            self.enquiry_url(), self.enquiry_payload(), format="json"
        )

        self.assertEqual(response.status_code, 201)
        enquiry = Enquiry.objects.get()
        self.assertEqual(enquiry.status, EnquiryStatus.SPAM)
        self.assertTrue(any("faster than" in reason for reason in enquiry.spam_reasons))

    def test_a_missing_form_token_is_flagged_but_kept(self):
        response = self.client.post(
            self.enquiry_url(), self.enquiry_payload(form_token=""), format="json"
        )

        self.assertEqual(response.status_code, 201)
        enquiry = Enquiry.objects.get()
        self.assertEqual(enquiry.status, EnquiryStatus.SPAM)
        self.assertTrue(enquiry.spam_reasons)

    def test_a_forged_form_token_is_flagged(self):
        response = self.client.post(
            self.enquiry_url(),
            self.enquiry_payload(form_token="not:a:real:token"),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Enquiry.objects.get().status, EnquiryStatus.SPAM)

    def test_link_stuffing_is_flagged(self):
        response = self.client.post(
            self.enquiry_url(),
            self.enquiry_payload(
                message="Great site! http://spam.example and http://more.example here."
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        enquiry = Enquiry.objects.get()
        self.assertEqual(enquiry.status, EnquiryStatus.SPAM)
        self.assertTrue(any("links" in reason for reason in enquiry.spam_reasons))

    def test_marketing_vocabulary_is_flagged(self):
        self.client.post(
            self.enquiry_url(),
            self.enquiry_payload(
                message="We offer SEO services and backlink packages for your website."
            ),
            format="json",
        )

        self.assertEqual(Enquiry.objects.get().status, EnquiryStatus.SPAM)

    def test_an_identical_repeat_within_minutes_is_flagged(self):
        payload = self.enquiry_payload()
        self.client.post(self.enquiry_url(), payload, format="json")

        self.client.post(
            self.enquiry_url(), self.enquiry_payload(message=payload["message"]), format="json"
        )

        self.assertEqual(Enquiry.objects.count(), 2)
        self.assertEqual(Enquiry.objects.filter(status=EnquiryStatus.SPAM).count(), 1)

    def test_a_flagged_enquiry_is_stored_not_discarded(self):
        """A false positive that silently bins a real buyer is the expensive one."""
        self.client.post(
            self.enquiry_url(), self.enquiry_payload(form_token=""), format="json"
        )

        enquiry = Enquiry.objects.get()
        self.assertEqual(enquiry.message, self.enquiry_payload()["message"])
        self.assertTrue(enquiry.is_spam)

    def test_the_response_is_the_same_whether_flagged_or_not(self):
        clean = self.client.post(
            self.enquiry_url(), self.enquiry_payload(), format="json"
        )
        cache.clear()
        flagged = self.client.post(
            self.enquiry_url(),
            self.enquiry_payload(message="Buy crypto now, bitcoin loan offer available."),
            format="json",
        )

        self.assertEqual(clean.status_code, flagged.status_code)
        self.assertEqual(clean.data, flagged.data)

    def test_the_enquiry_form_is_rate_limited(self):
        """The one defence that helps against volume.

        Patched on the throttle class rather than via ``override_settings``:
        ``SimpleRateThrottle.THROTTLE_RATES`` binds the settings dict at import
        time, so overriding REST_FRAMEWORK in a test leaves the already-bound
        rate untouched and the throttle silently keeps its real limit.
        """
        from unittest import mock

        from apps.listings.public_views import EnquiryThrottle

        cache.clear()

        # create=True: `rate` is computed in __init__, so the class does not
        # carry the attribute until an instance exists.
        with mock.patch.object(EnquiryThrottle, "rate", "2/hour", create=True):
            codes = [
                self.client.post(
                    self.enquiry_url(),
                    self.enquiry_payload(
                        message=f"Enquiry number {index} about this lovely home."
                    ),
                    format="json",
                ).status_code
                for index in range(4)
            ]

        self.assertEqual(codes[:2], [201, 201])
        self.assertEqual(codes[2:], [429, 429])
        # The refused ones were never stored.
        self.assertEqual(Enquiry.objects.count(), 2)


class EnquiryInboxTests(PublicPageTestCase):
    """Enquiries are visible in the app, never publicly."""

    def setUp(self) -> None:
        super().setUp()
        self.client.post(self.enquiry_url(), self.enquiry_payload(), format="json")
        self.enquiry = Enquiry.objects.get()
        self.inbox_url = reverse("listings:enquiry-list")

    def test_the_agent_sees_their_own_enquiries(self):
        self.authenticate_as(self.agent)

        response = self.client.get(self.inbox_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Jamie Buyer")
        self.assertEqual(response.data["results"][0]["message"], self.enquiry.message)

    def test_an_anonymous_visitor_cannot_read_enquiries(self):
        self.client.credentials()

        self.assertEqual(self.client.get(self.inbox_url).status_code, 401)

    def test_another_agent_cannot_read_them(self):
        other_agent, _ = self.make_agent_in(self.acme, "b@example.com")
        self.authenticate_as(other_agent)

        response = self.client.get(self.inbox_url)

        self.assertEqual(response.data["count"], 0)
        detail = reverse("listings:enquiry-detail", args=[self.enquiry.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)

    def test_a_brokerage_admin_sees_the_brokerages_enquiries(self):
        broker_admin = self.make_brokerage_admin("admin@example.com")
        self.acme.admins.add(broker_admin)
        self.authenticate_as(broker_admin)

        self.assertEqual(self.client.get(self.inbox_url).data["count"], 1)

    def test_spam_is_hidden_unless_asked_for(self):
        cache.clear()
        self.client.post(
            self.enquiry_url(),
            self.enquiry_payload(message="Cheap backlink packages, SEO services here."),
            format="json",
        )
        self.authenticate_as(self.agent)

        default = self.client.get(self.inbox_url)
        with_spam = self.client.get(self.inbox_url, {"include_spam": "true"})

        self.assertEqual(default.data["count"], 1)
        self.assertEqual(with_spam.data["count"], 2)

    def test_an_agent_can_triage_an_enquiry(self):
        self.authenticate_as(self.agent)
        url = reverse("listings:enquiry-set-status", args=[self.enquiry.pk])

        response = self.client.post(url, {"status": "replied"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.enquiry.refresh_from_db()
        self.assertEqual(self.enquiry.status, EnquiryStatus.REPLIED)
        self.assertIsNotNone(self.enquiry.read_at)

    def test_another_agent_cannot_triage_it(self):
        other_agent, _ = self.make_agent_in(self.acme, "b@example.com")
        self.authenticate_as(other_agent)
        url = reverse("listings:enquiry-set-status", args=[self.enquiry.pk])

        self.assertEqual(
            self.client.post(url, {"status": "archived"}, format="json").status_code, 404
        )

    def test_enquiries_cannot_be_edited_through_the_api(self):
        """The message is the only record of what someone actually sent."""
        self.authenticate_as(self.agent)
        detail = reverse("listings:enquiry-detail", args=[self.enquiry.pk])

        response = self.client.patch(detail, {"message": "rewritten"}, format="json")

        self.assertEqual(response.status_code, 405)

    def test_the_summary_counts_new_and_spam(self):
        cache.clear()
        self.client.post(
            self.enquiry_url(),
            self.enquiry_payload(message="Bitcoin crypto loan offer, work from home."),
            format="json",
        )
        self.authenticate_as(self.agent)

        data = self.client.get(reverse("listings:enquiry-summary")).data

        self.assertEqual(data["total"], 1)
        self.assertEqual(data["new"], 1)
        self.assertEqual(data["spam"], 1)


class PublicSlugTests(ListingAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")

    def test_a_slug_is_generated_on_creation(self):
        listing = self.make_listing(self.profile)

        self.assertTrue(listing.public_slug)
        self.assertIn("harbour", listing.public_slug)

    def test_slugs_are_unique_for_identical_addresses(self):
        first = self.make_listing(self.profile)
        second = self.make_listing(self.profile)

        self.assertNotEqual(first.public_slug, second.public_slug)

    def test_the_slug_does_not_change_when_the_address_is_edited(self):
        """A shared link must keep working."""
        listing = self.make_listing(self.profile)
        original = listing.public_slug

        listing.address = "Somewhere else entirely"
        listing.save()

        listing.refresh_from_db()
        self.assertEqual(listing.public_slug, original)

    def test_a_listing_with_no_address_still_gets_a_slug(self):
        listing = self.make_listing(self.profile, address="", city="")

        self.assertTrue(listing.public_slug)
