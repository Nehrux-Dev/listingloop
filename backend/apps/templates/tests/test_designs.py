"""Design lifecycle: save, reopen, rename, duplicate, delete — and scoping."""

from __future__ import annotations

import shutil
import tempfile

from django.core.files.storage import default_storage
from django.test import override_settings

from apps.accounts.tests.base import make_image_file
from apps.templates.models import Design, TemplateCategory
from apps.templates.tests.base import TemplateAPITestCase

MEDIA_ROOT = tempfile.mkdtemp(prefix="real-estate-design-upload-media-")


class DesignRoundTripTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        self.authenticate_as(self.agent)

    def test_creating_a_design_copies_the_templates_elements(self):
        """The copy is the architecture. A design that came back with an empty
        canvas, or with a reference to the template, would mean every later
        edit was either lost or shared."""
        created = self.client.post(
            self.designs_url,
            {
                "name": "Harbour View — Instagram",
                "template": self.template.pk,
                "listing": self.listing.pk,
            },
            format="json",
        )

        self.assertEqual(created.status_code, 201, created.data)
        elements = created.data["elements"]
        self.assertEqual(len(elements), self.template.elements.count())
        self.assertEqual(
            {e["original_element_id"] for e in elements},
            set(self.template.elements.values_list("key", flat=True)),
        )

    def test_nothing_arrives_locked(self):
        """The headline change: a template cannot ship an uneditable element."""
        created = self.client.post(
            self.designs_url,
            {"name": "D", "template": self.template.pk, "listing": self.listing.pk},
            format="json",
        )

        self.assertEqual(
            [], [e["name"] for e in created.data["elements"] if e["locked"]]
        )

    def test_save_and_reopen_preserves_the_whole_document(self):
        """The round trip that matters: what you saved is what you reopen."""
        created = self.client.post(
            self.designs_url,
            {
                "name": "Harbour View — Instagram",
                "template": self.template.pk,
                "listing": self.listing.pk,
            },
            format="json",
        )
        design = Design.objects.get()

        elements = created.data["elements"]
        for element in elements:
            if element["original_element_id"] == "headline":
                element["content"] = "Beachside living at its best"
                element["manually_overridden"] = True
            if element["original_element_id"] == "badge":
                element["style"] = {"background_color": "#0F172A", "font_size_ratio": 0.022}
            if element["original_element_id"] == "price":
                element["transform"] = {
                    "x": 0.42, "y": 0.36, "width": 0.5, "height": 0.085,
                    "rotation": 0.0, "z_index": 10,
                }
                element["style"] = {"color": "#FFFFFF", "font_weight": "800"}
                element["locked"] = True
                element["name"] = "The price"

        saved = self.client.patch(
            self.design_detail_url(design), {"elements": elements}, format="json"
        )
        self.assertEqual(saved.status_code, 200, saved.data)

        reopened = self.client.get(self.design_detail_url(design))

        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(reopened.data["name"], "Harbour View — Instagram")
        self.assertEqual(reopened.data["elements"], saved.data["elements"])

        by_original = {e["original_element_id"]: e for e in reopened.data["elements"]}
        self.assertEqual(
            by_original["headline"]["content"], "Beachside living at its best"
        )
        self.assertEqual(by_original["badge"]["style"]["background_color"], "#0F172A")
        self.assertEqual(by_original["price"]["transform"]["x"], 0.42)
        # A user-set lock is part of the document and survives the round trip;
        # it is the only thing that restricts editing, so losing it would mean
        # losing the one guard there is.
        self.assertTrue(by_original["price"]["locked"])
        self.assertEqual(by_original["price"]["name"], "The price")

    def _open_template(self, **extra):
        """Open the template the way every screen in the app opens one."""
        payload = {"name": "Harbour View", "template": self.template.pk}
        payload.update(extra)
        return self.client.post(self.designs_url, payload, format="json")

    def test_opening_the_same_template_twice_resumes_one_design(self):
        """The complaint, as a test.

        Opening a template used to POST a new design every time, so an agent
        who came back to "Just Listed" on three days had three near-identical
        rows in their designs panel and no way to tell which held their edits.
        """
        first = self._open_template()
        second = self._open_template()

        self.assertEqual(first.status_code, 201, first.data)
        # 200, not 201: nothing was created the second time, and saying
        # otherwise would make the status a lie.
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(Design.objects.count(), 1)

    def test_resuming_returns_the_edits_rather_than_a_clean_copy(self):
        """Resuming has to mean *your* canvas, not a fresh one under the old id.

        This is the half that makes the fix worth anything: an agent who edits,
        saves, leaves and clicks the template again is asking to carry on.
        """
        created = self._open_template()
        design = Design.objects.get()

        elements = created.data["elements"]
        for element in elements:
            if element["original_element_id"] == "headline":
                element["content"] = "Beachside living at its best"
                element["manually_overridden"] = True
        self.client.patch(
            self.design_detail_url(design), {"elements": elements}, format="json"
        )

        reopened = self._open_template()

        self.assertEqual(Design.objects.count(), 1)
        by_original = {
            e["original_element_id"]: e for e in reopened.data["elements"]
        }
        self.assertEqual(
            by_original["headline"]["content"], "Beachside living at its best"
        )

    def test_fresh_starts_a_second_design_on_purpose(self):
        """Two flyers from one template for two properties is a real thing.

        So the rule is a default, not a cage — "Start a fresh copy" sets this.
        """
        first = self._open_template()
        second = self._open_template(fresh=True)

        self.assertEqual(second.status_code, 201, second.data)
        self.assertNotEqual(first.data["id"], second.data["id"])
        self.assertEqual(Design.objects.count(), 2)

    def test_another_agent_gets_their_own_design_from_the_same_template(self):
        """The rule is per agent. A shared library template is opened by
        everybody, and resuming a colleague's design would be a data leak
        rather than a convenience."""
        mine = self._open_template()

        colleague, _profile = self.make_agent_in(self.acme, "b@example.com")
        self.authenticate_as(colleague)
        theirs = self._open_template()

        self.assertEqual(theirs.status_code, 201, theirs.data)
        self.assertNotEqual(mine.data["id"], theirs.data["id"])
        self.assertEqual(Design.objects.count(), 2)

    def test_reopening_does_not_disturb_the_listing_already_attached(self):
        """A resumed design keeps the property the agent chose for it.

        The editor sends a listing when it switches template, and letting that
        overwrite one already on the design would silently re-point a finished
        flyer at a different house.
        """
        first = self._open_template(listing=self.listing.pk)
        other = self.make_verified_listing(
            self.profile, self.agent, address="9 Other Street"
        )

        second = self._open_template(listing=other.pk)

        self.assertEqual(second.data["id"], first.data["id"])
        self.assertEqual(second.data["listing"], self.listing.pk)

    def test_reopening_resolves_content_against_the_listing(self):
        design = self.make_design(self.template, self.profile, self.listing)
        headline = self.element_of(design, "headline")
        headline["content"] = "Custom headline"
        headline["manually_overridden"] = True
        design.save(update_fields=["elements"])

        response = self.client.get(self.design_action_url(design, "resolved"))

        self.assertEqual(response.status_code, 200)
        by_key = {
            element["original_element_id"]: element
            for element in response.data["elements"]
        }

        # The agent's own words win, and the payload says why: still bound to
        # the address, but flagged, so the panel can offer to sync it back.
        self.assertEqual(by_key["headline"]["resolved_content"], "Custom headline")
        self.assertTrue(by_key["headline"]["manually_overridden"])
        self.assertEqual(by_key["headline"]["bound_to"], "address")
        self.assertEqual(by_key["headline"]["bound_value"], self.listing.full_address)

        # ...and everything else resolves from the listing and brokerage.
        self.assertEqual(by_key["price"]["resolved_content"], "$1,850,000")
        # Nothing arrives locked, including what used to be the locked tier.
        self.assertFalse(by_key["disclaimer"]["locked"])

    def test_resolved_view_reflects_the_requested_dimension(self):
        design = self.make_design(self.template, self.profile, self.listing)

        response = self.client.get(
            self.design_action_url(design, "resolved"), {"dimension": "instagram_story"}
        )

        self.assertEqual(response.data["width"], 1080)
        self.assertEqual(response.data["height"], 1920)

    def test_rename(self):
        design = self.make_design(self.template, self.profile, self.listing)

        response = self.client.post(
            self.design_action_url(design, "rename"), {"name": "Renamed"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        design.refresh_from_db()
        self.assertEqual(design.name, "Renamed")

    def test_duplicate_copies_the_document_but_not_the_exports(self):
        design = self.make_design(self.template, self.profile, self.listing)
        self.element_of(design, "headline")["content"] = "Original"
        design.save(update_fields=["elements"])

        response = self.client.post(
            self.design_action_url(design, "duplicate"), {}, format="json"
        )

        self.assertEqual(response.status_code, 201)
        copy = Design.objects.get(pk=response.data["id"])
        self.assertNotEqual(copy.pk, design.pk)
        self.assertEqual(copy.name, "Test Design (copy)")
        self.assertEqual(self.element_of(copy, "headline")["content"], "Original")
        self.assertEqual(copy.exports.count(), 0)

    def test_duplicate_accepts_a_name(self):
        design = self.make_design(self.template, self.profile, self.listing)

        response = self.client.post(
            self.design_action_url(design, "duplicate"),
            {"name": "Story version"},
            format="json",
        )

        self.assertEqual(response.data["name"], "Story version")

    def test_editing_a_copy_does_not_touch_the_original(self):
        design = self.make_design(self.template, self.profile, self.listing)
        self.element_of(design, "headline")["content"] = "A"
        design.save(update_fields=["elements"])

        copy = Design.objects.get(
            pk=self.client.post(
                self.design_action_url(design, "duplicate"), {}, format="json"
            ).data["id"]
        )
        elements = list(copy.elements)
        for element in elements:
            if element["original_element_id"] == "headline":
                element["content"] = "B"

        self.client.patch(
            self.design_detail_url(copy), {"elements": elements}, format="json"
        )

        design.refresh_from_db()
        self.assertEqual(self.element_of(design, "headline")["content"], "A")

    def test_delete(self):
        design = self.make_design(self.template, self.profile, self.listing)

        response = self.client.delete(self.design_detail_url(design))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Design.objects.filter(pk=design.pk).exists())

    def test_a_design_needs_no_listing(self):
        """Agent-introduction, market-update and seasonal templates have no
        property. A listing-led template still demands one — see
        test_calendar.DesignWithoutListingTests."""
        agent_template = self.make_template(
            name="About me", slug="about-me", category="agent_introduction"
        )

        response = self.client.post(
            self.designs_url,
            {"name": "About me", "template": agent_template.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(Design.objects.get().listing)


class DesignListingGateTests(TemplateAPITestCase):
    """A design may only be built on a verified listing."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.authenticate_as(self.agent)

    def test_unverified_listing_is_refused(self):
        unverified = self.make_listing(self.profile)

        response = self.client.post(
            self.designs_url,
            {"name": "Too early", "template": self.template.pk, "listing": unverified.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("listing", response.data)
        self.assertIn("verified", str(response.data["listing"][0]).lower())

    def test_verified_listing_is_accepted(self):
        verified = self.make_verified_listing(self.profile, self.agent)

        response = self.client.post(
            self.designs_url,
            {"name": "Ready", "template": self.template.pk, "listing": verified.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)

    def test_another_agents_listing_is_refused(self):
        other_agent, other_profile = self.make_agent_in(self.acme, "b@example.com")
        theirs = self.make_verified_listing(other_profile, other_agent)

        response = self.client.post(
            self.designs_url,
            {"name": "Not mine", "template": self.template.pk, "listing": theirs.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class ImportedTemplateNeedsNoListingTests(TemplateAPITestCase):
    """An agent's own imported artwork is theirs to customise immediately.

    The library's New Listing card is a shell that says nothing without a
    property. An imported one is a finished page — the extractor kept its
    wording and its pictures — so the same category must not gate it behind
    verifying an unrelated listing.
    """

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        # Same category, the only difference is who owns it.
        self.library = self.make_template()
        self.imported = self.make_template(
            name="My flyer",
            slug="my-flyer",
            category=TemplateCategory.NEW_LISTING,
            owner=self.profile,
        )
        self.authenticate_as(self.agent)

    def test_imported_template_reports_that_it_needs_no_listing(self):
        response = self.client.get(self.template_detail_url(self.imported))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_imported"])
        self.assertFalse(response.data["requires_listing"])

    def test_library_template_of_the_same_category_still_needs_one(self):
        """The exemption is about ownership, not about relaxing the category."""
        response = self.client.get(self.template_detail_url(self.library))

        self.assertFalse(response.data["is_imported"])
        self.assertTrue(response.data["requires_listing"])

    def test_a_design_opens_on_an_imported_template_with_no_listing(self):
        response = self.client.post(
            self.designs_url,
            {"name": "Mine to edit", "template": self.imported.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(Design.objects.get().listing)

    def test_the_library_equivalent_also_opens_without_one(self):
        """`requires_listing` no longer gates creation for anything.

        It still describes the template truthfully, and the library still uses
        it — but what it governs now is whether the export can go out empty,
        not whether the design may be started.
        """
        response = self.client.post(
            self.designs_url,
            {"name": "Needs a property", "template": self.library.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(Design.objects.get().listing)

    def test_an_unverified_listing_is_still_refused_on_an_imported_template(self):
        """Not needing a listing is not the same as accepting an unreviewed one.

        The verification gate exists so unreviewed property data never reaches
        marketing material. Waiving the requirement must not waive that.
        """
        unverified = self.make_listing(self.profile)

        response = self.client.post(
            self.designs_url,
            {"name": "Too early", "template": self.imported.pk, "listing": unverified.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("verified", str(response.data["listing"][0]).lower())

    def test_a_verified_listing_can_still_be_attached(self):
        verified = self.make_verified_listing(self.profile, self.agent)

        response = self.client.post(
            self.designs_url,
            {"name": "With a property", "template": self.imported.pk, "listing": verified.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Design.objects.get().listing, verified)

    def test_the_model_agrees_with_the_serializer(self):
        """`Design.clean` carries the same rule, so a shell cannot diverge."""
        design = Design(
            name="From the shell", template=self.imported, agent=self.profile
        )
        design.elements = design.ensure_document()

        design.full_clean(exclude=["elements"])  # must not raise


class DesignScopingTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.nehrux = self.make_nehrux_admin()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)
        self.rival = self.make_brokerage("Rival Realty")

        self.agent_a, self.profile_a = self.make_agent_in(self.acme, "a@example.com")
        self.agent_b, self.profile_b = self.make_agent_in(self.acme, "b@example.com")
        self.outsider, self.profile_out = self.make_agent_in(self.rival, "c@example.com")

        self.template = self.make_template()
        self.design_a = self.make_design(self.template, self.profile_a, name="A design")
        self.design_b = self.make_design(self.template, self.profile_b, name="B design")
        self.design_out = self.make_design(self.template, self.profile_out, name="Rival")

    def test_agent_sees_only_their_own_designs(self):
        self.authenticate_as(self.agent_a)

        response = self.client.get(self.designs_url)

        self.assertEqual([row["name"] for row in response.data["results"]], ["A design"])

    def test_agent_cannot_open_a_colleagues_design(self):
        self.authenticate_as(self.agent_a)

        self.assertEqual(
            self.client.get(self.design_detail_url(self.design_b)).status_code, 404
        )

    def test_agent_cannot_edit_or_delete_a_colleagues_design(self):
        self.authenticate_as(self.agent_a)
        url = self.design_detail_url(self.design_b)

        self.assertEqual(
            self.client.patch(url, {"name": "Hijacked"}, format="json").status_code, 404
        )
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_agent_cannot_duplicate_a_colleagues_design(self):
        self.authenticate_as(self.agent_a)

        response = self.client.post(
            self.design_action_url(self.design_b, "duplicate"), {}, format="json"
        )

        self.assertEqual(response.status_code, 404)

    def test_brokerage_admin_sees_the_brokerages_designs(self):
        self.authenticate_as(self.broker_admin)

        response = self.client.get(self.designs_url)

        self.assertEqual(
            sorted(row["name"] for row in response.data["results"]),
            ["A design", "B design"],
        )

    def test_brokerage_admin_cannot_see_another_brokerages_design(self):
        self.authenticate_as(self.broker_admin)

        self.assertEqual(
            self.client.get(self.design_detail_url(self.design_out)).status_code, 404
        )

    def test_nehrux_admin_sees_everything(self):
        self.authenticate_as(self.nehrux)

        self.assertEqual(self.client.get(self.designs_url).data["count"], 3)

    def test_unauthenticated_access_is_rejected(self):
        self.assertEqual(self.client.get(self.designs_url).status_code, 401)

    def test_mine_narrows_an_admin_to_designs_they_authored(self):
        """`?mine=1` asks a narrower question than the permission scope.

        A brokerage admin may legitimately read the whole firm's designs, which
        is the right answer for an audit and the wrong one for a screen called
        "my designs". Without this the admin's designs panel fills with their
        agents' work, and the template gallery offers to resume it.
        """
        self.authenticate_as(self.broker_admin)

        response = self.client.get(self.designs_url, {"mine": "1"})

        self.assertEqual(response.data["count"], 0)

    def test_mine_leaves_an_agents_own_list_alone(self):
        self.authenticate_as(self.agent_a)

        response = self.client.get(self.designs_url, {"mine": "1"})

        self.assertEqual([row["name"] for row in response.data["results"]], ["A design"])

    def test_mine_combines_with_the_template_filter(self):
        """The exact query behind "have I already started one of these?".

        The template gallery asks this before offering to create anything, so
        that opening the same template twice resumes one design rather than
        leaving a second one behind.
        """
        self.authenticate_as(self.agent_a)
        other_template = self.make_template(slug="other-template")
        self.make_design(other_template, self.profile_a, name="Different template")

        response = self.client.get(
            self.designs_url, {"mine": "1", "template": self.template.pk}
        )

        self.assertEqual([row["name"] for row in response.data["results"]], ["A design"])


class TemplateLibraryTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")

        self.bold = self.make_template(name="Bold one", slug="bold-one")
        self.luxury = self.make_template(
            name="Luxury one", slug="luxury-one", style="luxury"
        )
        self.sold = self.make_template(
            name="Sold one", slug="sold-one", category="just_sold", style="classic"
        )
        self.authenticate_as(self.agent)

    def test_library_lists_active_templates(self):
        response = self.client.get(self.templates_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)

    def test_filter_by_category(self):
        response = self.client.get(self.templates_url, {"category": "just_sold"})

        self.assertEqual([row["name"] for row in response.data["results"]], ["Sold one"])

    def test_filter_by_style(self):
        response = self.client.get(self.templates_url, {"style": "luxury"})

        self.assertEqual([row["name"] for row in response.data["results"]], ["Luxury one"])

    def test_filter_by_category_and_style_together(self):
        response = self.client.get(
            self.templates_url, {"category": "new_listing", "style": "bold"}
        )

        self.assertEqual([row["name"] for row in response.data["results"]], ["Bold one"])

    def test_inactive_templates_are_hidden(self):
        self.sold.is_active = False
        self.sold.save()

        response = self.client.get(self.templates_url)

        self.assertEqual(response.data["count"], 2)

    def test_facets_report_counts_for_the_filter_ui(self):
        response = self.client.get(self.template_facets_url)

        categories = {row["value"]: row["count"] for row in response.data["categories"]}
        styles = {row["value"]: row["count"] for row in response.data["styles"]}

        self.assertEqual(categories["new_listing"], 2)
        self.assertEqual(categories["just_sold"], 1)
        self.assertEqual(styles["bold"], 1)
        # Every category is offered, including the seasonal ones added for the
        # content calendar — the facet list is the full vocabulary, with counts.
        self.assertEqual(
            len(response.data["categories"]), len(TemplateCategory.choices)
        )
        self.assertEqual(len(response.data["styles"]), 6)
        self.assertEqual(categories["diwali"], 0)

    def test_templates_are_read_only_over_the_api(self):
        """Templates are product content, authored in the admin."""
        response = self.client.post(
            self.templates_url,
            {"name": "Mine", "slug": "mine", "category": "new_listing", "style": "bold"},
            format="json",
        )

        self.assertEqual(response.status_code, 405)


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class UploadImageTests(TemplateAPITestCase):
    """The 'upload a new one' half of image replace — a bare storage write
    the caller then PATCHes onto whichever element they mean it for."""

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        self.design = self.make_design(self.template, self.profile, self.listing)
        self.authenticate_as(self.agent)

    def _upload(self, **kwargs):
        return self.client.post(
            self.design_action_url(self.design, "upload-image"),
            {"image": make_image_file("feature.png", **kwargs)},
            format="multipart",
        )

    def test_a_valid_image_is_accepted(self):
        response = self._upload()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn("image_key", response.data)
        self.assertIn("url", response.data)
        self.assertTrue(default_storage.exists(response.data["image_key"]))

    def test_the_returned_key_works_as_an_elements_content(self):
        """The point of the endpoint: what it hands back is immediately
        usable, not a second format the client has to translate."""
        key = self._upload().data["image_key"]
        elements = list(self.design.elements)
        for element in elements:
            if element["original_element_id"] == "hero_photo":
                element["content"] = key
                element["manually_overridden"] = True

        response = self.client.patch(
            self.design_detail_url(self.design), {"elements": elements}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        self.assertEqual(self.element_of(self.design, "hero_photo")["content"], key)

    def test_the_url_points_at_the_uploaded_key(self):
        # Not a real HTTP round trip: Django's dev-only media-serving route is
        # wired to the real MEDIA_ROOT at URLconf import time, which this
        # test's @override_settings can't reach — the same reason no other
        # test in this codebase fetches a media URL through the test client.
        # What actually matters, and is real here, is that storage has the
        # file and the URL names it.
        response = self._upload()

        self.assertIn(response.data["image_key"], response.data["url"])
        self.assertTrue(default_storage.exists(response.data["image_key"]))

    def test_uploading_requires_authentication(self):
        self.client.credentials()

        response = self._upload()

        self.assertEqual(response.status_code, 401)

    def test_another_agent_cannot_upload_to_your_design(self):
        other_agent, _ = self.make_agent_in(self.acme, "b@example.com")
        self.authenticate_as(other_agent)

        response = self._upload()

        self.assertEqual(response.status_code, 404)

    def test_a_non_image_file_is_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            self.design_action_url(self.design, "upload-image"),
            {"image": SimpleUploadedFile("note.txt", b"not an image", content_type="text/plain")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)

    def test_uploading_does_not_itself_change_the_design(self):
        """It only ever produces a key — applying it is a separate PATCH."""
        before = list(self.design.elements)

        self._upload()

        self.design.refresh_from_db()
        self.assertEqual(self.design.elements, before)


class MergeDuplicateDesignsCommandTests(TemplateAPITestCase):
    """Cleaning up the duplicates the old create rule already left behind.

    The fix in `DesignSerializer.create` only stops new ones. An agent staring
    at fourteen copies of the same flyer is not helped by that alone, which is
    what this command is for.
    """

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()

    def _merge(self, **options) -> str:
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("merge_duplicate_designs", stdout=out, stderr=out, **options)
        return out.getvalue()

    def test_dry_run_reports_but_deletes_nothing(self):
        for index in range(3):
            self.make_design(self.template, self.profile, name=f"Copy {index}")

        output = self._merge()

        self.assertIn("Dry run", output)
        self.assertIn("2 design(s) would be deleted", output)
        self.assertEqual(Design.objects.count(), 3)

    def test_apply_keeps_only_the_most_recently_edited(self):
        oldest = self.make_design(self.template, self.profile, name="Oldest")
        newest = self.make_design(self.template, self.profile, name="Newest")
        # `updated_at` is auto_now, so the second one saved is genuinely newer;
        # assert the ordering rather than trusting the write order.
        self.assertGreater(newest.updated_at, oldest.updated_at)

        self._merge(apply=True)

        self.assertEqual([d.pk for d in Design.objects.all()], [newest.pk])

    def test_another_agents_design_is_not_touched(self):
        """One shared template is opened by everybody. Folding across agents
        would delete somebody else's work."""
        _colleague, other_profile = self.make_agent_in(self.acme, "b@example.com")
        mine_old = self.make_design(self.template, self.profile, name="Mine 1")
        self.make_design(self.template, self.profile, name="Mine 2")
        theirs = self.make_design(self.template, other_profile, name="Theirs")

        self._merge(apply=True)

        surviving = set(Design.objects.values_list("pk", flat=True))
        self.assertIn(theirs.pk, surviving)
        self.assertNotIn(mine_old.pk, surviving)
        self.assertEqual(len(surviving), 2)

    def test_designs_from_different_templates_are_left_alone(self):
        other_template = self.make_template(slug="other-template")
        self.make_design(self.template, self.profile, name="A")
        self.make_design(other_template, self.profile, name="B")

        output = self._merge(apply=True)

        self.assertIn("Nothing to merge", output)
        self.assertEqual(Design.objects.count(), 2)

    def test_an_exported_design_survives_a_newer_unexported_one(self):
        """Somebody already has the PNG. Deleting it takes its exports with it,
        so the export outranks the timestamp."""
        exported = self.make_design(self.template, self.profile, name="Exported")
        exported.exports.create(
            dimension="instagram_post",
            export_format="png",
            width=1080,
            height=1080,
            bytes=1234,
            render_ms=10,
        )
        newer = self.make_design(self.template, self.profile, name="Newer draft")
        self.assertGreater(newer.updated_at, exported.updated_at)

        self._merge(apply=True)

        self.assertEqual([d.pk for d in Design.objects.all()], [exported.pk])

    def test_two_exported_designs_are_reported_and_skipped(self):
        """Two rendered designs are two real pieces of work. The command says
        so instead of picking one."""
        for name in ("First", "Second"):
            design = self.make_design(self.template, self.profile, name=name)
            design.exports.create(
                dimension="instagram_post",
                export_format="png",
                width=1080,
                height=1080,
                bytes=1234,
                render_ms=10,
            )

        output = self._merge(apply=True)

        self.assertIn("skipped", output)
        self.assertEqual(Design.objects.count(), 2)

    def test_agent_filter_limits_the_blast_radius(self):
        _colleague, other_profile = self.make_agent_in(self.acme, "b@example.com")
        self.make_design(self.template, self.profile, name="Mine 1")
        self.make_design(self.template, self.profile, name="Mine 2")
        self.make_design(self.template, other_profile, name="Theirs 1")
        self.make_design(self.template, other_profile, name="Theirs 2")

        self._merge(apply=True, agent="b@example.com")

        self.assertEqual(Design.objects.filter(agent=self.profile).count(), 2)
        self.assertEqual(Design.objects.filter(agent=other_profile).count(), 1)

    def test_exclude_spares_a_deliberate_variation(self):
        """A variation made on purpose reads exactly like an accidental copy
        from the command's point of view, so it has to be named explicitly."""
        oldest = self.make_design(self.template, self.profile, name="Oldest")
        variation = self.make_design(self.template, self.profile, name="A (variation)")
        newest = self.make_design(self.template, self.profile, name="Newest")

        self._merge(apply=True, exclude=[variation.pk])

        surviving = set(Design.objects.values_list("pk", flat=True))
        self.assertEqual(surviving, {variation.pk, newest.pk})
        self.assertNotIn(oldest.pk, surviving)
