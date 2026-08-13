"""The tall portrait format, and a template's right to open in its own shape.

A template composed at 844x2048 and opened at 1080x1080 is not "the same
design at another size" — the composition was drawn for a column and the
square reads as a crop of it. Geometry stays normalised (one stored design
still renders at every size); what changes here is that a template can say
which size it was drawn for, and that the tall size exists at all.
"""

from __future__ import annotations

from apps.templates.dimensions import SOCIAL_DIMENSIONS, get_dimension
from apps.templates.html_builder import build_html
from apps.templates.models import ElementType, TemplateElement
from apps.templates.render_context import build_context
from apps.templates.tests.base import TemplateAPITestCase

ORIGINAL_WIDTH = 844
ORIGINAL_HEIGHT = 2048


class PortraitDimensionTests(TemplateAPITestCase):
    def test_the_portrait_format_is_the_original_artwork_size(self):
        dimension = get_dimension("portrait_tall")

        self.assertEqual((dimension.width, dimension.height), (ORIGINAL_WIDTH, ORIGINAL_HEIGHT))

    def test_it_preserves_the_exact_source_aspect_ratio(self):
        dimension = get_dimension("portrait_tall")

        self.assertAlmostEqual(dimension.aspect, ORIGINAL_WIDTH / ORIGINAL_HEIGHT, places=9)

    def test_it_is_not_merely_a_story_by_another_name(self):
        """0.5625 vs 0.4121 — using Story would letterbox or stretch."""
        self.assertNotAlmostEqual(
            get_dimension("portrait_tall").aspect,
            get_dimension("instagram_story").aspect,
            places=3,
        )

    def test_it_reserves_no_safe_area(self):
        """It is a download format; no platform paints chrome over it."""
        dimension = get_dimension("portrait_tall")

        self.assertEqual(dimension.safe_inset_top, 0.0)
        self.assertEqual(dimension.safe_inset_bottom, 0.0)

    def test_the_existing_four_formats_are_untouched(self):
        """Names the four rather than subtracting the additions — written the
        other way round, every new format broke it for no reason."""
        expected = {
            "instagram_post": (1080, 1080),
            "instagram_story": (1080, 1920),
            "facebook": (1200, 630),
            "linkedin": (1200, 627),
        }

        actual = {
            key: (SOCIAL_DIMENSIONS[key].width, SOCIAL_DIMENSIONS[key].height)
            for key in expected
        }

        self.assertEqual(actual, expected)

    def test_it_is_offered_by_the_dimensions_endpoint(self):
        agent, _profile = self.make_agent_in(self.make_brokerage("Acme"), "a@example.com")
        self.authenticate_as(agent)

        response = self.client.get("/api/render-dimensions/")

        keys = {row["key"] for row in response.data}
        self.assertIn("portrait_tall", keys)

    def test_geometry_maps_into_the_portrait_canvas(self):
        acme = self.make_brokerage("Acme")
        agent, profile = self.make_agent_in(acme, "a@example.com")
        template = self.make_template()
        TemplateElement.objects.create(
            template=template,
            key="probe",
            label="Probe",
            element_type=ElementType.COLOR_BLOCK,
            geometry={"x": 0.5, "y": 0.25, "width": 0.25, "height": 0.1, "rotation": 0.0},
            style_properties={"background_color": "#ABCDEF"},
            z_index=40,
        )
        listing = self.make_verified_listing(profile, agent)
        design = self.make_design(template, profile, listing)

        html = build_html(
            design, build_context(design), get_dimension("portrait_tall"), {}
        )

        # No insets, so the mapping is the plain fraction of each axis.
        self.assertIn(f"left:{0.5 * ORIGINAL_WIDTH:.2f}px", html)
        self.assertIn(f"top:{0.25 * ORIGINAL_HEIGHT:.2f}px", html)
        self.assertIn(f"width:{0.25 * ORIGINAL_WIDTH:.2f}px", html)
        self.assertIn(f"height:{0.1 * ORIGINAL_HEIGHT:.2f}px", html)


class TemplateNativeFormatTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.authenticate_as(self.agent)

    def test_a_template_defaults_to_the_square_format(self):
        """Existing templates keep opening exactly as they did."""
        self.assertEqual(self.template.default_dimension, "instagram_post")

    def test_a_template_can_declare_a_portrait_native_format(self):
        self.template.default_dimension = "portrait_tall"
        self.template.save(update_fields=["default_dimension"])

        response = self.client.get(f"/api/templates/{self.template.id}/")

        self.assertEqual(response.data["default_dimension"], "portrait_tall")

    def test_the_native_format_is_published_in_the_library_listing_too(self):
        response = self.client.get("/api/templates/")

        self.assertIn("default_dimension", response.data["results"][0])

    def test_declaring_a_native_format_does_not_restrict_the_others(self):
        """One stored design, every size — that property must survive."""
        self.template.default_dimension = "portrait_tall"
        self.template.save(update_fields=["default_dimension"])
        listing = self.make_verified_listing(self.profile, self.agent)
        design = self.make_design(self.template, self.profile, listing)

        for key in SOCIAL_DIMENSIONS:
            with self.subTest(dimension=key):
                html = build_html(
                    design, build_context(design), get_dimension(key), {}
                )
                self.assertIn("<div id=\"canvas\"", html)

    def test_a_portrait_design_can_still_be_exported_at_every_size(self):
        self.template.default_dimension = "portrait_tall"
        self.template.save(update_fields=["default_dimension"])
        listing = self.make_verified_listing(self.profile, self.agent)
        design = self.make_design(self.template, self.profile, listing)

        response = self.client.get(
            self.design_action_url(design, "resolved") + "?dimension=portrait_tall"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["width"], ORIGINAL_WIDTH)
        self.assertEqual(response.data["height"], ORIGINAL_HEIGHT)
