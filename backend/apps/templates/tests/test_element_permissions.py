"""Element permission enforcement — the security core of the template system.

The premise of every test here is that the client is hostile. The editing UI
disables the controls an agent may not use, but nothing stops someone POSTing
straight to the API, so the rules are re-derived from the template on every
write.

Each permission level gets the same treatment: prove what it allows, and prove
what it refuses.
"""

from __future__ import annotations

from apps.templates.models import Design
from apps.templates.tests.base import TemplateAPITestCase


class LockedElementTests(TemplateAPITestCase):
    """Locked elements reject everything, via any route."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        self.authenticate_as(self.agent)

    def test_editing_a_locked_element_is_rejected_on_create(self):
        response = self.client.post(
            self.designs_url,
            {
                "name": "Attempt",
                "template": self.template.pk,
                "listing": self.listing.pk,
                "overrides": {"disclaimer": {"text": "No disclaimer needed"}},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("disclaimer", response.data)
        self.assertIn("locked", str(response.data["disclaimer"][0]).lower())
        self.assertFalse(Design.objects.exists())

    def test_editing_a_locked_element_is_rejected_on_update(self):
        design = self.make_design(self.template, self.profile, self.listing)

        response = self.client.patch(
            self.design_detail_url(design),
            {"overrides": {"disclaimer": {"text": "Rewritten"}}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        design.refresh_from_db()
        self.assertEqual(design.overrides, {})

    def test_styling_a_locked_element_is_rejected(self):
        design = self.make_design(self.template, self.profile, self.listing)

        response = self.client.patch(
            self.design_detail_url(design),
            {"overrides": {"disclaimer": {"color": "#FFFFFF"}}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_moving_a_locked_element_is_rejected(self):
        design = self.make_design(self.template, self.profile, self.listing)

        response = self.client.patch(
            self.design_detail_url(design),
            {
                "overrides": {
                    "disclaimer": {"geometry": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.1}}
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_hiding_a_locked_element_is_rejected(self):
        """The obvious workaround: if you cannot reword it, delete it."""
        design = self.make_design(self.template, self.profile, self.listing)

        response = self.client.patch(
            self.design_detail_url(design),
            {"overrides": {"disclaimer": {"hidden": True}}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_even_an_empty_override_on_a_locked_element_is_rejected(self):
        """A client that thinks it can edit this should be told it cannot."""
        design = self.make_design(self.template, self.profile, self.listing)

        response = self.client.patch(
            self.design_detail_url(design),
            {"overrides": {"disclaimer": {}}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class ContentOnlyElementTests(TemplateAPITestCase):
    """Content may be swapped; layout and styling may not."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        self.design = self.make_design(self.template, self.profile, self.listing)
        self.authenticate_as(self.agent)

    def _patch(self, overrides):
        return self.client.patch(
            self.design_detail_url(self.design), {"overrides": overrides}, format="json"
        )

    def test_text_can_be_replaced(self):
        response = self._patch({"headline": {"text": "Stunning family home"}})

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        self.assertEqual(self.design.overrides["headline"]["text"], "Stunning family home")

    def test_text_length_limit_is_enforced(self):
        response = self._patch({"headline": {"text": "x" * 61}})

        self.assertEqual(response.status_code, 400)
        self.assertIn("headline", response.data)

    def test_colour_change_is_rejected(self):
        response = self._patch({"headline": {"color": "#FF0000"}})

        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot be changed", str(response.data["headline"][0]))

    def test_font_size_change_is_rejected(self):
        response = self._patch({"headline": {"font_size_ratio": 0.08}})

        self.assertEqual(response.status_code, 400)

    def test_moving_is_rejected(self):
        response = self._patch(
            {"headline": {"geometry": {"x": 0.2, "y": 0.2, "width": 0.5, "height": 0.1}}}
        )

        self.assertEqual(response.status_code, 400)

    def test_a_required_element_cannot_be_hidden(self):
        response = self._patch({"hero_photo": {"hidden": True}})

        self.assertEqual(response.status_code, 400)
        self.assertIn("required", str(response.data["hero_photo"][0]).lower())

    def test_text_on_an_image_element_is_rejected(self):
        response = self._patch({"hero_photo": {"text": "not an image"}})

        self.assertEqual(response.status_code, 400)

    def test_image_override_must_be_a_key_not_a_url(self):
        """Accepting a URL would let a design make the renderer fetch it."""
        response = self._patch({"hero_photo": {"image_key": "https://evil.test/x.png"}})

        self.assertEqual(response.status_code, 400)
        self.assertIn("not a URL", str(response.data["hero_photo"][0]))

    def test_image_key_cannot_traverse(self):
        response = self._patch({"hero_photo": {"image_key": "../../etc/passwd"}})

        self.assertEqual(response.status_code, 400)


class StyledElementTests(TemplateAPITestCase):
    """Colour and size, but only within the template's allowlist."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        self.design = self.make_design(self.template, self.profile, self.listing)
        self.authenticate_as(self.agent)

    def _patch(self, overrides):
        return self.client.patch(
            self.design_detail_url(self.design), {"overrides": overrides}, format="json"
        )

    def test_allowed_colour_is_accepted(self):
        response = self._patch({"badge": {"background_color": "#C2874A"}})

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        self.assertEqual(self.design.overrides["badge"]["background_color"], "#C2874A")

    def test_colour_outside_the_allowlist_is_rejected(self):
        response = self._patch({"badge": {"background_color": "#FF00FF"}})

        self.assertEqual(response.status_code, 400)
        self.assertIn("badge", response.data)

    def test_colour_matching_is_case_insensitive(self):
        response = self._patch({"badge": {"background_color": "#c2874a"}})

        self.assertEqual(response.status_code, 200, response.data)

    def test_font_size_within_bounds_is_accepted(self):
        response = self._patch({"badge": {"font_size_ratio": 0.02}})

        self.assertEqual(response.status_code, 200, response.data)

    def test_font_size_above_the_maximum_is_rejected(self):
        response = self._patch({"badge": {"font_size_ratio": 0.5}})

        self.assertEqual(response.status_code, 400)

    def test_font_size_below_the_minimum_is_rejected(self):
        response = self._patch({"badge": {"font_size_ratio": 0.001}})

        self.assertEqual(response.status_code, 400)

    def test_moving_a_styled_element_is_rejected(self):
        """Styled is not free: colour yes, position no."""
        response = self._patch(
            {"badge": {"geometry": {"x": 0.5, "y": 0.5, "width": 0.3, "height": 0.05}}}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot be changed", str(response.data["badge"][0]))

    def test_malformed_colour_is_rejected(self):
        response = self._patch({"badge": {"background_color": "cornflowerblue"}})

        self.assertEqual(response.status_code, 400)


class FreeElementTests(TemplateAPITestCase):
    """Free means free *within declared bounds*, not anywhere."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        self.design = self.make_design(self.template, self.profile, self.listing)
        self.authenticate_as(self.agent)

    def _patch(self, overrides):
        return self.client.patch(
            self.design_detail_url(self.design), {"overrides": overrides}, format="json"
        )

    def test_moving_within_bounds_is_accepted(self):
        response = self._patch(
            {"price": {"geometry": {"x": 0.5, "y": 0.35, "width": 0.4, "height": 0.08}}}
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        self.assertEqual(self.design.overrides["price"]["geometry"]["x"], 0.5)

    def test_moving_outside_bounds_is_rejected(self):
        response = self._patch(
            {"price": {"geometry": {"x": 0.5, "y": 0.80, "width": 0.4, "height": 0.08}}}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("inside the area", str(response.data["price"][0]))

    def test_resizing_past_the_right_edge_of_bounds_is_rejected(self):
        response = self._patch(
            {"price": {"geometry": {"x": 0.8, "y": 0.35, "width": 0.4, "height": 0.08}}}
        )

        self.assertEqual(response.status_code, 400)

    def test_geometry_outside_the_canvas_is_rejected(self):
        response = self._patch(
            {"price": {"geometry": {"x": -0.2, "y": 0.35, "width": 0.4, "height": 0.08}}}
        )

        self.assertEqual(response.status_code, 400)

    def test_zero_size_is_rejected(self):
        response = self._patch(
            {"price": {"geometry": {"x": 0.1, "y": 0.35, "width": 0.0, "height": 0.08}}}
        )

        self.assertEqual(response.status_code, 400)

    def test_incomplete_geometry_is_rejected(self):
        response = self._patch({"price": {"geometry": {"x": 0.1, "y": 0.35}}})

        self.assertEqual(response.status_code, 400)
        self.assertIn("missing", str(response.data["price"][0]))

    def test_restyling_within_the_allowlist_is_accepted(self):
        response = self._patch(
            {"price": {"color": "#0F172A", "font_size_ratio": 0.05, "font_weight": "800"}}
        )

        self.assertEqual(response.status_code, 200, response.data)

    def test_colour_outside_the_allowlist_is_still_rejected(self):
        """Free elements still obey their constraints."""
        response = self._patch({"price": {"color": "#FF00FF"}})

        self.assertEqual(response.status_code, 400)


class OverrideShapeTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        self.design = self.make_design(self.template, self.profile, self.listing)
        self.authenticate_as(self.agent)

    def _patch(self, overrides):
        return self.client.patch(
            self.design_detail_url(self.design), {"overrides": overrides}, format="json"
        )

    def test_unknown_element_key_is_rejected(self):
        """Silently ignoring it would let a client believe an edit worked."""
        response = self._patch({"no_such_element": {"text": "hello"}})

        self.assertEqual(response.status_code, 400)
        self.assertIn("no_such_element", response.data)

    def test_unknown_field_is_rejected(self):
        response = self._patch({"price": {"rotation": 45}})

        self.assertEqual(response.status_code, 400)

    def test_overrides_must_be_an_object(self):
        response = self._patch(["not", "an", "object"])

        self.assertEqual(response.status_code, 400)

    def test_valid_multi_element_override_is_stored_intact(self):
        response = self._patch(
            {
                "headline": {"text": "Beachside living"},
                "badge": {"background_color": "#0F172A"},
                "price": {"geometry": {"x": 0.1, "y": 0.35, "width": 0.5, "height": 0.08}},
            }
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        self.assertEqual(set(self.design.overrides), {"headline", "badge", "price"})

    def test_one_bad_element_rejects_the_whole_payload(self):
        """No partial application: the client's model must stay in sync."""
        response = self._patch(
            {
                "headline": {"text": "This part is fine"},
                "disclaimer": {"text": "This part is not"},
            }
        )

        self.assertEqual(response.status_code, 400)
        self.design.refresh_from_db()
        self.assertEqual(self.design.overrides, {})

    def test_the_api_publishes_what_each_element_allows(self):
        """The UI is told the rules rather than left to infer them."""
        response = self.client.get(self.template_detail_url(self.template))

        self.assertEqual(response.status_code, 200)
        by_key = {element["key"]: element for element in response.data["elements"]}

        self.assertEqual(by_key["disclaimer"]["editable_fields"], [])
        self.assertIn("text", by_key["headline"]["editable_fields"])
        self.assertNotIn("geometry", by_key["headline"]["editable_fields"])
        self.assertIn("background_color", by_key["badge"]["editable_fields"])
        self.assertNotIn("geometry", by_key["badge"]["editable_fields"])
        self.assertIn("geometry", by_key["price"]["editable_fields"])

        self.assertEqual(
            response.data["permission_map"],
            {
                "disclaimer": "locked",
                "headline": "content_only",
                "hero_photo": "content_only",
                "badge": "styled",
                "price": "free",
            },
        )
