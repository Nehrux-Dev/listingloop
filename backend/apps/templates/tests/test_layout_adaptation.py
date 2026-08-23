"""Layout adaptation: re-composing a design for another format.

The unit tests pin the placement rules — uniform scale, edge anchoring,
full-span stretch, cluster cohesion — because each one is a promise the
editor's "Adapt layout" button makes about what the copy will look like.
The endpoint tests cover the product surface: a 201 with a new, editable
design whose ``preferred_dimension`` tells the editor where to open it.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.templates.dimensions import get_dimension
from apps.templates.layout_adaptation import adapt_elements
from apps.templates.models import Design
from apps.templates.tests.base import TemplateAPITestCase

SQUARE = get_dimension("instagram_post")  # 1080 x 1080
LINKEDIN = get_dimension("linkedin")  # 1200 x 627
STORY = get_dimension("instagram_story")  # 1080 x 1920, safe insets
FLYER = get_dimension("flyer_portrait")  # 1414 x 2000

#: min(1200, 627) / min(1080, 1080) — the square-to-LinkedIn uniform scale.
S = 627 / 1080


def element(x, y, width, height, **extra):
    entry = {
        "id": f"el-{x}-{y}",
        "type": "shape",
        "transform": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "rotation": 0,
            "z_index": 0,
        },
        "style": {},
        "content": "",
        "visible": True,
        "locked": False,
    }
    entry.update(extra)
    return entry


class AdaptElementsTests(SimpleTestCase):
    def adapt_one(self, entry, source=SQUARE, target=LINKEDIN) -> dict:
        return adapt_elements([entry], source, target)[0]["transform"]

    def test_same_dimension_is_a_plain_copy(self):
        source = [element(0.1, 0.2, 0.3, 0.4)]
        result = adapt_elements(source, SQUARE, SQUARE)
        self.assertEqual(result, source)
        self.assertIsNot(result[0], source[0])  # a copy, not the same dict

    def test_full_bleed_background_still_covers(self):
        """The one thing that SHOULD stretch. Its object-fit does the crop."""
        transform = self.adapt_one(element(0.0, 0.0, 1.0, 1.0))
        self.assertAlmostEqual(transform["x"], 0.0)
        self.assertAlmostEqual(transform["y"], 0.0)
        self.assertAlmostEqual(transform["width"], 1.0)
        self.assertAlmostEqual(transform["height"], 1.0)

    def test_a_square_stays_square(self):
        """Uniform scaling is the whole point: fractional stretch would turn
        this 216px square into a 240 x 135 rectangle on LinkedIn."""
        transform = self.adapt_one(element(0.4, 0.4, 0.2, 0.2))
        width_px = transform["width"] * LINKEDIN.width
        height_px = transform["height"] * LINKEDIN.height
        self.assertAlmostEqual(width_px, 0.2 * 1080 * S, places=6)
        self.assertAlmostEqual(width_px, height_px, places=6)

    def test_corner_badge_keeps_its_scaled_margins(self):
        """Top-left third anchors to the top-left: the margins scale with the
        element instead of stretching with the canvas."""
        transform = self.adapt_one(element(0.06, 0.05, 0.2, 0.05))
        self.assertAlmostEqual(transform["x"] * LINKEDIN.width, 0.06 * 1080 * S, places=6)
        self.assertAlmostEqual(transform["y"] * LINKEDIN.height, 0.05 * 1080 * S, places=6)

    def test_bottom_right_element_hugs_the_bottom_right(self):
        """The far corner anchors to the far edges — measured from them."""
        transform = self.adapt_one(element(0.75, 0.85, 0.2, 0.1))
        right_margin = (1 - 0.75 - 0.2) * 1080  # px in the source
        bottom_margin = (1 - 0.85 - 0.1) * 1080
        self.assertAlmostEqual(
            (1 - transform["x"] - transform["width"]) * LINKEDIN.width,
            right_margin * S,
            places=6,
        )
        self.assertAlmostEqual(
            (1 - transform["y"] - transform["height"]) * LINKEDIN.height,
            bottom_margin * S,
            places=6,
        )

    def test_centered_element_stays_centered(self):
        transform = self.adapt_one(element(0.35, 0.45, 0.3, 0.1))
        self.assertAlmostEqual(transform["x"] + transform["width"] / 2, 0.5, places=6)

    def test_full_width_band_stretches_across_but_keeps_its_thickness(self):
        """A bottom bar spans the width, so it stretches horizontally; its
        height scales uniformly and it stays anchored to the bottom edge."""
        transform = self.adapt_one(element(0.0, 0.9, 1.0, 0.06))
        self.assertAlmostEqual(transform["x"], 0.0)
        self.assertAlmostEqual(transform["width"], 1.0)
        self.assertAlmostEqual(
            transform["height"] * LINKEDIN.height, 0.06 * 1080 * S, places=6
        )
        bottom_margin = (1 - 0.9 - 0.06) * 1080
        self.assertAlmostEqual(
            (1 - transform["y"] - transform["height"]) * LINKEDIN.height,
            bottom_margin * S,
            places=6,
        )

    def test_a_lockup_moves_as_one_across_an_anchor_boundary(self):
        """An icon in the left third and its label crossing into the middle
        third would be torn apart if each anchored alone — clustering keeps
        their spacing exact."""
        icon = element(0.28, 0.40, 0.05, 0.05)
        label = element(0.34, 0.405, 0.30, 0.04)
        icon_t, label_t = (
            entry["transform"] for entry in adapt_elements([icon, label], SQUARE, LINKEDIN)
        )
        source_offset_px = (0.34 - 0.28) * 1080
        self.assertAlmostEqual(
            (label_t["x"] - icon_t["x"]) * LINKEDIN.width,
            source_offset_px * S,
            places=6,
        )

    def test_separated_elements_do_not_cluster(self):
        """Two boxes far apart adapt independently — one left-anchored, one
        right-anchored — rather than being dragged around as a false group."""
        left = element(0.05, 0.4, 0.15, 0.1)
        right = element(0.80, 0.4, 0.15, 0.1)
        left_t, right_t = (
            entry["transform"] for entry in adapt_elements([left, right], SQUARE, LINKEDIN)
        )
        self.assertAlmostEqual(left_t["x"] * LINKEDIN.width, 0.05 * 1080 * S, places=6)
        self.assertAlmostEqual(
            (1 - right_t["x"] - right_t["width"]) * LINKEDIN.width,
            (1 - 0.80 - 0.15) * 1080 * S,
            places=6,
        )

    def test_style_and_identity_pass_through_untouched(self):
        """Square onto LinkedIn: the shorter-side ratio already fits both
        axes, so the ratio correction is exactly 1 and style must pass
        through EXACT — not multiplied by a float 1.0-and-an-epsilon."""
        entry = element(0.1, 0.1, 0.5, 0.2, style={"font_size_ratio": 0.04, "color": "#112233"})
        adapted = adapt_elements([entry], SQUARE, LINKEDIN)[0]
        self.assertEqual(adapted["style"], {"font_size_ratio": 0.04, "color": "#112233"})
        self.assertEqual(adapted["id"], entry["id"])
        self.assertEqual(adapted["transform"]["rotation"], 0)
        self.assertEqual(adapted["transform"]["z_index"], 0)

    # -- the flyer-to-square regression --------------------------------------
    # A tall A4 flyer squeezed into a square compresses its height to 54%
    # while the shorter-side ratio says 76%. The first version scaled boxes by
    # 76% and stacked fifteen hundred pixels of layout into a thousand — every
    # element overlapped its neighbours. Contain scaling is the fix, and these
    # tests are what "not messy" means, written down.

    def test_tall_flyer_into_square_keeps_the_stack_apart(self):
        """A vertical stack that fit the flyer must still be a vertical
        stack on the square — order kept, no two entries overlapping."""
        stack = [
            element(0.1, 0.05, 0.8, 0.10),  # heading
            element(0.1, 0.20, 0.8, 0.30),  # photo
            element(0.1, 0.55, 0.8, 0.20),  # body copy
            element(0.1, 0.90, 0.8, 0.05),  # footer
        ]
        adapted = [entry["transform"] for entry in adapt_elements(stack, FLYER, SQUARE)]
        for above, below in zip(adapted, adapted[1:]):
            self.assertLessEqual(
                above["y"] + above["height"], below["y"] + 1e-6,
                f"{above} overlaps {below}",
            )

    def test_tall_flyer_content_still_fits_the_square(self):
        """Contain scaling means nothing can be pushed off the canvas: what
        was inside the flyer page stays inside the square page."""
        stack = [element(0.1, 0.05, 0.8, 0.1), element(0.1, 0.9, 0.8, 0.08)]
        for entry in adapt_elements(stack, FLYER, SQUARE):
            transform = entry["transform"]
            self.assertGreaterEqual(transform["x"], -1e-6)
            self.assertGreaterEqual(transform["y"], -1e-6)
            self.assertLessEqual(transform["x"] + transform["width"], 1 + 1e-6)
            self.assertLessEqual(transform["y"] + transform["height"], 1 + 1e-6)

    def test_a_circle_survives_the_tall_to_square_trip(self):
        """Uniform scaling holds in the compressed direction too — a 200px
        circle on the flyer is still a circle on the square."""
        transform = self.adapt_one(
            element(0.45, 0.45, 200 / 1414, 200 / 2000), FLYER, SQUARE
        )
        self.assertAlmostEqual(
            transform["width"] * SQUARE.width,
            transform["height"] * SQUARE.height,
            places=6,
        )

    def test_type_shrinks_with_its_box_when_an_axis_compresses(self):
        """Flyer to square: boxes scale by 1080/2000 = 0.54 but type's scale
        reference only drops to 1080/1414 = 0.76 — so font_size_ratio must be
        corrected by 0.54 x 1414/1080, or the text outgrows its shrunken box."""
        entry = element(0.1, 0.1, 0.5, 0.1, style={"font_size_ratio": 0.04})
        adapted = adapt_elements([entry], FLYER, SQUARE)[0]
        expected = 0.04 * (1080 / 2000) * 1414 / 1080
        self.assertAlmostEqual(adapted["style"]["font_size_ratio"], expected, places=9)

    def test_story_top_maps_to_the_safe_area_top(self):
        """Anchoring works in safe-page space: the top of a square post lands
        at the top of the Story's SAFE area, not under the platform chrome
        the insets exist to avoid."""
        transform = self.adapt_one(element(0.05, 0.0, 0.3, 0.1), SQUARE, STORY)
        self.assertAlmostEqual(transform["y"], 0.0, places=6)

    def test_output_never_leaves_the_documents_limits(self):
        """Whatever the maths says, the result must be saveable — the same
        clamp-not-reject stance the import pipeline takes."""
        transform = self.adapt_one(element(-1.9, -1.9, 3.5, 3.5), FLYER, LINKEDIN)
        for field, low, high in (
            ("x", -2.0, 3.0),
            ("y", -2.0, 3.0),
            ("width", 0.001, 4.0),
            ("height", 0.001, 4.0),
        ):
            self.assertGreaterEqual(transform[field], low, field)
            self.assertLessEqual(transform[field], high, field)


class AdaptEndpointTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()  # default_dimension: instagram_post
        self.listing = self.make_verified_listing(self.profile, self.agent)
        self.design = self.make_design(self.template, self.profile, self.listing)
        self.authenticate_as(self.agent)

    def adapt(self, payload):
        return self.client.post(
            self.design_action_url(self.design, "adapt"), payload, format="json"
        )

    def test_adapt_creates_a_new_design_composed_for_the_target(self):
        response = self.adapt({"dimension": "linkedin"})

        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotEqual(response.data["id"], self.design.pk)
        self.assertEqual(response.data["preferred_dimension"], "linkedin")
        self.assertEqual(response.data["name"], "Test Design — LinkedIn")

        copy = Design.objects.get(pk=response.data["id"])
        self.assertEqual(copy.listing_id, self.design.listing_id)
        self.assertEqual(len(copy.elements), len(self.design.elements))
        # Every element is re-identified, same rule as duplicate.
        self.assertFalse(
            {e["id"] for e in copy.elements} & {e["id"] for e in self.design.elements}
        )
        # The fixture badge sits in the top-left third: its margins must have
        # scaled with the badge, not stretched with the canvas.
        badge = self.element_of(copy, "badge")
        scale = 627 / 1080
        self.assertAlmostEqual(
            badge["transform"]["x"] * 1200, 0.06 * 1080 * scale, places=4
        )
        # The original design is untouched.
        self.design.refresh_from_db()
        self.assertEqual(self.element_of(self.design, "badge")["transform"]["x"], 0.06)

    def test_adapting_to_the_native_format_is_refused(self):
        response = self.adapt({"dimension": "instagram_post"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("already composed", response.data["detail"])

    def test_an_adapted_copy_adapts_from_its_own_format(self):
        """A copy composed for LinkedIn is LinkedIn-shaped, whatever its
        template says. Re-adapting it must start from that fact: to LinkedIn
        there is nothing to do, and onward to Facebook the source is LinkedIn
        — not the template's native square, which would re-adapt geometry
        that has already moved and scramble it."""
        first = self.adapt({"dimension": "linkedin"})
        copy = Design.objects.get(pk=first.data["id"])

        again = self.client.post(
            self.design_action_url(copy, "adapt"), {"dimension": "linkedin"}, format="json"
        )
        self.assertEqual(again.status_code, 400)
        self.assertIn("already composed", again.data["detail"])

        onward = self.client.post(
            self.design_action_url(copy, "adapt"), {"dimension": "facebook"}, format="json"
        )
        self.assertEqual(onward.status_code, 201, onward.data)
        self.assertEqual(onward.data["preferred_dimension"], "facebook")

    def test_unknown_dimension_is_refused(self):
        response = self.adapt({"dimension": "tiktok"})
        self.assertEqual(response.status_code, 400)

    def test_a_custom_name_is_honoured(self):
        response = self.adapt({"dimension": "facebook", "name": "FB version"})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["name"], "FB version")

    def test_someone_elses_design_cannot_be_adapted(self):
        other, _profile = self.make_agent_in(self.acme, "b@example.com")
        self.authenticate_as(other)
        response = self.adapt({"dimension": "linkedin"})
        self.assertEqual(response.status_code, 404)
