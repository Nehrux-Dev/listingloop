"""The design document: the copy, the bindings, and what still says no.

This is the test module for the model described in ``document.py``. It is
organised around the three things that changed, in the order they matter:

  1. Opening a template copies it. Nothing is shared, nothing is locked.
  2. A binding populates and re-syncs content. It does not restrict anything.
  3. The server still refuses values that would compromise the renderer —
     which was never what the permission tiers were for.
"""

from __future__ import annotations

from apps.templates.dimensions import get_dimension
from apps.templates.document import (
    BLANK_ELEMENTS,
    ELEMENT_TYPES,
    MAX_ELEMENTS,
    PROPERTY_FIELDS_BY_NAME,
    DocumentValidationError,
    duplicate_element,
    element_from_template,
    elements_from_template,
    new_element,
    normalise_z_order,
    sorted_for_render,
    validate_document,
)
from apps.templates.html_builder import build_html
from apps.templates.models import Design, ElementType, TemplateElement
from apps.templates.render_context import build_context
from apps.templates.tests.base import TemplateAPITestCase


class DocumentTestCase(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.acme.required_disclaimer = "A guide only."
        self.acme.save()
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        self.design = self.make_design(self.template, self.profile, self.listing)
        self.authenticate_as(self.agent)

    def document(self):
        return list(self.design.elements)

    def save(self, elements):
        return self.client.patch(
            self.design_detail_url(self.design), {"elements": elements}, format="json"
        )


# ===========================================================================
# 1. The copy
# ===========================================================================


class TemplateToDesignCopyTests(DocumentTestCase):
    def test_every_template_element_is_copied(self):
        self.assertEqual(len(self.design.elements), self.template.elements.count())

    def test_nothing_is_locked(self):
        """The headline change. A template has no way to ship an element the
        agent cannot touch, because the tier that expressed that is gone."""
        self.assertEqual([], [e for e in self.design.elements if e["locked"]])

    def test_every_element_is_visible_and_named(self):
        for element in self.design.elements:
            self.assertTrue(element["visible"])
            self.assertTrue(element["name"], f"{element['id']} has no name")

    def test_each_element_points_back_at_its_template_original(self):
        """What makes "reset this element" possible after any amount of
        renaming, moving and duplicating."""
        self.assertEqual(
            {e["original_element_id"] for e in self.design.elements},
            set(self.template.elements.values_list("key", flat=True)),
        )

    def test_every_template_element_type_maps_to_a_document_type(self):
        for value, _label in ElementType.choices:
            with self.subTest(element_type=value):
                template_element = TemplateElement(
                    template=self.template,
                    key=f"probe_{value}",
                    element_type=value,
                    geometry={"x": 0, "y": 0, "width": 0.1, "height": 0.1},
                )
                self.assertIn(
                    element_from_template(template_element)["type"], ELEMENT_TYPES
                )

    def test_editing_a_design_never_writes_to_the_template(self):
        before = [
            (e.key, e.geometry, e.style_properties, e.default_content, e.z_index)
            for e in self.template.elements.all()
        ]
        elements = self.document()
        for element in elements:
            element["content"] = "rewritten"
            element["transform"] = {**element["transform"], "x": 0.9}
            element["style"] = {"color": "#000000"}

        self.assertEqual(self.save(elements).status_code, 200)

        self.template.refresh_from_db()
        self.assertEqual(
            before,
            [
                (e.key, e.geometry, e.style_properties, e.default_content, e.z_index)
                for e in self.template.elements.all()
            ],
        )

    def test_the_template_endpoint_is_read_only(self):
        """The other half of the same promise, checked at the door.

        DELETE answers 403 rather than 405, and the difference is real: the
        method exists now, for the platform owner removing something from the
        shared library (see RemoveFromLibraryTests). An agent is refused by
        permission instead of by the method not being there at all. Editing a
        template is still nobody's — 405 for everyone, whatever their role.
        """
        url = self.template_detail_url(self.template)
        for method, payload in (
            (self.client.put, {"name": "Hijacked"}),
            (self.client.patch, {"name": "Hijacked"}),
        ):
            with self.subTest(method=method.__name__):
                self.assertEqual(method(url, payload, format="json").status_code, 405)

        self.assertEqual(self.client.delete(url).status_code, 403)

        self.template.refresh_from_db()
        self.assertEqual(self.template.name, "Test Template")
        self.assertTrue(self.template.is_active)

    def test_a_design_made_outside_the_api_still_gets_a_document(self):
        """The admin, a shell, a fixture. An empty canvas is not a state a
        user should ever be shown, so it is filled in on read."""
        bare = Design.objects.create(
            name="Bare", template=self.template, agent=self.profile, listing=self.listing
        )
        self.assertEqual(bare.elements, [])

        self.assertEqual(len(bare.ensure_document()), self.template.elements.count())


class ResetTests(DocumentTestCase):
    def test_reset_element_restores_one_element(self):
        element = self.element_of(self.design, "price")
        element.update({"content": "wrong", "name": "Renamed", "locked": True})
        element["transform"] = {**element["transform"], "x": 0.99, "rotation": 45.0}
        element["style"] = {"color": "#FF0000"}
        self.design.save(update_fields=["elements"])

        response = self.client.post(
            self.design_element_url(self.design, element["id"], "reset-element")
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        restored = self.element_of(self.design, "price")
        self.assertEqual(restored["name"], "Price")
        self.assertEqual(restored["transform"]["x"], 0.06)
        self.assertEqual(restored["transform"]["rotation"], 0.0)
        self.assertEqual(restored["style"]["color"], "#FFFFFF")
        self.assertFalse(restored["locked"])

    def test_reset_element_keeps_the_elements_id(self):
        """A new id would orphan the current selection and every undo entry
        that refers to this element."""
        element_id = self.element_of(self.design, "price")["id"]

        self.client.post(
            self.design_element_url(self.design, element_id, "reset-element")
        )

        self.design.refresh_from_db()
        self.assertEqual(self.element_of(self.design, "price")["id"], element_id)

    def test_reset_element_leaves_the_other_elements_alone(self):
        headline = self.element_of(self.design, "headline")
        headline["content"] = "Kept"
        price_id = self.element_of(self.design, "price")["id"]
        self.design.save(update_fields=["elements"])

        self.client.post(
            self.design_element_url(self.design, price_id, "reset-element")
        )

        self.design.refresh_from_db()
        self.assertEqual(self.element_of(self.design, "headline")["content"], "Kept")

    def test_reset_element_works_after_the_element_has_been_reordered(self):
        """Matched by ``original_element_id``, not by position — otherwise the
        feature would break the first time someone used the layers panel."""
        elements = self.document()
        elements.reverse()
        for index, element in enumerate(elements):
            element["transform"]["z_index"] = index
        self.design.elements = elements
        self.design.save(update_fields=["elements"])
        price_id = self.element_of(self.design, "price")["id"]

        response = self.client.post(
            self.design_element_url(self.design, price_id, "reset-element")
        )

        self.assertEqual(response.status_code, 200, response.data)

    def test_a_duplicate_can_be_reset_to_the_same_original(self):
        original = self.element_of(self.design, "price")
        copy = duplicate_element(original)
        copy["content"] = "changed"
        self.design.elements.append(copy)
        self.design.save(update_fields=["elements"])

        response = self.client.post(
            self.design_element_url(self.design, copy["id"], "reset-element")
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["element"]["transform"]["x"], 0.06)

    def test_an_added_element_cannot_be_reset_and_says_so(self):
        """Silence would be indistinguishable from a bug."""
        added = new_element("text")
        self.design.elements.append(added)
        self.design.save(update_fields=["elements"])

        response = self.client.post(
            self.design_element_url(self.design, added["id"], "reset-element")
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("no template original", response.data["detail"])

    def test_reset_design_restores_the_whole_canvas(self):
        self.design.elements = [new_element("text")]
        self.design.save(update_fields=["elements"])

        response = self.client.post(
            self.design_action_url(self.design, "reset"), {"confirm": True}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        self.assertEqual(len(self.design.elements), self.template.elements.count())

    def test_reset_design_refuses_without_confirmation(self):
        """It is unrecoverable. A mis-wired button or a replayed request must
        not be able to wipe a design on its own."""
        self.element_of(self.design, "headline")["content"] = "Precious"
        self.design.save(update_fields=["elements"])

        response = self.client.post(
            self.design_action_url(self.design, "reset"), {}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.design.refresh_from_db()
        self.assertEqual(self.element_of(self.design, "headline")["content"], "Precious")

    def test_another_agent_cannot_reset_your_design(self):
        other, _profile = self.make_agent_in(self.acme, "b@example.com")
        self.authenticate_as(other)

        response = self.client.post(
            self.design_action_url(self.design, "reset"), {"confirm": True}, format="json"
        )

        self.assertEqual(response.status_code, 404)


# ===========================================================================
# 2. Bindings
# ===========================================================================


class BindingTests(DocumentTestCase):
    def render(self):
        return build_html(
            self.design,
            build_context(self.design),
            get_dimension("instagram_post"),
            {},
        )

    def test_the_template_content_source_becomes_a_named_binding(self):
        self.assertEqual(self.element_of(self.design, "price")["bound_to"], "price")
        self.assertEqual(
            self.element_of(self.design, "disclaimer")["bound_to"], "disclaimer"
        )

    def test_a_binding_populates_content_on_open(self):
        response = self.client.get(self.design_action_url(self.design, "resolved"))
        by_original = {
            e["original_element_id"]: e for e in response.data["elements"]
        }

        self.assertEqual(by_original["price"]["resolved_content"], "$1,850,000")

    def test_a_binding_does_not_restrict_anything(self):
        """The rule that separates a binding from the old permission tier: a
        bound element moves, restyles and retypes like any other."""
        element = self.element_of(self.design, "price")
        elements = self.document()
        for candidate in elements:
            if candidate["id"] == element["id"]:
                candidate["transform"] = {
                    "x": 0.7, "y": 0.1, "width": 0.25, "height": 0.05,
                    "rotation": 12.0, "z_index": 3,
                }
                candidate["style"] = {"color": "#123456", "font_size_ratio": 0.09}
                candidate["type"] = "button"

        response = self.save(elements)

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        moved = self.element_of(self.design, "price")
        self.assertEqual(moved["transform"]["x"], 0.7)
        self.assertEqual(moved["transform"]["rotation"], 12.0)
        self.assertEqual(moved["type"], "button")
        self.assertEqual(moved["bound_to"], "price")

    def test_editing_bound_text_does_not_change_the_underlying_data(self):
        original = self.listing.price
        element = self.element_of(self.design, "price")
        element["content"] = "POA"
        element["manually_overridden"] = True
        self.design.save(update_fields=["elements"])

        self.assertIn("POA", self.render())
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.price, original)

    def test_an_overridden_element_is_not_silently_overwritten_by_new_data(self):
        element = self.element_of(self.design, "price")
        element["content"] = "POA"
        element["manually_overridden"] = True
        self.design.save(update_fields=["elements"])

        self.listing.price = 2_000_000
        self.listing.save()

        html = self.render()
        self.assertIn("POA", html)
        self.assertNotIn("$2,000,000", html)

    def test_a_non_overridden_element_follows_the_data(self):
        self.listing.price = 2_000_000
        self.listing.save()

        self.assertIn("$2,000,000", self.render())

    def test_syncing_clears_the_flag_and_the_value_returns(self):
        element = self.element_of(self.design, "price")
        element["content"] = "POA"
        element["manually_overridden"] = True
        self.design.save(update_fields=["elements"])

        element["manually_overridden"] = False
        self.design.save(update_fields=["elements"])

        self.assertIn("$1,850,000", self.render())

    def test_the_binding_survives_a_manual_edit(self):
        """Flagged, not deleted — otherwise "reset to property data" would have
        nothing to reset to."""
        elements = self.document()
        for element in elements:
            if element["original_element_id"] == "price":
                element["content"] = "POA"
                element["manually_overridden"] = True

        self.save(elements)

        self.design.refresh_from_db()
        self.assertEqual(self.element_of(self.design, "price")["bound_to"], "price")

    def test_a_binding_and_its_content_source_cannot_disagree(self):
        """A payload claiming one field and sourcing another would render one
        thing and label itself another, so the source is derived, not trusted."""
        elements = self.document()
        for element in elements:
            if element["original_element_id"] == "price":
                element["bound_to"] = "agent_phone"
                element["content_source"] = "property.price"

        self.save(elements)

        self.design.refresh_from_db()
        element = self.element_of(self.design, "price")
        self.assertEqual(element["bound_to"], "agent_phone")
        self.assertEqual(element["content_source"], "agent.phone")

    def test_an_unknown_binding_is_refused(self):
        elements = self.document()
        elements[0]["bound_to"] = "shoe_size"

        response = self.save(elements)

        self.assertEqual(response.status_code, 400)


class PropertyDataEndpointTests(DocumentTestCase):
    def url(self):
        return self.design_action_url(self.design, "property-data")

    def test_it_lists_the_fields_with_their_current_values(self):
        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200, response.data)
        fields = {field["name"]: field for field in response.data["fields"]}
        self.assertEqual(fields["price"]["value"], float(self.listing.price))
        self.assertEqual(fields["agent_name"]["value"], self.profile.name)
        self.assertTrue(response.data["has_listing"])

    def test_it_reports_which_elements_are_bound_to_each_field(self):
        response = self.client.get(self.url())
        fields = {field["name"]: field for field in response.data["fields"]}

        self.assertEqual(
            fields["price"]["bound_element_ids"],
            [self.element_of(self.design, "price")["id"]],
        )

    def test_it_reports_which_bound_elements_have_been_customised(self):
        """What the panel needs to say "3 elements customized" instead of
        silently overwriting them."""
        element = self.element_of(self.design, "price")
        element["manually_overridden"] = True
        self.design.save(update_fields=["elements"])

        response = self.client.get(self.url())
        fields = {field["name"]: field for field in response.data["fields"]}

        self.assertEqual(fields["price"]["overridden_element_ids"], [element["id"]])

    def test_every_registered_field_is_published(self):
        response = self.client.get(self.url())

        self.assertEqual(
            {field["name"] for field in response.data["fields"]},
            set(PROPERTY_FIELDS_BY_NAME),
        )


# ===========================================================================
# 3. What still says no — and why none of it is about permission
# ===========================================================================


class RendererSafetyTests(DocumentTestCase):
    """Every one of these values is interpolated into a ``style`` attribute or
    an ``src`` in HTML that a real browser executes. These checks predate the
    permission model, are unrelated to it, and outlive it.
    """

    def test_a_colour_cannot_smuggle_a_second_declaration(self):
        elements = self.document()
        elements[0]["style"] = {
            "background_color": "#fff;background-image:url(https://example.invalid/x)"
        }

        response = self.save(elements)

        self.assertEqual(response.status_code, 400)
        self.design.refresh_from_db()
        self.assertNotIn("example.invalid", str(self.design.elements))

    def test_a_brand_token_is_still_allowed(self):
        elements = self.document()
        elements[0]["style"] = {"background_color": "@accent_color"}

        self.assertEqual(self.save(elements).status_code, 200)

    def test_an_image_cannot_be_a_url(self):
        """Would be fetched by the renderer, from our container, to a host the
        caller chose."""
        elements = self.document()
        for element in elements:
            if element["original_element_id"] == "hero_photo":
                element["content"] = "https://example.invalid/pixel.png"

        response = self.save(elements)

        self.assertEqual(response.status_code, 400)
        self.assertIn("not a URL", str(response.data))

    def test_an_image_cannot_traverse_out_of_storage(self):
        elements = self.document()
        for element in elements:
            if element["original_element_id"] == "hero_photo":
                element["content"] = "../../etc/passwd"

        self.assertEqual(self.save(elements).status_code, 400)

    def test_a_gradient_cannot_contain_a_url(self):
        elements = self.document()
        elements[0]["style"] = {
            "background_gradient": "linear-gradient(red, url(https://example.invalid/x))"
        }

        self.assertEqual(self.save(elements).status_code, 400)

    def test_a_real_gradient_is_accepted(self):
        elements = self.document()
        elements[0]["style"] = {
            "background_gradient": "linear-gradient(180deg, #8B4F24 0%, #2A1A10 100%)"
        }

        self.assertEqual(self.save(elements).status_code, 200)

    def test_text_is_escaped_on_the_way_into_the_html(self):
        elements = self.document()
        for element in elements:
            if element["original_element_id"] == "headline":
                element["content"] = "<img src=x onerror=alert(1)>"
                element["manually_overridden"] = True
        self.save(elements)
        self.design.refresh_from_db()

        html = build_html(
            self.design,
            build_context(self.design),
            get_dimension("instagram_post"),
            {},
        )

        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;img", html)

    def test_a_design_cannot_hold_an_unbounded_number_of_elements(self):
        """The renderer lays out every one of these in a real browser."""
        response = self.save([new_element("text") for _ in range(MAX_ELEMENTS + 1)])

        self.assertEqual(response.status_code, 400)

    def test_two_elements_cannot_share_an_id(self):
        """Selection, layer rows and undo all address elements by id."""
        elements = self.document()
        elements[1]["id"] = elements[0]["id"]

        self.assertEqual(self.save(elements).status_code, 400)

    def test_an_unknown_element_type_is_refused(self):
        elements = self.document()
        elements[0]["type"] = "iframe"

        self.assertEqual(self.save(elements).status_code, 400)

    def test_an_unknown_style_key_is_dropped_rather_than_refused(self):
        """A whole autosave should not fail because the client knows a style
        key the server does not yet. The key simply does not survive, which is
        visible and recoverable; a rejected save loses the user's work."""
        elements = self.document()
        elements[0]["style"] = {"color": "#123456", "font_variant": "small-caps"}

        response = self.save(elements)

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        self.assertEqual(self.design.elements[0]["style"], {"color": "#123456"})

    def test_a_known_style_key_with_a_bad_value_does_fail(self):
        elements = self.document()
        elements[0]["style"] = {"opacity": 40}

        self.assertEqual(self.save(elements).status_code, 400)

    def test_geometry_may_bleed_off_canvas_but_not_run_away(self):
        """Cropping an image against the bleed is normal in a design tool; the
        old 0..1 clamp made it impossible. A thousand canvases away is not a
        design choice, it is an element the agent can never find again."""
        elements = self.document()
        elements[0]["transform"] = {
            "x": -0.2, "y": -0.1, "width": 1.4, "height": 1.2, "rotation": 0, "z_index": 0
        }
        self.assertEqual(self.save(elements).status_code, 200)

        elements[0]["transform"]["x"] = 900.0
        self.assertEqual(self.save(elements).status_code, 400)

    def test_a_nonsense_number_is_refused(self):
        elements = self.document()
        elements[0]["transform"] = {
            "x": float("inf"), "y": 0, "width": 0.5, "height": 0.5,
            "rotation": 0, "z_index": 0,
        }

        with self.assertRaises(DocumentValidationError):
            validate_document(elements)


class LockTests(DocumentTestCase):
    """``locked`` is the only thing that restricts editing — and it is the
    user's own switch, not the template's.

    It is enforced in the editor, where the interaction happens: a locked
    element does not hit-test, drag or resize. It is deliberately not enforced
    here, because the editor saves the whole document at once, so "unlock it
    and move it" is a single save and refusing that would break the obvious
    flow to protect the user from a decision they just made.
    """

    def test_it_defaults_to_false_on_a_copied_element(self):
        self.assertEqual([], [e for e in self.design.elements if e["locked"]])

    def test_it_defaults_to_false_on_a_new_element(self):
        for kind in BLANK_ELEMENTS:
            with self.subTest(kind=kind):
                self.assertFalse(new_element(kind)["locked"])

    def test_it_round_trips(self):
        elements = self.document()
        elements[0]["locked"] = True

        self.save(elements)

        self.design.refresh_from_db()
        self.assertTrue(self.design.elements[0]["locked"])

    def test_unlocking_and_moving_in_one_save_is_accepted(self):
        elements = self.document()
        elements[0]["locked"] = True
        self.save(elements)

        elements = self.document()
        elements[0]["locked"] = False
        elements[0]["transform"] = {**elements[0]["transform"], "x": 0.42}

        self.assertEqual(self.save(elements).status_code, 200)

    def test_a_locked_element_still_renders(self):
        """Locked is not hidden. Confusing the two would make locking the
        background a way to lose it."""
        elements = self.document()
        for element in elements:
            if element["original_element_id"] == "badge":
                element["locked"] = True
        self.save(elements)
        self.design.refresh_from_db()

        html = build_html(
            self.design, build_context(self.design), get_dimension("instagram_post"), {}
        )

        self.assertIn("Just listed", html)


class StackingOrderTests(DocumentTestCase):
    def test_render_order_is_by_z_index_not_list_order(self):
        elements = [
            {**new_element("text"), "transform": {**new_element("text")["transform"], "z_index": z}}
            for z in (5, 1, 3)
        ]

        self.assertEqual(
            [1, 3, 5],
            [e["transform"]["z_index"] for e in sorted_for_render(elements)],
        )

    def test_ties_break_on_list_order_so_reordering_is_stable(self):
        first, second = new_element("text"), new_element("shape")
        first["transform"]["z_index"] = second["transform"]["z_index"] = 4

        self.assertEqual(
            [first["id"], second["id"]],
            [e["id"] for e in sorted_for_render([first, second])],
        )

    def test_normalising_makes_the_numbers_dense(self):
        """Without it, repeated "bring to front" walks z_index towards the cap
        and eventually pins several elements together at it."""
        elements = [new_element("text") for _ in range(3)]
        for element, z in zip(elements, (900, 40, 998)):
            element["transform"]["z_index"] = z

        self.assertEqual(
            [0, 1, 2],
            [e["transform"]["z_index"] for e in normalise_z_order(elements)],
        )


class ElementKindsEndpointTests(DocumentTestCase):
    def test_it_publishes_every_addable_kind(self):
        response = self.client.get(self.element_kinds_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["kind"] for row in response.data}, set(BLANK_ELEMENTS)
        )

    def test_every_published_blueprint_actually_validates(self):
        """One definition, two consumers. A blueprint the canvas could create
        and the server would then refuse is the exact bug this prevents."""
        response = self.client.get(self.element_kinds_url)

        for row in response.data:
            with self.subTest(kind=row["kind"]):
                validate_document([new_element(row["kind"])])

    def test_every_element_type_is_addable(self):
        self.assertEqual(set(BLANK_ELEMENTS), ELEMENT_TYPES)


class AddElementTests(DocumentTestCase):
    def test_adding_puts_a_new_element_on_top(self):
        response = self.client.post(
            self.design_action_url(self.design, "add-element"),
            {"kind": "button"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.design.refresh_from_db()
        added = self.design.elements[-1]
        self.assertEqual(added["type"], "button")
        self.assertEqual(
            added["transform"]["z_index"],
            max(e["transform"]["z_index"] for e in self.design.elements),
        )

    def test_an_unknown_kind_is_refused(self):
        response = self.client.post(
            self.design_action_url(self.design, "add-element"),
            {"kind": "spreadsheet"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class DuplicateElementTests(DocumentTestCase):
    def test_the_copy_gets_its_own_id_and_is_nudged_off_the_original(self):
        original = self.element_of(self.design, "price")

        copy = duplicate_element(original)

        self.assertNotEqual(copy["id"], original["id"])
        self.assertGreater(copy["transform"]["x"], original["transform"]["x"])
        self.assertGreater(
            copy["transform"]["z_index"], original["transform"]["z_index"]
        )

    def test_the_copy_does_not_share_mutable_state_with_the_original(self):
        original = self.element_of(self.design, "price")
        copy = duplicate_element(original)

        copy["style"]["color"] = "#000000"
        copy["transform"]["x"] = 0.99

        self.assertNotEqual(original["style"].get("color"), "#000000")
        self.assertNotEqual(original["transform"]["x"], 0.99)


class TemplateSerializerTests(DocumentTestCase):
    def test_the_permission_concept_is_absent_from_the_api(self):
        """Not renamed and not defaulted — gone, in the payload as in the
        model."""
        detail = self.client.get(self.template_detail_url(self.template)).data

        self.assertNotIn("permission_map", detail)
        for element in detail["elements"]:
            self.assertNotIn("permission", element)
            self.assertNotIn("editable_fields", element)

    def test_the_word_does_not_appear_in_the_design_payload_either(self):
        payload = str(self.client.get(self.design_detail_url(self.design)).data)

        self.assertNotIn("permission", payload)
        self.assertNotIn("FIXED BY TEMPLATE", payload)


class LegacyFieldTests(DocumentTestCase):
    def test_the_old_override_fields_are_no_longer_writable(self):
        """They are retained so pre-canvas designs stay readable, but nothing
        writes them — including a client that still tries."""
        response = self.client.patch(
            self.design_detail_url(self.design),
            {"overrides": {"headline": {"text": "via the old path"}}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.design.refresh_from_db()
        self.assertEqual(self.design.overrides, {})

    def test_they_are_not_in_the_payload(self):
        payload = self.client.get(self.design_detail_url(self.design)).data

        self.assertNotIn("overrides", payload)
        self.assertNotIn("extra_elements", payload)
