"""Tests for the one-off URL import.

No real network traffic: the fetch layer is stubbed, so these tests exercise
extraction, draft creation and failure handling deterministically. The SSRF
guard is tested directly against IP literals and loopback names, which resolve
without a network.
"""

from __future__ import annotations

import shutil
import tempfile
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.listings.extraction import extract_listing_data
from apps.listings.fetching import FetchedDocument, FetchError, UnsafeUrlError, assert_fetchable
from apps.listings.models import Listing, ListingSource, VerificationStatus
from apps.listings.tests.base import ListingAPITestCase, make_image_file

MEDIA_ROOT = tempfile.mkdtemp(prefix="real-estate-import-media-")

SOURCE_URL = "https://example.test/listings/12-harbour-view"

JSON_LD_PAGE = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "SingleFamilyResidence",
  "name": "12 Harbour View Terrace",
  "description": "A light-filled family home with ocean views.",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "12 Harbour View Terrace",
    "addressLocality": "Manly",
    "addressRegion": "NSW",
    "postalCode": "2095",
    "addressCountry": "Australia"
  },
  "numberOfBedrooms": 4,
  "numberOfBathroomsTotal": 2.5,
  "floorSize": {"@type": "QuantitativeValue", "value": 2400, "unitCode": "FTK"},
  "offers": {"@type": "Offer", "price": "1850000", "priceCurrency": "AUD"},
  "image": ["https://cdn.example.test/a.jpg", "https://cdn.example.test/b.jpg"]
}
</script>
</head><body><h1>12 Harbour View Terrace</h1></body></html>
"""

BARE_PAGE = """
<html><head><title>A property</title></head>
<body><p>Contact us for details. Inspection Saturday.</p></body></html>
"""

AMBIGUOUS_PAGE = """
<html><body>
  <div class="result">Charming cottage with 2 bedrooms</div>
  <div class="result">Nearby: modern home with 5 bedrooms</div>
  <div>Asking $1,250,000 &mdash; reduced from $1,400,000</div>
</body></html>
"""


def _document(html: str, url: str = SOURCE_URL) -> FetchedDocument:
    return FetchedDocument(url=url, content_type="text/html", content=html.encode())


class ExtractionTests(SimpleTestCase):
    """The parser on its own: what it reads, and what it refuses to."""

    def test_structured_data_is_read(self):
        result = extract_listing_data(JSON_LD_PAGE, SOURCE_URL)

        self.assertEqual(result.fields["address"], "12 Harbour View Terrace")
        self.assertEqual(result.fields["city"], "Manly")
        self.assertEqual(result.fields["state"], "NSW")
        self.assertEqual(result.fields["postcode"], "2095")
        self.assertEqual(result.fields["price"], Decimal("1850000"))
        self.assertEqual(result.fields["bedrooms"], 4)
        self.assertEqual(result.fields["bathrooms"], Decimal("2.5"))
        self.assertEqual(result.fields["square_footage"], 2400)
        self.assertEqual(result.fields["property_type"], "house")
        self.assertEqual(len(result.photo_urls), 2)

    def test_nothing_is_invented_from_a_bare_page(self):
        """The core promise: no structured data means no data."""
        result = extract_listing_data(BARE_PAGE, SOURCE_URL)

        for name in ("address", "city", "price", "bedrooms", "bathrooms"):
            self.assertNotIn(name, result.fields)
        self.assertTrue(result.warnings)

    def test_price_is_never_read_from_page_text(self):
        """Listing pages are full of numbers that look like prices."""
        result = extract_listing_data(AMBIGUOUS_PAGE, SOURCE_URL)

        self.assertNotIn("price", result.fields)
        self.assertTrue(
            any("price" in warning.lower() for warning in result.warnings)
        )

    def test_conflicting_values_are_left_blank_with_a_warning(self):
        """Two different bedroom counts on one page means 'don't know'."""
        result = extract_listing_data(AMBIGUOUS_PAGE, SOURCE_URL)

        self.assertNotIn("bedrooms", result.fields)
        self.assertTrue(
            any("several different values" in w for w in result.warnings)
        )

    def test_a_single_labelled_value_is_accepted(self):
        html = "<html><body><p>Spacious home with 3 bedrooms and 2 baths.</p></body></html>"

        result = extract_listing_data(html, SOURCE_URL)

        self.assertEqual(result.fields["bedrooms"], 3)
        self.assertEqual(result.fields["bathrooms"], Decimal("2"))

    def test_square_metres_are_converted_and_flagged(self):
        html = JSON_LD_PAGE.replace('"unitCode": "FTK"', '"unitCode": "MTK"')

        result = extract_listing_data(html, SOURCE_URL)

        self.assertEqual(result.fields["square_footage"], 25833)
        self.assertTrue(any("converted" in w for w in result.warnings))

    def test_malformed_json_ld_does_not_break_the_import(self):
        html = '<html><head><script type="application/ld+json">{ oops </script></head><body>hi</body></html>'

        result = extract_listing_data(html, SOURCE_URL)

        self.assertEqual(result.fields, {})
        self.assertTrue(result.warnings)

    def test_open_graph_images_are_collected_and_made_absolute(self):
        html = (
            '<html><head><meta property="og:image" content="/img/hero.jpg">'
            '<meta property="og:description" content="Lovely home."></head><body></body></html>'
        )

        result = extract_listing_data(html, SOURCE_URL)

        self.assertEqual(result.photo_urls, ["https://example.test/img/hero.jpg"])
        self.assertEqual(result.fields["description"], "Lovely home.")


class SafeUrlTests(SimpleTestCase):
    """The SSRF guard. These are the URLs that must never be fetched."""

    def test_loopback_is_refused(self):
        for url in (
            "http://127.0.0.1/",
            "http://localhost:8000/api/admin/platform-overview/",
            "http://[::1]/",
        ):
            with self.subTest(url=url), self.assertRaises(UnsafeUrlError):
                assert_fetchable(url)

    def test_private_ranges_are_refused(self):
        for url in ("http://10.0.0.5:6379/", "http://192.168.1.1/", "http://172.16.0.1/"):
            with self.subTest(url=url), self.assertRaises(UnsafeUrlError):
                assert_fetchable(url)

    def test_cloud_metadata_address_is_refused(self):
        """169.254.169.254 hands out instance credentials on most clouds."""
        with self.assertRaises(UnsafeUrlError):
            assert_fetchable("http://169.254.169.254/latest/meta-data/")

    def test_non_http_schemes_are_refused(self):
        for url in ("file:///etc/passwd", "gopher://x/", "ftp://x/", "redis://localhost"):
            with self.subTest(url=url), self.assertRaises(UnsafeUrlError):
                assert_fetchable(url)

    def test_embedded_credentials_are_refused(self):
        with self.assertRaises(UnsafeUrlError):
            assert_fetchable("http://user:pass@127.0.0.1/")

    def test_unresolvable_host_is_refused(self):
        with self.assertRaises(UnsafeUrlError):
            assert_fetchable("http://this-host-does-not-exist.invalid/")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ImportEndpointTests(ListingAPITestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.authenticate_as(self.agent)

    def _import(self, url: str = SOURCE_URL):
        return self.client.post(self.listing_import_url, {"url": url}, format="json")

    @mock.patch("apps.listings.importing.fetch_image")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_successful_import_creates_an_unverified_draft(self, fetch_doc, fetch_img):
        fetch_doc.return_value = _document(JSON_LD_PAGE)
        fetch_img.return_value = FetchedDocument(
            url="https://cdn.example.test/a.jpg",
            content_type="image/png",
            content=make_image_file("a.png").read(),
        )

        response = self._import()

        self.assertEqual(response.status_code, 201, response.data)
        listing = Listing.objects.get(pk=response.data["listing"]["id"])

        self.assertEqual(listing.agent, self.profile)
        self.assertEqual(listing.source, ListingSource.IMPORT)
        self.assertEqual(listing.source_url, SOURCE_URL)
        self.assertEqual(listing.price, Decimal("1850000.00"))
        self.assertEqual(listing.bedrooms, 4)

        # However complete the extraction looked, it is still a draft.
        self.assertEqual(listing.verification_status, VerificationStatus.UNVERIFIED)
        self.assertEqual(listing.status, "draft")

    @mock.patch("apps.listings.importing.fetch_image")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_import_records_exactly_which_fields_it_filled(self, fetch_doc, fetch_img):
        fetch_doc.return_value = _document(JSON_LD_PAGE)
        fetch_img.side_effect = FetchError("no")

        response = self._import()

        extracted = response.data["extracted_fields"]
        self.assertIn("price", extracted)
        self.assertIn("bedrooms", extracted)
        listing = Listing.objects.get(pk=response.data["listing"]["id"])
        self.assertEqual(sorted(listing.imported_fields), sorted(extracted))

    @mock.patch("apps.listings.importing.fetch_document")
    def test_unparseable_page_yields_a_blank_draft_and_warnings(self, fetch_doc):
        """Graceful failure: blank fields, explicit warnings, no guesses."""
        fetch_doc.return_value = _document(BARE_PAGE)

        response = self._import()

        self.assertEqual(response.status_code, 201)
        listing = Listing.objects.get(pk=response.data["listing"]["id"])

        self.assertEqual(listing.address, "")
        self.assertIsNone(listing.price)
        self.assertIsNone(listing.bedrooms)
        self.assertEqual(listing.imported_fields, [])
        self.assertTrue(listing.import_warnings)
        # And it certainly cannot be used yet.
        self.assertFalse(listing.is_usable_for_content)

    @mock.patch("apps.listings.importing.fetch_document")
    def test_fetch_failure_creates_nothing(self, fetch_doc):
        fetch_doc.side_effect = FetchError("The page returned HTTP 404.")

        response = self._import()

        self.assertEqual(response.status_code, 502)
        self.assertIn("could not be imported", response.data["detail"])
        self.assertFalse(Listing.objects.exists())

    @mock.patch("apps.listings.importing.fetch_document")
    def test_unsafe_url_is_refused_before_anything_is_created(self, fetch_doc):
        fetch_doc.side_effect = UnsafeUrlError(
            "That URL resolves to a private or internal address, which cannot be imported."
        )

        response = self._import("http://127.0.0.1/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("private or internal", response.data["detail"])
        self.assertFalse(Listing.objects.exists())

    @mock.patch("apps.listings.importing.fetch_image")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_photos_are_downloaded_and_attached(self, fetch_doc, fetch_img):
        fetch_doc.return_value = _document(JSON_LD_PAGE)
        fetch_img.return_value = FetchedDocument(
            url="https://cdn.example.test/a.jpg",
            content_type="image/png",
            content=make_image_file("a.png").read(),
        )

        response = self._import()

        listing = Listing.objects.get(pk=response.data["listing"]["id"])
        self.assertEqual(listing.photos.count(), 2)
        self.assertEqual(response.data["photo_count"], 2)
        photo = listing.photos.first()
        self.assertTrue(photo.image.name.startswith("listings/photos/"))
        self.assertEqual(photo.source_url, "https://cdn.example.test/a.jpg")

    @mock.patch("apps.listings.importing.fetch_image")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_a_failing_photo_does_not_lose_the_import(self, fetch_doc, fetch_img):
        fetch_doc.return_value = _document(JSON_LD_PAGE)
        fetch_img.side_effect = FetchError("Image unavailable.")

        response = self._import()

        self.assertEqual(response.status_code, 201)
        listing = Listing.objects.get(pk=response.data["listing"]["id"])
        self.assertEqual(listing.photos.count(), 0)
        self.assertTrue(any("photo" in w.lower() for w in response.data["warnings"]))
        # The text fields survived.
        self.assertEqual(listing.bedrooms, 4)

    @mock.patch("apps.listings.importing.fetch_image")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_a_disguised_image_is_rejected(self, fetch_doc, fetch_img):
        """Remote images get the same validation as browser uploads."""
        fetch_doc.return_value = _document(JSON_LD_PAGE)
        fetch_img.return_value = FetchedDocument(
            url="https://cdn.example.test/a.jpg",
            content_type="image/png",
            content=b"#!/bin/sh\nrm -rf /\n",
        )

        response = self._import()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["photo_count"], 0)

    @mock.patch("apps.listings.importing.fetch_image")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_imported_listing_must_still_be_reviewed_before_use(self, fetch_doc, fetch_img):
        fetch_doc.return_value = _document(JSON_LD_PAGE)
        fetch_img.side_effect = FetchError("not needed here")
        listing_id = self._import().data["listing"]["id"]
        listing = Listing.objects.get(pk=listing_id)

        # The agent reviews, corrects the price the page did not have, and
        # confirms — which is the whole point of the verification step.
        response = self.client.post(
            self.listing_verify_url(listing), {"confirmed": True}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        listing.refresh_from_db()
        self.assertTrue(listing.is_usable_for_content)

    def test_import_requires_authentication(self):
        self.client.credentials()

        response = self._import()

        self.assertEqual(response.status_code, 401)

    def test_invalid_url_is_rejected_without_fetching(self):
        response = self.client.post(
            self.listing_import_url, {"url": "not a url"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("url", response.data)
