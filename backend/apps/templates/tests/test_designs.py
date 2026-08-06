"""Design lifecycle: save, reopen, rename, duplicate, delete — and scoping."""

from __future__ import annotations

from apps.templates.models import Design, TemplateCategory
from apps.templates.tests.base import TemplateAPITestCase


class DesignRoundTripTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        self.authenticate_as(self.agent)

    def test_save_and_reopen_preserves_every_override(self):
        """The round trip that matters: what you saved is what you reopen."""
        overrides = {
            "headline": {"text": "Beachside living at its best"},
            "badge": {"background_color": "#0F172A", "font_size_ratio": 0.022},
            "price": {
                "geometry": {"x": 0.42, "y": 0.36, "width": 0.5, "height": 0.085},
                "color": "#FFFFFF",
                "font_weight": "800",
            },
        }

        created = self.client.post(
            self.designs_url,
            {
                "name": "Harbour View — Instagram",
                "template": self.template.pk,
                "listing": self.listing.pk,
                "overrides": overrides,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)

        reopened = self.client.get(self.design_detail_url(Design.objects.get()))

        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(reopened.data["name"], "Harbour View — Instagram")
        self.assertEqual(reopened.data["overrides"], overrides)
        self.assertEqual(reopened.data["template"], self.template.pk)
        self.assertEqual(reopened.data["listing"], self.listing.pk)

    def test_reopening_resolves_content_against_the_listing(self):
        design = self.make_design(
            self.template,
            self.profile,
            self.listing,
            overrides={"headline": {"text": "Custom headline"}},
        )

        response = self.client.get(self.design_action_url(design, "resolved"))

        self.assertEqual(response.status_code, 200)
        by_key = {element["key"]: element for element in response.data["elements"]}

        # Overridden content wins...
        self.assertEqual(by_key["headline"]["content"], "Custom headline")
        self.assertEqual(by_key["headline"]["overridden_fields"], ["text"])
        # ...and everything else resolves from the listing and brokerage.
        self.assertEqual(by_key["price"]["content"], "$1,850,000")
        self.assertEqual(by_key["disclaimer"]["permission"], "locked")

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

    def test_duplicate_copies_overrides_but_not_exports(self):
        design = self.make_design(
            self.template,
            self.profile,
            self.listing,
            overrides={"headline": {"text": "Original"}},
        )

        response = self.client.post(
            self.design_action_url(design, "duplicate"), {}, format="json"
        )

        self.assertEqual(response.status_code, 201)
        copy = Design.objects.get(pk=response.data["id"])
        self.assertNotEqual(copy.pk, design.pk)
        self.assertEqual(copy.name, "Test Design (copy)")
        self.assertEqual(copy.overrides, design.overrides)
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
        design = self.make_design(
            self.template, self.profile, self.listing, overrides={"headline": {"text": "A"}}
        )
        copy_id = self.client.post(
            self.design_action_url(design, "duplicate"), {}, format="json"
        ).data["id"]

        self.client.patch(
            self.design_detail_url(Design.objects.get(pk=copy_id)),
            {"overrides": {"headline": {"text": "B"}}},
            format="json",
        )

        design.refresh_from_db()
        self.assertEqual(design.overrides["headline"]["text"], "A")

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
