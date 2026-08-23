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


# ---------------------------------------------------------------------------
# Microdata, bot walls, and the paste-the-source fallback
# ---------------------------------------------------------------------------

MICRODATA_PAGE = """
<html><body>
<div itemscope itemtype="https://schema.org/SingleFamilyResidence">
  <h1 itemprop="name">8 Rosewood Crescent</h1>
  <p itemprop="description">A renovated family home near the park.</p>
  <div itemprop="address" itemscope itemtype="https://schema.org/PostalAddress">
    <span itemprop="streetAddress">8 Rosewood Crescent</span>
    <span itemprop="addressLocality">Ottawa</span>
    <span itemprop="addressRegion">ON</span>
    <span itemprop="postalCode">K1P 1J1</span>
    <span itemprop="addressCountry">Canada</span>
  </div>
  <span itemprop="numberOfBedrooms">3</span>
  <span itemprop="numberOfBathroomsTotal">2</span>
  <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
    <meta itemprop="price" content="915000" />
    <meta itemprop="priceCurrency" content="CAD" />
  </div>
  <img itemprop="image" src="/photos/front.jpg" />
</div>
</body></html>
"""

#: A nested item whose own values must not be hoisted onto the listing.
MICRODATA_WITH_NESTED_AGENT = """
<html><body>
<div itemscope itemtype="https://schema.org/Apartment">
  <span itemprop="numberOfBedrooms">2</span>
  <div itemprop="agent" itemscope itemtype="https://schema.org/Person">
    <span itemprop="name">Someone Else</span>
    <span itemprop="numberOfBedrooms">99</span>
  </div>
</div>
</body></html>
"""

BOT_WALL_PAGE = """
<!DOCTYPE html><html><head>
<noscript><title>Pardon Our Interruption</title></noscript>
<meta name="viewport" content="width=device-width" />
</head><body>
<p>As you were browsing something about your browser made us think you were a bot.</p>
</body></html>
"""


class MicrodataTests(SimpleTestCase):
    """schema.org written inline instead of in a script tag.

    Plenty of brokerage sites and CMS templates emit only this, and before it
    was read those pages imported as blank despite stating everything needed.
    """

    def test_microdata_is_read(self):
        result = extract_listing_data(MICRODATA_PAGE, SOURCE_URL)

        self.assertEqual(result.fields["address"], "8 Rosewood Crescent")
        self.assertEqual(result.fields["city"], "Ottawa")
        self.assertEqual(result.fields["state"], "ON")
        self.assertEqual(result.fields["postcode"], "K1P 1J1")
        self.assertEqual(result.fields["bedrooms"], 3)
        self.assertEqual(result.fields["price"], Decimal("915000"))

    def test_a_microdata_page_does_not_warn_about_missing_structured_data(self):
        result = extract_listing_data(MICRODATA_PAGE, SOURCE_URL)

        self.assertFalse(
            any("no structured listing data" in w for w in result.warnings),
            result.warnings,
        )

    def test_relative_image_urls_are_resolved(self):
        result = extract_listing_data(MICRODATA_PAGE, SOURCE_URL)

        self.assertIn("https://example.test/photos/front.jpg", result.photo_urls)

    def test_a_nested_items_values_do_not_leak_onto_the_listing(self):
        """The agent's own properties are not the property's properties."""
        result = extract_listing_data(MICRODATA_WITH_NESTED_AGENT, SOURCE_URL)

        self.assertEqual(result.fields["bedrooms"], 2)

    def test_json_ld_still_wins_when_both_are_present(self):
        both = JSON_LD_PAGE + MICRODATA_PAGE

        result = extract_listing_data(both, SOURCE_URL)

        self.assertEqual(result.fields["address"], "12 Harbour View Terrace")


NEXT_DATA_PAGE = """
<html><head>
<script id="__NEXT_DATA__" type="application/json">
{"props": {"pageProps": {"property": {
  "displayAddress": "12 Harbour View Terrace, Manly",
  "listPrice": 1850000,
  "bedrooms": 4,
  "bathrooms": 2.5,
  "propertyType": "SemiDetachedHouse",
  "images": [{"url": "https://cdn.example.test/a.jpg"}, "/img/b.jpg"]
}}}}
</script>
</head><body><div id="root"></div></body></html>
"""

WINDOW_STATE_PAGE = """
<html><head><script>
window.__INITIAL_STATE__ = {"listing": {
  "address": {"street": "12 Harbour View Terrace", "city": "Manly",
              "state": "NSW", "zip": "2095"},
  "prices": {"primaryPrice": "$1,850,000"},
  "beds": 4,
  "baths": 2
}};
</script></head><body><div id="root"></div></body></html>
"""

CARD_LIST_PAGE = """
<html><head>
<script id="__NEXT_DATA__" type="application/json">
{"props": {"searchResults": [
  {"displayAddress": "1 First St", "listPrice": 500000, "bedrooms": 2, "bathrooms": 1},
  {"displayAddress": "2 Second St", "listPrice": 600000, "bedrooms": 3, "bathrooms": 2},
  {"displayAddress": "3 Third St", "listPrice": 700000, "bedrooms": 4, "bathrooms": 2}
]}}
</script>
</head><body><div id="root"></div></body></html>
"""

DISAGREEING_STATE_PAGE = """
<html><head>
<script id="__NEXT_DATA__" type="application/json">
{"entities": {
  "Listing:1": {"displayAddress": "12 Harbour View Terrace", "listPrice": 1850000,
                "bedrooms": 4, "bathrooms": 2},
  "Listing:2": {"displayAddress": "99 Somewhere Else Road", "listPrice": 725000,
                "bedrooms": 3, "bathrooms": 2}
}}
</script>
</head><body><div id="root"></div></body></html>
"""


class EmbeddedStateTests(SimpleTestCase):
    """The JSON a JavaScript-built page ships its own data in.

    These pages used to import blank from the plain fetch (their visible HTML
    is an empty shell) and needed the browser re-fetch, which the state tier
    now often makes unnecessary.
    """

    def test_next_data_island_is_read(self):
        result = extract_listing_data(NEXT_DATA_PAGE, SOURCE_URL)

        self.assertEqual(result.fields["address"], "12 Harbour View Terrace, Manly")
        self.assertEqual(result.fields["price"], Decimal("1850000"))
        self.assertEqual(result.fields["bedrooms"], 4)
        self.assertEqual(result.fields["bathrooms"], Decimal("2.5"))
        self.assertEqual(result.fields["property_type"], "house")
        self.assertTrue(result.structured)

    def test_state_photos_are_collected_and_made_absolute(self):
        result = extract_listing_data(NEXT_DATA_PAGE, SOURCE_URL)

        self.assertIn("https://cdn.example.test/a.jpg", result.photo_urls)
        self.assertIn("https://example.test/img/b.jpg", result.photo_urls)

    def test_inline_window_assignment_is_read(self):
        result = extract_listing_data(WINDOW_STATE_PAGE, SOURCE_URL)

        self.assertEqual(result.fields["address"], "12 Harbour View Terrace")
        self.assertEqual(result.fields["city"], "Manly")
        self.assertEqual(result.fields["state"], "NSW")
        self.assertEqual(result.fields["postcode"], "2095")
        self.assertEqual(result.fields["price"], Decimal("1850000"))
        self.assertEqual(result.fields["bedrooms"], 4)

    def test_a_card_list_is_not_mistaken_for_the_listing(self):
        """Search results are somebody else's properties, every one of them."""
        result = extract_listing_data(CARD_LIST_PAGE, SOURCE_URL)

        self.assertEqual(result.fields, {})
        self.assertFalse(result.structured)

    def test_disagreeing_state_objects_settle_only_what_they_agree_on(self):
        """An entity cache holds the neighbours too; unanimity or nothing."""
        result = extract_listing_data(DISAGREEING_STATE_PAGE, SOURCE_URL)

        self.assertNotIn("address", result.fields)
        self.assertNotIn("price", result.fields)
        self.assertNotIn("bedrooms", result.fields)
        self.assertEqual(result.fields["bathrooms"], Decimal("2"))
        self.assertTrue(any("conflicting values" in w for w in result.warnings))

    def test_json_ld_wins_over_embedded_state(self):
        state = NEXT_DATA_PAGE.replace('"listPrice": 1850000', '"listPrice": 999')
        both = JSON_LD_PAGE + state

        result = extract_listing_data(both, SOURCE_URL)

        self.assertEqual(result.fields["price"], Decimal("1850000"))

    def test_javascript_that_is_not_json_is_skipped_not_evaluated(self):
        html = (
            "<html><head><script>window.PAGE_MODEL = {foo: bar, nope};"
            "</script></head><body>hi</body></html>"
        )

        result = extract_listing_data(html, SOURCE_URL)

        self.assertEqual(result.fields, {})
        self.assertFalse(result.structured)

    def test_an_area_with_no_unit_is_not_assumed_to_be_square_feet(self):
        html = NEXT_DATA_PAGE.replace('"listPrice": 1850000', '"listPrice": 1850000, "livingArea": 200')

        result = extract_listing_data(html, SOURCE_URL)

        self.assertNotIn("square_footage", result.fields)


class BotWallTests(SimpleTestCase):
    """A challenge page is not an empty listing, and must not read as one."""

    def test_a_bot_wall_is_recognised(self):
        from apps.listings.fetching import looks_like_bot_wall

        self.assertTrue(looks_like_bot_wall(BOT_WALL_PAGE))

    def test_a_normal_page_is_not_mistaken_for_one(self):
        from apps.listings.fetching import looks_like_bot_wall

        self.assertFalse(looks_like_bot_wall(JSON_LD_PAGE))
        self.assertFalse(looks_like_bot_wall(BARE_PAGE))

    def test_the_phrase_appearing_late_in_a_real_page_is_not_a_block(self):
        """A listing that happens to quote the words is still a listing."""
        from apps.listings.fetching import looks_like_bot_wall

        page = JSON_LD_PAGE + "x" * 5000 + "<p>Pardon our interruption, open house!</p>"

        self.assertFalse(looks_like_bot_wall(page))


class BlockedSiteEndpointTests(ListingAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.authenticate_as(self.agent)

    @mock.patch("apps.listings.importing.fetch_document")
    def test_a_blocked_site_is_reported_as_blocked_not_as_an_empty_page(self, fetch_doc):
        from apps.listings.fetching import SiteBlockedError

        fetch_doc.side_effect = SiteBlockedError(
            "This website does not allow automatic importing."
        )

        response = self.client.post(
            self.listing_import_url, {"url": SOURCE_URL}, format="json"
        )

        self.assertEqual(response.status_code, 422)
        self.assertTrue(response.data["blocked_by_site"])
        # No half-built draft left behind.
        self.assertEqual(Listing.objects.count(), 0)

    @mock.patch("apps.listings.importing.fetch_document")
    def test_an_ordinary_fetch_failure_is_not_flagged_as_blocked(self, fetch_doc):
        fetch_doc.side_effect = FetchError("The page could not be reached.")

        response = self.client.post(
            self.listing_import_url, {"url": SOURCE_URL}, format="json"
        )

        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.data["blocked_by_site"])


class PastedSourceTests(ListingAPITestCase):
    """The route for sites that refuse us: the agent fetches, we parse."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.authenticate_as(self.agent)

    def _paste(self, html: str, url: str = SOURCE_URL):
        return self.client.post(
            self.listing_import_html_url, {"html": html, "url": url}, format="json"
        )

    def test_pasted_source_produces_the_same_fields_as_a_fetch(self):
        response = self._paste(JSON_LD_PAGE)

        self.assertEqual(response.status_code, 201, response.data)
        listing = Listing.objects.get(pk=response.data["listing"]["id"])
        self.assertEqual(listing.address, "12 Harbour View Terrace")
        self.assertEqual(listing.price, Decimal("1850000.00"))
        self.assertEqual(listing.bedrooms, 4)

    def test_pasted_source_is_still_only_a_draft(self):
        """Who fetched the page changes nothing about trusting it."""
        response = self._paste(JSON_LD_PAGE)

        listing = Listing.objects.get(pk=response.data["listing"]["id"])
        self.assertEqual(listing.verification_status, VerificationStatus.UNVERIFIED)
        self.assertEqual(listing.status, "draft")
        self.assertEqual(listing.source, ListingSource.IMPORT)

    def test_it_still_refuses_to_invent_anything(self):
        response = self._paste(AMBIGUOUS_PAGE)

        listing = Listing.objects.get(pk=response.data["listing"]["id"])
        self.assertIsNone(listing.price)
        self.assertIsNone(listing.bedrooms)

    @mock.patch("apps.listings.importing.fetch_image")
    def test_no_outbound_request_is_made(self, fetch_img):
        """The whole point: this path never touches the network.

        Photos referenced in pasted markup usually sit behind the same wall
        that blocked the page, so they are reported rather than attempted.
        """
        response = self._paste(JSON_LD_PAGE)

        fetch_img.assert_not_called()
        self.assertEqual(response.data["photo_count"], 0)
        self.assertTrue(
            any("not downloaded" in w for w in response.data["warnings"]),
            response.data["warnings"],
        )

    def test_the_source_url_is_recorded_but_never_fetched(self):
        with mock.patch("apps.listings.importing.fetch_document") as fetch_doc:
            response = self._paste(JSON_LD_PAGE, url="https://blocked.test/a-listing")

        fetch_doc.assert_not_called()
        listing = Listing.objects.get(pk=response.data["listing"]["id"])
        self.assertEqual(listing.source_url, "https://blocked.test/a-listing")

    def test_a_url_pasted_into_the_html_box_is_rejected_helpfully(self):
        """The mistake that started all this: pasting a link, not the source."""
        response = self._paste("https://www.realtor.ca/real-estate/30132324/x")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Ctrl+U", str(response.data["html"]))

    def test_pasting_requires_authentication(self):
        self.client.credentials()

        response = self._paste(JSON_LD_PAGE)

        self.assertEqual(response.status_code, 401)


#: What a JavaScript-built listing page looks like to a plain HTTP client:
#: an empty shell. A person sees a full listing; `requests` sees this.
JS_SHELL_PAGE = """
<html><head><title>Loading…</title></head>
<body><div id="root"></div><script src="/app.js"></script></body></html>
"""


@override_settings(LISTING_IMPORT_USE_BROWSER=True)
class BrowserRetryTests(ListingAPITestCase):
    """Pasting a link should work on sites that build the page in JavaScript.

    The plain fetch stays the default because it is far cheaper. The browser is
    a second attempt, made only on evidence that the first one found nothing.
    """

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.authenticate_as(self.agent)

    @mock.patch("apps.listings.importing.fetch_image")
    @mock.patch("apps.listings.importing.fetch_document_rendered")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_a_js_only_page_is_retried_in_a_browser(self, fetch_doc, fetch_rendered, fetch_img):
        fetch_doc.return_value = _document(JS_SHELL_PAGE)
        fetch_rendered.return_value = _document(JSON_LD_PAGE)
        fetch_img.return_value = FetchedDocument(
            url="https://cdn.example.test/a.jpg",
            content_type="image/png",
            content=make_image_file("a.png").read(),
        )

        response = self.client.post(
            self.listing_import_url, {"url": SOURCE_URL}, format="json"
        )

        self.assertEqual(response.status_code, 201, response.data)
        fetch_rendered.assert_called_once()
        listing = Listing.objects.get(pk=response.data["listing"]["id"])
        self.assertEqual(listing.address, "12 Harbour View Terrace")
        self.assertEqual(listing.bedrooms, 4)

    @mock.patch("apps.listings.importing.fetch_image")
    @mock.patch("apps.listings.importing.fetch_document_rendered")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_a_page_that_already_worked_is_not_re_fetched(
        self, fetch_doc, fetch_rendered, fetch_img
    ):
        """The browser costs seconds. Do not spend them on a page that parsed."""
        fetch_doc.return_value = _document(JSON_LD_PAGE)
        fetch_img.return_value = FetchedDocument(
            url="https://cdn.example.test/a.jpg",
            content_type="image/png",
            content=make_image_file("a.png").read(),
        )

        self.client.post(self.listing_import_url, {"url": SOURCE_URL}, format="json")

        fetch_rendered.assert_not_called()

    @mock.patch("apps.listings.importing.fetch_document_rendered")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_a_thin_page_does_not_look_richer_just_for_being_rendered(
        self, fetch_doc, fetch_rendered
    ):
        """A genuinely empty listing stays empty rather than acquiring guesses."""
        fetch_doc.return_value = _document(AMBIGUOUS_PAGE)
        fetch_rendered.return_value = _document(BARE_PAGE)

        response = self.client.post(
            self.listing_import_url, {"url": SOURCE_URL}, format="json"
        )

        listing = Listing.objects.get(pk=response.data["listing"]["id"])
        self.assertIsNone(listing.price)
        self.assertIsNone(listing.bedrooms)

    @mock.patch("apps.listings.importing.fetch_document_rendered")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_a_broken_renderer_does_not_fail_an_import_that_worked(
        self, fetch_doc, fetch_rendered
    ):
        """The browser is a bonus, not a dependency."""
        fetch_doc.return_value = _document(AMBIGUOUS_PAGE)
        fetch_rendered.side_effect = FetchError("renderer is down")

        response = self.client.post(
            self.listing_import_url, {"url": SOURCE_URL}, format="json"
        )

        self.assertEqual(response.status_code, 201, response.data)

    @mock.patch("apps.listings.importing.fetch_document_rendered")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_a_site_that_blocks_both_is_reported_as_blocked(
        self, fetch_doc, fetch_rendered
    ):
        from apps.listings.fetching import SiteBlockedError

        fetch_doc.side_effect = SiteBlockedError("plain client refused")
        fetch_rendered.side_effect = SiteBlockedError("browser refused too")

        response = self.client.post(
            self.listing_import_url, {"url": SOURCE_URL}, format="json"
        )

        self.assertEqual(response.status_code, 422)
        self.assertTrue(response.data["blocked_by_site"])
        self.assertEqual(Listing.objects.count(), 0)

    @mock.patch("apps.listings.importing.fetch_image")
    @mock.patch("apps.listings.importing.fetch_document_rendered")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_a_browser_gets_through_where_a_plain_client_did_not(
        self, fetch_doc, fetch_rendered, fetch_img
    ):
        """Some sites turn away HTTP clients but serve a real browser fine.

        Being an actual browser is not a disguise, so this is worth trying
        before telling the agent the site refused them.
        """
        from apps.listings.fetching import SiteBlockedError

        fetch_doc.side_effect = SiteBlockedError("plain client refused")
        fetch_rendered.return_value = _document(JSON_LD_PAGE)
        fetch_img.return_value = FetchedDocument(
            url="https://cdn.example.test/a.jpg",
            content_type="image/png",
            content=make_image_file("a.png").read(),
        )

        response = self.client.post(
            self.listing_import_url, {"url": SOURCE_URL}, format="json"
        )

        self.assertEqual(response.status_code, 201, response.data)
        listing = Listing.objects.get(pk=response.data["listing"]["id"])
        self.assertEqual(listing.bedrooms, 4)

    @override_settings(LISTING_IMPORT_USE_BROWSER=False)
    @mock.patch("apps.listings.importing.fetch_document_rendered")
    @mock.patch("apps.listings.importing.fetch_document")
    def test_the_retry_can_be_switched_off(self, fetch_doc, fetch_rendered):
        fetch_doc.return_value = _document(JS_SHELL_PAGE)

        self.client.post(self.listing_import_url, {"url": SOURCE_URL}, format="json")

        fetch_rendered.assert_not_called()
