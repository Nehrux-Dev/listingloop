"""The editor edits; the renderer exports. These tests hold them to the same
arithmetic.

The canvas in the browser and ``element_html`` here are two independent
implementations of one layout: both take fractional geometry and produce
absolutely-positioned CSS. Nothing enforces that they agree except the fact
that both follow the same documented formula:

    left   = x * width
    top    = (safe_inset_top + y * safe_height) * height
    width  = w * width
    height = h * safe_height * height          safe_height = 1 - top - bottom

So these tests pin that formula per dimension, and then check that every field
the editor can write actually reaches the exported HTML. A field the editor
offers but the renderer ignores is the worst kind of bug here: the agent sees
their change on the canvas, the export silently drops it, and nothing errors.
"""

from __future__ import annotations

import re

from apps.templates.dimensions import SOCIAL_DIMENSIONS, get_dimension
from apps.templates.document import new_element
from apps.templates.html_builder import build_html
from apps.templates.models import ElementType, TemplateElement
from apps.templates.render_context import build_context
from apps.templates.tests.base import TemplateAPITestCase


def css_of(html: str, needle: str) -> dict[str, str]:
    """Pull the inline style of the element identified by ``needle``.

    ``needle`` is matched against the element's own style declaration or its
    own inner content only — deliberately not a window of surrounding markup,
    which matched whichever element merely happened to come first.
    """
    for match in re.finditer(r'<div style="([^"]+)"[^>]*>', html):
        style = match.group(1)
        inner = html[match.end() :].split("<div", 1)[0]
        if needle in style or needle in inner:
            return dict(
                part.split(":", 1)  # type: ignore[misc]
                for part in style.split(";")
                if ":" in part
            )
    raise AssertionError(f"No element identified by {needle!r} in the rendered HTML")


class DocumentEditMixin:
    """Edit a design's own element the way the editor does — in the document.

    There is no override layer any more, so "the agent changed this" is
    literally "the element says something different". These helpers exist so
    the tests below read as edits rather than as dictionary surgery.
    """

    def edit(self, design, original_key: str, **fields):
        """Change one element, addressed by the template element it came from."""
        element = self.element_of(design, original_key)
        style = fields.pop("style", None)
        transform = fields.pop("transform", None)
        if style:
            element["style"] = {**element["style"], **style}
        if transform:
            element["transform"] = {**element["transform"], **transform}
        element.update(fields)
        design.save(update_fields=["elements"])
        return element

    def add(self, design, kind: str, **fields):
        element = new_element(kind, z_index=99)
        element.update(fields)
        design.elements.append(element)
        design.save(update_fields=["elements"])
        return element

    def render(self, design, dimension_key="instagram_post"):
        return build_html(
            design, build_context(design), get_dimension(dimension_key), {}
        )


class GeometryConversionTests(DocumentEditMixin, TemplateAPITestCase):
    """Fractions in, pixels out — for every format the product supports."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        # An element with unambiguous geometry, so the numbers below are
        # arithmetic rather than a guess about the fixture.
        TemplateElement.objects.create(
            template=self.template,
            key="probe",
            label="Probe",
            element_type=ElementType.COLOR_BLOCK,
            geometry={"x": 0.25, "y": 0.5, "width": 0.5, "height": 0.2, "rotation": 0.0},
            style_properties={"background_color": "#ABCDEF"},
            z_index=40,
        )
        self.listing = self.make_verified_listing(self.profile, self.agent)

    def fresh(self):
        return self.make_design(self.template, self.profile, self.listing)

    def test_every_supported_dimension_maps_geometry_by_the_documented_formula(self):
        design = self.fresh()
        for key, dimension in SOCIAL_DIMENSIONS.items():
            with self.subTest(dimension=key):
                css = css_of(self.render(design, key), "#ABCDEF")

                safe_height = 1 - dimension.safe_inset_top - dimension.safe_inset_bottom
                self.assertEqual(css["left"], f"{0.25 * dimension.width:.2f}px")
                self.assertEqual(
                    css["top"],
                    f"{(dimension.safe_inset_top + 0.5 * safe_height) * dimension.height:.2f}px",
                )
                self.assertEqual(css["width"], f"{0.5 * dimension.width:.2f}px")
                self.assertEqual(
                    css["height"], f"{0.2 * safe_height * dimension.height:.2f}px"
                )

    def test_the_four_named_formats_are_all_present(self):
        """The product promises these four; a rename would break the editor's
        dimension tabs silently. Additional formats are fine — this is a
        floor, not a ceiling."""
        self.assertLessEqual(
            {"instagram_post", "instagram_story", "facebook", "linkedin"},
            set(SOCIAL_DIMENSIONS),
        )

    def test_story_reserves_its_safe_area_and_the_square_does_not(self):
        """The insets are the reason a Story export is not just a taller Post."""
        design = self.fresh()
        post = css_of(self.render(design, "instagram_post"), "#ABCDEF")
        story = css_of(self.render(design, "instagram_story"), "#ABCDEF")

        # Same fraction, but the Story maps it into the middle 74% only.
        self.assertEqual(post["top"], f"{0.5 * 1080:.2f}px")
        self.assertEqual(story["top"], f"{(0.12 + 0.5 * 0.74) * 1920:.2f}px")

    def test_an_edited_position_moves_the_exported_element(self):
        """The whole point of the pipeline: the editor writes normalized
        geometry, the renderer converts it, the export reflects the edit."""
        design = self.fresh()
        self.edit(
            design, "probe", transform={"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
        )
        css = css_of(self.render(design), "#ABCDEF")

        self.assertEqual(css["left"], "108.00px")
        self.assertEqual(css["top"], "216.00px")
        self.assertEqual(css["width"], "324.00px")
        self.assertEqual(css["height"], "432.00px")

    def test_rotation_reaches_the_export_around_the_elements_own_centre(self):
        design = self.fresh()
        self.edit(design, "probe", transform={"rotation": -33.5})
        css = css_of(self.render(design), "#ABCDEF")

        self.assertEqual(css["transform"], "rotate(-33.50deg)")
        self.assertEqual(css["transform-origin"], "center center")

    def test_geometry_is_stored_normalized_not_in_pixels(self):
        """Pixels in the database would mean one stored design per format."""
        design = self.fresh()
        self.edit(
            design, "probe", transform={"x": 0.4, "y": 0.4, "width": 0.2, "height": 0.2}
        )
        design.refresh_from_db()

        stored = self.element_of(design, "probe")["transform"]
        for axis in ("x", "y", "width", "height"):
            self.assertLessEqual(stored[axis], 1.0)

        # And one stored design still renders at every size.
        for key in SOCIAL_DIMENSIONS:
            self.assertIn("#ABCDEF", self.render(design, key))


class EditorFieldsReachTheExportTests(DocumentEditMixin, TemplateAPITestCase):
    """Every field the editor can write must survive to the exported HTML.

    A control that changes the canvas but not the export is the failure this
    class exists to catch — it looks like it worked right up until the file
    lands in someone's inbox.
    """

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        TemplateElement.objects.create(
            template=self.template,
            key="body_text",
            label="Body text",
            element_type=ElementType.TEXT,
            geometry={"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.1, "rotation": 0.0},
            default_content="Exportable",
            style_properties={"color": "#111111", "font_size_ratio": 0.04},
            z_index=30,
        )
        self.listing = self.make_verified_listing(self.profile, self.agent)
        self.design = self.make_design(self.template, self.profile, self.listing)

    def test_text_edits_reach_the_export(self):
        self.edit(self.design, "body_text", content="Edited in the canvas")
        self.assertIn("Edited in the canvas", self.render(self.design))

    def test_every_style_field_the_editor_offers_reaches_the_css(self):
        self.edit(
            self.design,
            "body_text",
            transform={"z_index": 88},
            style={
                "color": "#223344",
                "font_size_ratio": 0.06,
                "font_weight": "700",
                "font_style": "italic",
                "text_align": "right",
                "text_decoration": "underline",
                "line_height": 2.1,
                "letter_spacing_em": 0.12,
                "opacity": 0.65,
                "border_radius_ratio": 0.03,
                "border_width_ratio": 0.004,
                "border_color": "#654321",
                "border_style": "dashed",
            },
        )
        css = css_of(self.render(self.design), "Exportable")

        self.assertEqual(css["color"], "#223344")
        self.assertEqual(css["font-size"], f"{0.06 * 1080:.2f}px")
        self.assertEqual(css["font-weight"], "700")
        self.assertEqual(css["font-style"], "italic")
        self.assertEqual(css["text-align"], "right")
        self.assertEqual(css["text-decoration"], "underline")
        self.assertEqual(css["line-height"], "2.1")
        self.assertEqual(css["letter-spacing"], "0.12em")
        self.assertEqual(css["opacity"], "0.65")
        self.assertEqual(css["border-radius"], f"{0.03 * 1080:.2f}px")
        self.assertEqual(css["border"], f"{0.004 * 1080:.2f}px dashed #654321")
        self.assertEqual(css["z-index"], "88")

    def test_hiding_an_element_removes_it_from_the_export(self):
        self.edit(self.design, "body_text", visible=False)
        self.assertNotIn("Exportable", self.render(self.design))

    def test_image_framing_reaches_the_export_as_a_css_transform(self):
        """Crop is expressed as zoom-and-pan inside the frame, so the editor
        and the export are laying out the same box rather than the export
        re-deriving a crop from its own arithmetic."""
        photo = self.edit(
            self.design,
            "hero_photo",
            style={"image_scale": 1.75, "image_offset_x": -0.2, "image_offset_y": 0.1},
        )
        # The fixture listing has no photo, so the image is supplied the same
        # way rendering.resolve_images would supply it: element id -> data URI.
        html = build_html(
            self.design,
            build_context(self.design),
            get_dimension("instagram_post"),
            {photo["id"]: "data:image/png;base64,AAAA"},
        )

        self.assertIn("scale(1.750)", html)
        self.assertIn("translate(-20.00%,10.00%)", html)

    # An added shape asserts on its own geometry rather than its colour: the
    # fixture's badge is #2563EB too, so a colour match alone would pass even
    # if added elements never reached the renderer at all.
    def test_an_added_element_is_exported(self):
        self.add(self.design, "shape", transform={
            "x": 0.2, "y": 0.2, "width": 0.3, "height": 0.3, "rotation": 0.0, "z_index": 99,
        })
        self.assertIn("left:216.00px", self.render(self.design))

    def test_a_deleted_added_element_is_not_exported(self):
        added = self.add(self.design, "shape", transform={
            "x": 0.2, "y": 0.2, "width": 0.3, "height": 0.3, "rotation": 0.0, "z_index": 99,
        })
        self.design.elements = [
            element for element in self.design.elements if element["id"] != added["id"]
        ]
        self.design.save(update_fields=["elements"])

        self.assertNotIn("left:216.00px", self.render(self.design))

    def test_an_added_element_is_exported_at_every_dimension(self):
        self.add(self.design, "shape", style={"border_radius_ratio": 0.5})

        for key in SOCIAL_DIMENSIONS:
            with self.subTest(dimension=key):
                dimension = get_dimension(key)
                scale_ref = min(dimension.width, dimension.height)
                self.assertIn(
                    f"border-radius:{0.5 * scale_ref:.2f}px",
                    self.render(self.design, key),
                )

    def test_reordering_changes_the_exported_stacking_order(self):
        self.assertEqual(css_of(self.render(self.design), "Exportable")["z-index"], "30")

        self.edit(self.design, "body_text", transform={"z_index": 2})

        self.assertEqual(css_of(self.render(self.design), "Exportable")["z-index"], "2")

    def test_elements_are_painted_in_stacking_order_not_document_order(self):
        """The canvas paints back to front; so must the export, or an element
        the agent sent behind another comes out in front of it."""
        self.edit(self.design, "body_text", transform={"z_index": 0})
        html = self.render(self.design)

        body_at = html.index("Exportable")
        badge_at = html.index("Just listed")  # fixture badge, z_index 11
        self.assertLess(body_at, badge_at)


class DynamicListingDataTests(DocumentEditMixin, TemplateAPITestCase):
    """A design bound to a listing renders that listing's data — the export
    is where that actually matters."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)

    def test_listing_data_flows_into_the_export(self):
        design = self.make_design(self.template, self.profile, self.listing)

        html = self.render(design)

        self.assertIn(str(self.listing.address).split(",")[0][:10], html)

    def test_a_bound_element_tracks_the_listing_until_the_agent_types_over_it(self):
        """The binding rule, end to end: bound content follows the data, and
        stops following it the moment the agent writes their own words —
        without the underlying listing changing at all."""
        original_address = self.listing.address
        design = self.make_design(self.template, self.profile, self.listing)

        self.assertIn(original_address.split(",")[0][:10], self.render(design))

        self.edit(
            design, "headline", content="Agent's own words", manually_overridden=True
        )
        html = self.render(design)

        self.assertIn("Agent&#x27;s own words", html)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.address, original_address)

    def test_clearing_the_override_flag_resyncs_to_the_current_data(self):
        """"Sync to current data" is exactly this flag going false, which is
        why the binding is flagged rather than deleted on a manual edit."""
        design = self.make_design(self.template, self.profile, self.listing)
        self.edit(design, "headline", content="Stale", manually_overridden=True)
        self.assertIn("Stale", self.render(design))

        self.edit(design, "headline", manually_overridden=False)

        self.assertNotIn(">Stale<", self.render(design))
        self.assertIn(self.listing.address.split(",")[0][:10], self.render(design))


class TemplateIsNeverModifiedByExportTests(DocumentEditMixin, TemplateAPITestCase):
    """The master template survives everything the editor and exporter do."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)

    def snapshot(self):
        self.template.refresh_from_db()
        return {
            element.key: (
                element.geometry,
                element.style_properties,
                element.z_index,
                element.default_content,
                element.content_source,
            )
            for element in self.template.elements.all()
        }

    def test_rendering_every_dimension_leaves_the_template_untouched(self):
        before = self.snapshot()

        design = self.make_design(self.template, self.profile, self.listing)
        self.edit(design, "headline", content="Changed", manually_overridden=True)
        self.edit(
            design,
            "price",
            transform={"x": 0.9, "y": 0.9, "width": 0.05, "height": 0.02, "z_index": 99},
        )
        self.add(design, "shape")

        for key in SOCIAL_DIMENSIONS:
            self.render(design, key)

        self.assertEqual(before, self.snapshot())

    def test_deleting_every_element_of_a_design_leaves_the_template_whole(self):
        """The strongest form of the promise: a design can be emptied out and
        the template it came from is untouched, because the design owns a copy
        and never a reference."""
        before = self.snapshot()

        design = self.make_design(self.template, self.profile, self.listing)
        design.elements = []
        design.save(update_fields=["elements"])

        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.template.elements.count(), 5)

    def test_two_designs_on_one_template_do_not_leak_into_each_other(self):
        first = self.make_design(self.template, self.profile, self.listing)
        self.edit(first, "headline", content="First design", manually_overridden=True)
        second = self.make_design(self.template, self.profile, self.listing)

        self.assertIn("First design", self.render(first))
        self.assertNotIn("First design", self.render(second))

    def test_the_two_designs_do_not_even_share_element_ids(self):
        """Ids are generated per copy. Sharing them would make a client-side
        cache keyed on element id serve one design's element to another."""
        first = self.make_design(self.template, self.profile, self.listing)
        second = self.make_design(self.template, self.profile, self.listing)

        self.assertEqual(
            set(), {e["id"] for e in first.elements} & {e["id"] for e in second.elements}
        )
