"""Importing artwork (a PDF page or an image) into an editable template.

The vision call is stubbed throughout — these tests are about everything
around it: rasterising an upload, converting a model's pixel measurements into
the template's fractional coordinate space, cutting the photo regions out of
the page, and keeping one agent's imported artwork out of another's gallery.

The one thing deliberately NOT asserted is extraction quality. Whether the
model finds 38 elements or 41 on a given flyer is the provider's behaviour, not
this codebase's; what is tested is that whatever it returns is clamped, mapped
and stored correctly — including when it returns nonsense.
"""

from __future__ import annotations

import io
import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image
from rest_framework import status

from apps.ai_content.client import AIGenerationError, CompletionResult
from apps.templates.dimensions import SOCIAL_DIMENSIONS
from apps.templates.document import elements_from_template
from apps.templates.importing import (
    RasterPage,
    TemplateImportError,
    align_and_group,
    bake_assets,
    build_template,
    closest_dimension,
    normalise_elements,
    rasterise,
    run_import,
)
from apps.templates.models import (
    ElementType,
    ImportStatus,
    Template,
    TemplateCategory,
    TemplateImport,
    TemplateStyle,
)
from apps.templates.tests.base import TemplateAPITestCase

MEDIA_ROOT = tempfile.mkdtemp(prefix="real-estate-import-media-")

imports_url = reverse("templates:templateimport-list")


def import_detail_url(job) -> str:
    return reverse("templates:templateimport-detail", args=[job.pk])


def make_page_png(width: int = 800, height: int = 1000) -> bytes:
    """A page with two visibly different regions, so a crop can be checked.

    Left half red, right half blue. A crop taken from the right half whose
    pixels come back red would mean the crop box was measured against a
    different coordinate space than the one it was reported in — which is the
    failure mode worth having a fixture for.
    """
    image = Image.new("RGB", (width, height), "#FF0000")
    image.paste(Image.new("RGB", (width // 2, height), "#0000FF"), (width // 2, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


PAGE_PNG = make_page_png()


def element_payload(**overrides) -> dict:
    """One element as the model returns it — every key present, as strict
    mode requires."""
    payload = {
        "id": "e1",
        "type": "text",
        "role": "price",
        "binding": "price",
        "text": "$895,000",
        "transform": {
            "x": 80.0,
            "y": 200.0,
            "width": 400.0,
            "height": 50.0,
            "rotation": 0.0,
            "z_index": 5,
        },
        "style": {
            "color": "#1F2937",
            "background_color": "",
            "font_size_px": 40.0,
            "font_weight": "700",
            "text_align": "left",
            "text_transform": "uppercase",
            "line_height": 1.2,
            "opacity": 1.0,
            "border_radius_px": 0.0,
        },
    }
    for key, value in overrides.items():
        if key in ("transform", "style") and isinstance(value, dict):
            payload[key] = {**payload[key], **value}
        else:
            payload[key] = value
    return payload


def layout_payload(elements=None) -> dict:
    return {
        "page": {"background_color": "#FFFFFF", "suggested_name": "Find Comfort"},
        "elements": elements if elements is not None else [element_payload()],
    }


def completion(payload: dict) -> CompletionResult:
    return CompletionResult(
        payload=payload,
        raw_text="{}",
        model="gpt-4o",
        prompt_tokens=1200,
        completion_tokens=3400,
        total_tokens=4600,
        duration_ms=41000,
    )


# ---------------------------------------------------------------------------
# Step 1 — rasterise
# ---------------------------------------------------------------------------


class RasteriseTestCase(TemplateAPITestCase):
    def test_png_is_normalised_and_measured(self):
        page = rasterise(PAGE_PNG, "flyer.png")

        self.assertEqual((page.width, page.height), (800, 1000))
        # Re-encoded, not passed through: the cropper and the model must agree
        # on one coordinate space.
        with Image.open(io.BytesIO(page.png)) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (800, 1000))

    def test_oversized_image_is_downscaled_to_the_configured_edge(self):
        with override_settings(TEMPLATE_IMPORT_RASTER_MAX_EDGE=512):
            page = rasterise(make_page_png(4000, 5000), "huge.png")

        self.assertEqual(max(page.width, page.height), 512)
        # Aspect must survive, or every extracted box is stretched.
        self.assertAlmostEqual(page.width / page.height, 0.8, places=2)

    def test_empty_file_is_refused(self):
        with self.assertRaises(TemplateImportError):
            rasterise(b"", "empty.png")

    def test_unreadable_file_is_refused_with_a_usable_message(self):
        with self.assertRaises(TemplateImportError) as caught:
            rasterise(b"this is not an image at all", "notes.txt")
        self.assertIn("PDF", str(caught.exception))

    def test_tiny_image_is_refused_rather_than_extracted_from(self):
        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), "#FFFFFF").save(buffer, format="PNG")
        with self.assertRaises(TemplateImportError) as caught:
            rasterise(buffer.getvalue(), "tiny.png")
        self.assertIn("too small", str(caught.exception))

    def test_pdf_first_page_is_rendered(self):
        try:
            import pymupdf
        except ImportError:  # pragma: no cover - depends on the installed wheel
            self.skipTest("PyMuPDF is not installed")

        document = pymupdf.open()
        # A4 in points, and a second page that must be ignored.
        document.new_page(width=595, height=842)
        document.new_page(width=595, height=842)
        data = document.tobytes()

        with override_settings(TEMPLATE_IMPORT_RASTER_MAX_EDGE=1000):
            page = rasterise(data, "flyer.pdf")

        self.assertEqual(max(page.width, page.height), 1000)
        self.assertAlmostEqual(page.width / page.height, 595 / 842, places=2)
        self.assertTrue(page.png.startswith(b"\x89PNG"))

    def test_pdf_is_detected_from_its_bytes_not_its_name(self):
        """A PDF named .png must still import; the extension is client input."""
        try:
            import pymupdf
        except ImportError:  # pragma: no cover
            self.skipTest("PyMuPDF is not installed")

        document = pymupdf.open()
        document.new_page(width=400, height=600)

        page = rasterise(document.tobytes(), "actually-a-pdf.png")
        self.assertAlmostEqual(page.width / page.height, 400 / 600, places=2)


# ---------------------------------------------------------------------------
# Step 2/3 — converting what the model returned
# ---------------------------------------------------------------------------


class NormaliseElementsTestCase(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.page = RasterPage(png=PAGE_PNG, width=800, height=1000)

    def test_pixels_become_fractions_of_the_page(self):
        [element] = normalise_elements(layout_payload(), self.page)

        self.assertEqual(element.geometry["x"], 0.1)  # 80 / 800
        self.assertEqual(element.geometry["y"], 0.2)  # 200 / 1000
        self.assertEqual(element.geometry["width"], 0.5)
        self.assertEqual(element.geometry["height"], 0.05)

    def test_font_size_is_scaled_against_the_shorter_side(self):
        """Matches html_builder's type scale — min(width, height), not height.

        Getting this wrong is invisible at the imported aspect ratio and
        breaks the moment the same template is exported square.
        """
        [element] = normalise_elements(layout_payload(), self.page)
        self.assertEqual(element.style_properties["font_size_ratio"], 0.05)  # 40 / 800

    def test_binding_becomes_a_content_source_and_a_format(self):
        [element] = normalise_elements(layout_payload(), self.page)

        self.assertEqual(element.content_source, "property.price")
        self.assertEqual(element.style_properties["format"], "currency")
        self.assertEqual(element.default_content, "$895,000")

    def test_photo_regions_carry_a_crop_box_and_no_text(self):
        payload = layout_payload(
            [
                element_payload(
                    id="hero",
                    type="image",
                    role="hero_property_photo",
                    binding="photo_1",
                    # A model that ignores the instruction and describes the
                    # photo must not have that description stored as content.
                    text="A large modern house with a palm tree",
                    transform={"x": 0, "y": 300, "width": 660, "height": 520},
                )
            ]
        )
        [element] = normalise_elements(payload, self.page)

        self.assertEqual(element.element_type, ElementType.IMAGE)
        self.assertEqual(element.content_source, "property.photos[0]")
        self.assertEqual(element.default_content, "")
        self.assertEqual(element.crop_box, (0, 300, 660, 820))
        self.assertEqual(element.style_properties["object_fit"], "cover")

    def test_icons_are_baked_artwork_with_no_binding(self):
        payload = layout_payload(
            [element_payload(id="i1", type="icon", role="feature_icon_bed", binding="", text="")]
        )
        [element] = normalise_elements(payload, self.page)

        self.assertEqual(element.element_type, ElementType.STATIC_GRAPHIC)
        self.assertEqual(element.content_source, "")
        # Contain, not cover: an icon cropped to fill its box loses its shape.
        self.assertEqual(element.style_properties["object_fit"], "contain")

    def test_a_logo_binds_to_the_brokerage_even_unprompted(self):
        payload = layout_payload(
            [element_payload(id="l1", type="logo", role="logo", binding="", text="")]
        )
        [element] = normalise_elements(payload, self.page)
        self.assertEqual(element.content_source, "brokerage.logo")

    def test_an_outline_becomes_a_clip_relative_to_the_element(self):
        """Measured against the page, applied to the element.

        The conversion is the whole point: a shape left in page pixels would
        stop matching its element the moment the design rendered at another
        size.
        """
        payload = layout_payload(
            [
                element_payload(
                    id="hero",
                    type="image",
                    role="hero",
                    binding="photo_1",
                    text="",
                    transform={"x": 100, "y": 200, "width": 400, "height": 400},
                    # A triangle covering the left half of the element's box.
                    mask=[100, 200, 300, 200, 100, 600],
                )
            ]
        )
        [element] = normalise_elements(payload, self.page)

        self.assertEqual(
            element.style_properties["clip_polygon"], [0.0, 0.0, 50.0, 0.0, 0.0, 100.0]
        )

    def test_an_outline_applies_to_a_shape_that_is_never_cropped(self):
        """Angled colour panels are as common as angled photos.

        A shape gets the clip without getting any pixels — which is what stops
        an angled footer panel being baked from the page along with whatever
        text was printed on top of it.
        """
        payload = layout_payload(
            [
                element_payload(
                    id="panel",
                    type="shape",
                    role="footer_panel",
                    binding="",
                    text="",
                    transform={"x": 0, "y": 0, "width": 800, "height": 1000},
                    style={"background_color": "#36332F"},
                    mask=[400, 0, 800, 0, 800, 1000, 0, 1000],
                )
            ]
        )
        [element] = normalise_elements(payload, self.page)

        self.assertEqual(element.element_type, ElementType.COLOR_BLOCK)
        self.assertIsNone(element.crop_box)
        self.assertEqual(element.style_properties["background_color"], "#36332F")
        self.assertEqual(len(element.style_properties["clip_polygon"]), 8)

    def test_a_malformed_outline_yields_no_clip_at_all(self):
        """Half an outline would punch a hole through the middle of a photo.

        Worse than the square edge it was meant to replace, and much harder to
        recognise as a data problem.
        """
        for broken in ([1, 2, 3], [1, 2], "polygon(0 0)", [1, 2, 3, 4, "x", 6], None):
            payload = layout_payload(
                [element_payload(id="p", type="image", role="hero", text="", mask=broken)]
            )
            [element] = normalise_elements(payload, self.page)
            self.assertNotIn(
                "clip_polygon", element.style_properties, f"mask={broken!r}"
            )

    def test_a_condensed_headline_keeps_its_font_role(self):
        payload = layout_payload(
            [element_payload(id="h", role="headline", binding="", style={"font_family": "display"})]
        )
        [element] = normalise_elements(payload, self.page)
        self.assertEqual(element.style_properties["font_family"], "display")

    def test_an_unknown_font_role_is_dropped_rather_than_passed_through(self):
        payload = layout_payload(
            [element_payload(id="h", role="headline", binding="", style={"font_family": "Comic Sans"})]
        )
        [element] = normalise_elements(payload, self.page)
        self.assertNotIn("font_family", element.style_properties)

    def test_a_logo_is_never_baked_from_the_source_artwork(self):
        """The one crop that is refused, and not for fidelity reasons.

        A baked logo would export an asset carrying whoever's brand was on the
        source file, and — since readiness counts a stored image as present —
        would do it without tripping the gate that exists to stop exactly that.
        """
        payload = layout_payload(
            [element_payload(id="l1", type="logo", role="logo", binding="", text="")]
        )
        elements = normalise_elements(payload, self.page)

        self.assertIsNone(elements[0].crop_box)
        self.assertEqual(bake_assets(elements, self.page), 0)

    def test_type_and_shape_are_mapped_onto_template_storage(self):
        payload = layout_payload(
            [
                element_payload(id="a", type="shape", role="panel", binding="", text=""),
                element_payload(id="b", type="line", role="rule", binding="", text=""),
                element_payload(id="c", type="button", role="cta", binding="", text="Call"),
                element_payload(id="d", type="background", role="page", binding="", text=""),
            ]
        )
        kinds = [e.element_type for e in normalise_elements(payload, self.page)]
        self.assertEqual(
            kinds,
            [
                ElementType.COLOR_BLOCK,
                ElementType.DIVIDER,
                ElementType.BADGE,
                ElementType.COLOR_BLOCK,
            ],
        )

    def test_out_of_range_numbers_are_clamped_not_rejected(self):
        """A model's answer is untrusted input that happens to parse.

        One absurd number must cost that element its accuracy, not cost the
        user the whole import.
        """
        payload = layout_payload(
            [
                element_payload(
                    id="wild",
                    transform={"rotation": 9999.0, "z_index": 100000},
                    style={"font_size_px": 99999.0, "opacity": -4.0},
                )
            ]
        )
        [element] = normalise_elements(payload, self.page)

        self.assertLessEqual(element.geometry["rotation"], 360)
        self.assertLessEqual(element.z_index, 999)
        self.assertLessEqual(element.style_properties["font_size_ratio"], 0.6)

    def test_unusable_elements_are_skipped_and_the_rest_survive(self):
        payload = layout_payload(
            [
                "not an object",
                element_payload(id="bad-type", type="hologram"),
                element_payload(id="zero", transform={"width": 0.0}),
                {"id": "no-transform", "type": "text"},
                element_payload(id="good", role="headline", binding="", text="Hello"),
            ]
        )
        elements = normalise_elements(payload, self.page)

        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0].default_content, "Hello")

    def test_a_bad_colour_is_dropped_rather_than_defaulted(self):
        payload = layout_payload(
            [element_payload(style={"color": "red; background-image:url(http://x)"})]
        )
        [element] = normalise_elements(payload, self.page)
        self.assertNotIn("color", element.style_properties)

    def test_an_empty_response_fails_with_something_actionable(self):
        with self.assertRaises(TemplateImportError) as caught:
            normalise_elements(layout_payload([]), self.page)
        self.assertIn("resolution", str(caught.exception))

    def test_element_keys_are_unique_even_when_roles_repeat(self):
        payload = layout_payload(
            [element_payload(id=str(n), role="feature_icon") for n in range(4)]
        )
        elements = normalise_elements(payload, self.page)
        self.assertEqual(len({e.key for e in elements}), 4)


class BakeAssetsTestCase(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.page = RasterPage(png=PAGE_PNG, width=800, height=1000)

    def test_a_crop_comes_from_the_region_it_was_measured_at(self):
        payload = layout_payload(
            [
                element_payload(
                    id="right",
                    type="image",
                    role="interior",
                    binding="photo_2",
                    text="",
                    # Entirely inside the blue right half of the fixture.
                    transform={"x": 500, "y": 100, "width": 200, "height": 200},
                )
            ]
        )
        elements = normalise_elements(payload, self.page)
        self.assertEqual(bake_assets(elements, self.page), 1)

        with Image.open(io.BytesIO(elements[0].asset.read())) as crop:
            self.assertEqual(crop.size, (200, 200))
            self.assertEqual(crop.convert("RGB").getpixel((10, 10)), (0, 0, 255))

    def test_a_box_running_off_the_page_is_clipped_not_dropped(self):
        payload = layout_payload(
            [
                element_payload(
                    id="bleed",
                    type="image",
                    role="hero",
                    binding="photo_1",
                    text="",
                    transform={"x": 600, "y": 900, "width": 600, "height": 400},
                )
            ]
        )
        elements = normalise_elements(payload, self.page)
        self.assertEqual(elements[0].crop_box, (600, 900, 800, 1000))
        self.assertEqual(bake_assets(elements, self.page), 1)

    def test_text_elements_are_never_baked(self):
        elements = normalise_elements(layout_payload(), self.page)
        self.assertEqual(bake_assets(elements, self.page), 0)
        self.assertIsNone(elements[0].asset)

    def test_a_flat_page_background_is_not_baked(self):
        """The prompt asks the model to report background panels, so a plain
        page ground arrives on most artwork.

        Cropping one bakes a picture of the whole flyer — every heading, price
        and photo — and parks it behind the editable layout, so the canvas
        shows each text twice: once as pixels nobody can retype, once as the
        real element.
        """
        payload = layout_payload(
            [
                element_payload(
                    id="ground",
                    type="background",
                    role="page_background",
                    binding="",
                    text="",
                    transform={"x": 0, "y": 0, "width": 800, "height": 1000},
                    style={"background_color": "#ECE3D9"},
                )
            ]
        )
        elements = normalise_elements(payload, self.page)

        self.assertEqual(elements[0].element_type, ElementType.COLOR_BLOCK)
        self.assertIsNone(elements[0].crop_box)
        self.assertEqual(bake_assets(elements, self.page), 0)

    def test_a_photographic_background_is_still_baked(self):
        """The other half of the rule: a background the model bound to a photo
        is a real image and keeps its pixels."""
        payload = layout_payload(
            [
                element_payload(
                    id="ground",
                    type="background",
                    role="page_background",
                    binding="photo_1",
                    text="",
                    transform={"x": 0, "y": 0, "width": 800, "height": 1000},
                )
            ]
        )
        elements = normalise_elements(payload, self.page)

        self.assertEqual(elements[0].element_type, ElementType.IMAGE)
        self.assertIsNotNone(elements[0].crop_box)
        self.assertEqual(bake_assets(elements, self.page), 1)


class ClipPolygonSafetyTestCase(TemplateAPITestCase):
    """``clip-path`` takes a *function*, which is the interesting part.

    ``background_gradient`` is matched whole against a grammar precisely
    because ``background-image`` can carry a ``url(...)`` out of the renderer.
    ``clip-path`` is the same shape of hazard, and is closed a different and
    stronger way: the element stores numbers, never a string, so there is no
    grammar to get wrong — ``html_builder`` writes the CSS itself.
    """

    def test_a_css_string_is_refused_outright(self):
        from apps.templates.document import DocumentValidationError, validate_element

        for attack in (
            "polygon(0% 0%, 100% 0%)",
            "url(https://elsewhere.example/x)",
            "polygon(0 0);background-image:url(https://elsewhere.example/x)",
        ):
            with self.assertRaises(DocumentValidationError, msg=attack):
                validate_element(
                    {
                        "id": "el-1",
                        "type": "shape",
                        "transform": {"x": 0, "y": 0, "width": 0.5, "height": 0.5},
                        "style": {"clip_polygon": attack},
                    },
                    seen_ids=set(),
                )

    def test_non_numeric_points_are_refused(self):
        from apps.templates.document import DocumentValidationError, validate_element

        with self.assertRaises(DocumentValidationError):
            validate_element(
                {
                    "id": "el-1",
                    "type": "shape",
                    "transform": {"x": 0, "y": 0, "width": 0.5, "height": 0.5},
                    "style": {"clip_polygon": [0, 0, 100, 0, "50%", 100]},
                },
                seen_ids=set(),
            )

    def test_an_odd_number_of_coordinates_is_refused(self):
        from apps.templates.document import DocumentValidationError, validate_element

        with self.assertRaises(DocumentValidationError):
            validate_element(
                {
                    "id": "el-1",
                    "type": "shape",
                    "transform": {"x": 0, "y": 0, "width": 0.5, "height": 0.5},
                    "style": {"clip_polygon": [0, 0, 100, 0, 100]},
                },
                seen_ids=set(),
            )

    def test_the_rendered_css_is_built_from_numbers(self):
        from apps.templates.html_builder import _clip_path

        css = _clip_path([0, 0, 100, 0, 100, 100])
        self.assertEqual(
            css, "clip-path:polygon(0.000% 0.000%,100.000% 0.000%,100.000% 100.000%)"
        )
        # Anything that is not a usable list of pairs produces no declaration
        # rather than a partial one.
        for junk in ("polygon(0 0)", [1, 2], [1, 2, 3], None, {}):
            self.assertEqual(_clip_path(junk), "", repr(junk))


class FontRoleTestCase(TemplateAPITestCase):
    def test_a_role_resolves_to_an_installed_stack(self):
        from apps.templates.html_builder import FONT_STACKS, font_stack

        self.assertIn("Roboto Condensed", font_stack({"font_family": "display"}))
        # An unknown or absent role must not fall through to whatever
        # fontconfig picks — that is how an export stops matching the editor.
        self.assertEqual(font_stack({}), FONT_STACKS["body"])
        self.assertEqual(font_stack({"font_family": "Papyrus"}), FONT_STACKS["body"])

    def test_the_document_only_accepts_known_roles(self):
        from apps.templates.document import DocumentValidationError, validate_element

        with self.assertRaises(DocumentValidationError):
            validate_element(
                {
                    "id": "el-1",
                    "type": "text",
                    "transform": {"x": 0, "y": 0, "width": 0.5, "height": 0.5},
                    "style": {"font_family": "'Comic Sans MS', cursive"},
                },
                seen_ids=set(),
            )


class ClosestDimensionTestCase(TemplateAPITestCase):
    def test_a4_portrait_artwork_opens_as_a_flyer(self):
        self.assertEqual(closest_dimension(1414, 2000), "flyer_portrait")

    def test_square_artwork_opens_as_a_post(self):
        self.assertEqual(closest_dimension(1080, 1080), "instagram_post")

    def test_a_wide_banner_opens_at_a_wide_format(self):
        self.assertIn(closest_dimension(1200, 630), ("facebook", "linkedin"))

    def test_an_unrecognisable_shape_falls_back_rather_than_being_forced(self):
        # 5:1 is nothing in SOCIAL_DIMENSIONS; forcing it into the nearest
        # would crop the composition without saying so.
        self.assertEqual(closest_dimension(2000, 400), "instagram_post")


# ---------------------------------------------------------------------------
# Step 2b — smart geometry (size-aware snap, spacing, alignment, crop)
# ---------------------------------------------------------------------------


def _box(eid, x, y, w, h, kind="text"):
    """A minimal aligned-payload element in pixel space."""
    return {
        "id": eid,
        "type": kind,
        "role": "",
        "binding": "",
        "text": "x",
        "mask": [],
        "transform": {"x": x, "y": y, "width": w, "height": h, "rotation": 0, "z_index": 0},
        "style": {},
    }


@override_settings(TEMPLATE_IMPORT_SMART_GEOMETRY=True)
class SmartGeometryTestCase(TemplateAPITestCase):
    """The deterministic tidy-up that runs on either reader's output.

    Pixel space, since ``align_and_group`` runs before normalisation converts
    to fractions. The page is 1000x1000, so the snap tolerance is 5px.
    """

    W = H = 1000

    def align(self, elements):
        payload = {"page": {}, "elements": elements}
        return align_and_group(payload, self.W, self.H, smart=True)["elements"]

    def test_a_column_of_near_equal_cards_is_given_one_shared_edge(self):
        # Two left-aligned cards whose right edges are 3px apart were meant to
        # line up. Position-only snapping cannot fix this — the widths differ.
        a = _box("a", 100, 100, 400, 50, "image")
        b = _box("b", 100, 200, 403, 50, "image")
        self.align([a, b])
        self.assertEqual(a["transform"]["width"], b["transform"]["width"])
        self.assertAlmostEqual(
            a["transform"]["x"] + a["transform"]["width"],
            b["transform"]["x"] + b["transform"]["width"],
            places=2,
        )

    def test_genuinely_different_widths_are_left_alone(self):
        # Right edges 200px apart: a design decision, not placement slop.
        a = _box("a", 100, 100, 400, 50, "image")
        b = _box("b", 100, 200, 600, 50, "image")
        self.align([a, b])
        self.assertEqual(a["transform"]["width"], 400)
        self.assertEqual(b["transform"]["width"], 600)

    def test_a_nearly_even_column_is_regularised_to_one_rhythm(self):
        # Gaps of 24 / 24 / 25 px collapse to a single mean gap.
        run = [
            _box("t1", 100, 0, 200, 50),
            _box("t2", 100, 74, 200, 50),
            _box("t3", 100, 148, 200, 50),
            _box("t4", 100, 223, 200, 50),
        ]
        self.align(run)
        ys = [e["transform"]["y"] for e in run]
        gaps = [ys[i + 1] - (ys[i] + 50) for i in range(3)]
        self.assertLess(max(gaps) - min(gaps), 0.05)

    def test_an_intentionally_uneven_column_is_preserved(self):
        run = [
            _box("t1", 100, 0, 200, 50),
            _box("t2", 100, 60, 200, 50),
            _box("t3", 100, 150, 200, 50),
        ]
        before = [e["transform"]["y"] for e in run]
        self.align(run)
        self.assertEqual([e["transform"]["y"] for e in run], before)

    def test_confident_alignment_is_recorded_as_a_relationship(self):
        a = _box("a", 100, 100, 200, 50)
        b = _box("b", 100, 300, 200, 50)
        self.align([a, b])
        left = a["style"].get("layout_constraints", {}).get("align_left_with", [])
        self.assertIn("b", left)

    def test_recorded_relationships_survive_normalisation_as_stored_keys(self):
        # align_and_group records peers by the reader's throwaway ids; after
        # normalisation those must point at the keys actually stored, or the
        # relationship references nothing.
        page = RasterPage(png=PAGE_PNG, width=800, height=1000)
        payload = {
            "page": {"background_color": "#FFFFFF"},
            "elements": [
                _box("raw_a", 100, 100, 200, 50),
                _box("raw_b", 100, 300, 200, 50),
            ],
        }
        align_and_group(payload, 800, 1000, smart=True)
        elements = normalise_elements(payload, page)
        keys = {e.key for e in elements}
        for element in elements:
            for peers in (element.style_properties.get("layout_constraints") or {}).values():
                for peer in peers:
                    self.assertIn(peer, keys)
                    self.assertNotIn(peer, {"raw_a", "raw_b"})

    @override_settings(TEMPLATE_IMPORT_SMART_GEOMETRY=False)
    def test_the_flag_off_is_exactly_the_old_behaviour(self):
        # No size changes, no relationships — only the original position snap.
        a = _box("a", 100, 100, 400, 50, "image")
        b = _box("b", 100, 200, 403, 50, "image")
        self.align([a, b])
        self.assertEqual(a["transform"]["width"], 400)
        self.assertEqual(b["transform"]["width"], 403)
        self.assertNotIn("layout_constraints", a["style"])


@override_settings(TEMPLATE_IMPORT_SMART_GEOMETRY=True)
class TextFitTestCase(TemplateAPITestCase):
    """A text box measured too tight for the substitute font is widened.

    Page is 800x1000, so the type scale reference is 800px.
    """

    def setUp(self):
        super().setUp()
        self.page = RasterPage(png=PAGE_PNG, width=800, height=1000)

    def _price(self, width, align="left", x=80.0):
        return layout_payload(
            [
                element_payload(
                    id="price",
                    type="text",
                    role="price",
                    binding="",
                    text="$1,300,000",
                    transform={"x": x, "y": 500.0, "width": width, "height": 90.0},
                    style={"font_size_px": 80.0, "text_align": align},
                )
            ]
        )

    def test_a_too_narrow_price_box_is_widened_to_fit(self):
        # 10 glyphs at ~80px in the substitute body font need ~470px; the box is
        # 200px, which is what clips "$1,300,000" to "$1,300,00".
        [element] = normalise_elements(self._price(200.0), self.page)
        self.assertGreater(element.geometry["width"], 200.0 / 800.0)

    def test_a_box_already_wide_enough_is_left_alone(self):
        [element] = normalise_elements(self._price(700.0), self.page)
        self.assertAlmostEqual(element.geometry["width"], 700.0 / 800.0, places=3)

    def test_a_right_aligned_box_grows_leftward_keeping_its_right_edge(self):
        before = self._price(200.0, align="right", x=500.0)
        right_before = 500.0 + 200.0
        [element] = normalise_elements(before, self.page)
        right_after = (element.geometry["x"] + element.geometry["width"]) * 800.0
        self.assertLess(element.geometry["x"] * 800.0, 500.0)
        self.assertAlmostEqual(right_after, right_before, delta=3.0)

    def test_widening_never_leaves_the_canvas(self):
        [element] = normalise_elements(self._price(200.0, x=700.0), self.page)
        right = (element.geometry["x"] + element.geometry["width"]) * 800.0
        self.assertLessEqual(right, 800.0 + 0.5)

    @override_settings(TEMPLATE_IMPORT_SMART_GEOMETRY=False)
    def test_the_flag_off_leaves_the_box_as_measured(self):
        [element] = normalise_elements(self._price(200.0), self.page)
        self.assertAlmostEqual(element.geometry["width"], 200.0 / 800.0, places=3)


@override_settings(TEMPLATE_IMPORT_SMART_GEOMETRY=True)
class CropPreservationTestCase(TemplateAPITestCase):
    """A photo whose box bleeds off the page keeps its visible composition."""

    def setUp(self):
        super().setUp()
        self.page = RasterPage(png=PAGE_PNG, width=800, height=1000)

    def test_a_bleeding_photo_renders_the_region_that_is_actually_there(self):
        # A hero photo running 100px off the right and bottom edges. The crop is
        # clamped to the page; the render geometry must follow it, or cover
        # would slide the visible region.
        payload = layout_payload(
            [
                element_payload(
                    id="hero",
                    type="image",
                    role="hero",
                    binding="photo_1",
                    text="",
                    transform={"x": 600.0, "y": 700.0, "width": 300.0, "height": 400.0},
                )
            ]
        )
        [element] = normalise_elements(payload, self.page)
        # Visible width is 800-600=200 of 800 -> 0.25; height 1000-700=300 -> 0.30.
        self.assertAlmostEqual(element.geometry["width"], 0.25, places=3)
        self.assertAlmostEqual(element.geometry["height"], 0.30, places=3)
        self.assertIn("source_box", element.style_properties)

    def test_a_photo_inside_the_page_is_geometry_unchanged(self):
        payload = layout_payload(
            [
                element_payload(
                    id="p",
                    type="image",
                    role="photo",
                    binding="photo_1",
                    text="",
                    transform={"x": 100.0, "y": 100.0, "width": 200.0, "height": 200.0},
                )
            ]
        )
        [element] = normalise_elements(payload, self.page)
        self.assertAlmostEqual(element.geometry["x"], 0.125, places=3)
        self.assertAlmostEqual(element.geometry["width"], 0.25, places=3)
        self.assertNotIn("source_box", element.style_properties)

    def test_a_flat_background_is_never_cropped_into_a_screenshot(self):
        payload = layout_payload(
            [
                element_payload(
                    id="bg", type="background", role="page", binding="", text="",
                    transform={"x": 0.0, "y": 0.0, "width": 800.0, "height": 1000.0},
                )
            ]
        )
        [element] = normalise_elements(payload, self.page)
        self.assertEqual(element.element_type, ElementType.COLOR_BLOCK)
        self.assertIsNone(element.crop_box)


# ---------------------------------------------------------------------------
# Step 4 and the orchestrator
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class BuildTemplateTestCase(TemplateAPITestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.brokerage = self.make_brokerage("Acme Realty")
        self.user, self.profile = self.make_agent_in(self.brokerage, "importer@example.com")
        self.page = RasterPage(png=PAGE_PNG, width=800, height=1000)

    def test_the_template_and_its_elements_are_persisted(self):
        elements = normalise_elements(
            layout_payload(
                [
                    element_payload(id="p", role="price"),
                    element_payload(
                        id="hero", type="image", role="hero", binding="photo_1", text="",
                        transform={"x": 0, "y": 0, "width": 400, "height": 400},
                    ),
                ]
            ),
            self.page,
        )
        bake_assets(elements, self.page)

        template = build_template(
            owner=self.profile,
            name="Find Comfort",
            category=TemplateCategory.NEW_LISTING,
            style=TemplateStyle.MINIMAL,
            page=self.page,
            elements=elements,
            payload=layout_payload(),
        )

        self.assertEqual(template.owner, self.profile)
        self.assertTrue(template.is_imported)
        self.assertEqual(template.elements.count(), 2)
        # The source page becomes the gallery thumbnail.
        self.assertTrue(template.source_image.name)
        self.assertEqual(template.layout_definition["source_width"], 800)
        # The photo region's own pixels were stored against the element.
        hero = template.elements.get(key__startswith="hero")
        self.assertTrue(hero.static_asset.name)

    def test_slugs_do_not_collide_across_repeated_imports(self):
        elements = normalise_elements(layout_payload(), self.page)
        slugs = {
            build_template(
                owner=self.profile,
                name="Same Name",
                category=TemplateCategory.NEW_LISTING,
                style=TemplateStyle.MINIMAL,
                page=self.page,
                elements=elements,
                payload=layout_payload(),
            ).slug
            for _ in range(3)
        }
        self.assertEqual(len(slugs), 3)


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class RunImportTestCase(TemplateAPITestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.brokerage = self.make_brokerage("Acme Realty")
        self.user, self.profile = self.make_agent_in(self.brokerage, "importer@example.com")
        self.job = TemplateImport.objects.create(
            agent=self.profile,
            source_file=SimpleUploadedFile("flyer.png", PAGE_PNG, content_type="image/png"),
            original_filename="flyer.png",
        )

    def test_a_successful_run_records_everything_it_spent(self):
        payload = layout_payload(
            [
                element_payload(id="p", role="price"),
                element_payload(
                    id="hero", type="image", role="hero_photo", binding="photo_1", text="",
                    transform={"x": 0, "y": 0, "width": 400, "height": 400},
                ),
            ]
        )
        with mock.patch(
            "apps.templates.importing.complete_json", return_value=completion(payload)
        ):
            template = run_import(self.job)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, ImportStatus.SUCCEEDED)
        self.assertEqual(self.job.template, template)
        self.assertEqual(self.job.element_count, 2)
        self.assertEqual(self.job.model_used, "gpt-4o")
        self.assertEqual(self.job.prompt_tokens, 1200)
        self.assertIsNotNone(self.job.finished_at)
        self.assertEqual(self.job.error, "")

    def test_the_name_falls_back_to_the_headline_the_model_read(self):
        with mock.patch(
            "apps.templates.importing.complete_json", return_value=completion(layout_payload())
        ):
            template = run_import(self.job)
        self.assertEqual(template.name, "Find Comfort")

    def test_a_requested_name_wins_over_the_suggestion(self):
        self.job.requested_name = "Spring Campaign"
        self.job.save(update_fields=["requested_name"])

        with mock.patch(
            "apps.templates.importing.complete_json", return_value=completion(layout_payload())
        ):
            template = run_import(self.job)
        self.assertEqual(template.name, "Spring Campaign")

    def test_a_provider_failure_becomes_a_message_and_no_template(self):
        with mock.patch(
            "apps.templates.importing.complete_json",
            side_effect=AIGenerationError("upstream 500"),
        ):
            with self.assertRaises(TemplateImportError) as caught:
                run_import(self.job)

        # The provider's own text must not travel to the user.
        self.assertNotIn("500", str(caught.exception))
        self.assertEqual(Template.objects.filter(owner=self.profile).count(), 0)

    def test_the_celery_task_leaves_a_terminal_state_on_failure(self):
        from apps.templates.tasks import import_template_artwork

        with mock.patch(
            "apps.templates.importing.complete_json",
            side_effect=AIGenerationError("upstream 500"),
        ):
            import_template_artwork(self.job.pk)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, ImportStatus.FAILED)
        self.assertTrue(self.job.error)
        self.assertIsNone(self.job.template)

    def test_a_redelivered_task_does_not_re_run_a_finished_job(self):
        """acks_late means a task can arrive twice. The second must be free."""
        from apps.templates.tasks import import_template_artwork

        self.job.status = ImportStatus.SUCCEEDED
        self.job.save(update_fields=["status"])

        with mock.patch("apps.templates.importing.complete_json") as call:
            import_template_artwork(self.job.pk)

        call.assert_not_called()


# ---------------------------------------------------------------------------
# The imported template, in use
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ImportedTemplateInUseTestCase(TemplateAPITestCase):
    """What an imported template does once a design is made from it.

    This is where "the images are extracted" is actually verified: the crop is
    the element's content, so the design opens looking like the artwork — and
    a listing still takes precedence over it, because a flyer that keeps
    showing stock photos after a real property is attached is the failure that
    reaches a client.
    """

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.brokerage = self.make_brokerage("Acme Realty")
        self.user, self.profile = self.make_agent_in(self.brokerage, "importer@example.com")

        page = RasterPage(png=PAGE_PNG, width=800, height=1000)
        elements = normalise_elements(
            layout_payload(
                [
                    element_payload(
                        id="hero", type="image", role="hero_photo", binding="photo_1", text="",
                        transform={"x": 0, "y": 0, "width": 400, "height": 400},
                    )
                ]
            ),
            page,
        )
        bake_assets(elements, page)
        self.template = build_template(
            owner=self.profile,
            name="Imported Flyer",
            category=TemplateCategory.MARKET_UPDATE,
            style=TemplateStyle.MINIMAL,
            page=page,
            elements=elements,
            payload=layout_payload(),
        )

    def test_the_baked_crop_becomes_the_design_element_content(self):
        [element] = elements_from_template(self.template)

        self.assertEqual(element["type"], "image")
        # The crop's storage key, so the canvas has something to draw with no
        # listing attached at all.
        self.assertTrue(element["content"])
        self.assertIn("templates/assets/", element["content"])
        # And the binding survives alongside it.
        self.assertEqual(element["bound_to"], "photo_1")

    def test_a_listing_photo_outranks_the_baked_crop(self):
        from apps.templates.html_builder import resolve_content

        [element] = elements_from_template(self.template)
        context = {"property": {"photos": ["data:image/png;base64,LISTING"]}}

        resolved = resolve_content(
            element, context, {element["id"]: "data:image/png;base64,BAKED"}
        )
        self.assertEqual(resolved, "data:image/png;base64,LISTING")

    def test_the_crop_shows_when_the_binding_has_nothing(self):
        from apps.templates.html_builder import resolve_content

        [element] = elements_from_template(self.template)

        resolved = resolve_content(
            element, {"property": {"photos": []}}, {element["id"]: "data:image/png;base64,BAKED"}
        )
        self.assertEqual(resolved, "data:image/png;base64,BAKED")

    def test_baked_artwork_satisfies_readiness_with_no_listing_attached(self):
        """An imported design must not be blocked over a photo it already has.

        The photo slot carries both a crop of the source page and a binding to
        `listing.photos[0]`. With no listing, the binding resolves to nothing —
        but the design still draws the crop, so calling it "missing a photo"
        would refuse an export of something visibly complete.
        """
        from apps.templates.readiness import assess_design
        from apps.templates.render_context import build_context

        design = self.make_design(self.template, self.profile)
        missing = assess_design(design, build_context(design))

        self.assertEqual([item.label for item in missing], [])

    def test_a_photo_slot_with_no_artwork_is_still_reported(self):
        """The check must not have been weakened into never firing."""
        from apps.templates.readiness import assess_design
        from apps.templates.render_context import build_context

        design = self.make_design(self.template, self.profile)
        # An element bound to a photo with neither a listing nor baked artwork.
        design.elements[0]["content"] = ""
        design.save(update_fields=["elements"])

        missing = assess_design(design, build_context(design))
        self.assertEqual(len(missing), 1)

    def test_an_agent_who_replaces_the_photo_keeps_their_choice(self):
        from apps.templates.html_builder import resolve_content

        [element] = elements_from_template(self.template)
        element["manually_overridden"] = True
        context = {"property": {"photos": ["data:image/png;base64,LISTING"]}}

        resolved = resolve_content(
            element, context, {element["id"]: "data:image/png;base64,CHOSEN"}
        )
        self.assertEqual(resolved, "data:image/png;base64,CHOSEN")


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class TemplateImportAPITestCase(TemplateAPITestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.brokerage = self.make_brokerage("Acme Realty")
        self.user, self.profile = self.make_agent_in(self.brokerage, "importer@example.com")
        self.other_user, self.other_profile = self.make_agent_in(
            self.brokerage, "other@example.com"
        )

    def upload(self, data=PAGE_PNG, name="flyer.png"):
        return self.client.post(
            imports_url,
            {"file": SimpleUploadedFile(name, data, content_type="image/png")},
            format="multipart",
        )

    def test_uploading_queues_a_job_and_returns_it(self):
        self.authenticate_as(self.user)
        with mock.patch("apps.templates.views.import_template_artwork.delay") as queued:
            response = self.upload()

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["status"], ImportStatus.QUEUED)
        self.assertEqual(response.data["original_filename"], "flyer.png")
        self.assertIsNone(response.data["template"])
        queued.assert_called_once()

    def test_a_broken_queue_fails_the_job_rather_than_losing_it(self):
        self.authenticate_as(self.user)
        with mock.patch(
            "apps.templates.views.import_template_artwork.delay",
            side_effect=OSError("no broker"),
        ):
            response = self.upload()

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        job = TemplateImport.objects.get(pk=response.data["id"])
        self.assertEqual(job.status, ImportStatus.FAILED)
        self.assertIn("try importing it again", job.error)
        # The file is still stored, so a retry needs no second upload.
        self.assertTrue(job.source_file.name)

    def test_a_non_image_non_pdf_is_refused_before_a_worker_sees_it(self):
        self.authenticate_as(self.user)
        response = self.client.post(
            imports_url,
            {"file": SimpleUploadedFile("notes.pdf", b"just text", content_type="application/pdf")},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(TemplateImport.objects.exists())

    def test_an_unsupported_extension_is_refused(self):
        self.authenticate_as(self.user)
        response = self.client.post(
            imports_url,
            {"file": SimpleUploadedFile("design.svg", PAGE_PNG, content_type="image/svg+xml")},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_an_oversized_file_is_refused(self):
        self.authenticate_as(self.user)
        with override_settings(MAX_TEMPLATE_IMPORT_BYTES=100):
            response = self.upload()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_anonymous_callers_cannot_import(self):
        self.assertEqual(self.upload().status_code, status.HTTP_401_UNAUTHORIZED)

    def test_only_your_own_imports_are_listed(self):
        mine = TemplateImport.objects.create(
            agent=self.profile,
            source_file=SimpleUploadedFile("a.png", PAGE_PNG),
            original_filename="a.png",
        )
        TemplateImport.objects.create(
            agent=self.other_profile,
            source_file=SimpleUploadedFile("b.png", PAGE_PNG),
            original_filename="b.png",
        )

        self.authenticate_as(self.user)
        response = self.client.get(imports_url)
        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(ids, [mine.pk])

    def test_another_agents_import_is_not_readable(self):
        theirs = TemplateImport.objects.create(
            agent=self.other_profile,
            source_file=SimpleUploadedFile("b.png", PAGE_PNG),
            original_filename="b.png",
        )
        self.authenticate_as(self.user)
        self.assertEqual(
            self.client.get(import_detail_url(theirs)).status_code,
            status.HTTP_404_NOT_FOUND,
        )


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ImportedTemplateVisibilityTestCase(TemplateAPITestCase):
    """An import belongs to whoever uploaded it; the library belongs to all."""

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.brokerage = self.make_brokerage("Acme Realty")
        self.user, self.profile = self.make_agent_in(self.brokerage, "importer@example.com")
        self.other_user, self.other_profile = self.make_agent_in(
            self.brokerage, "other@example.com"
        )

        # Shared product content.
        self.library = self.make_template(name="Library Template", slug="library-template")
        # One agent's own import. Filed under a category that needs no listing,
        # so these tests answer the visibility question on its own rather than
        # also tripping the "this template describes a property" gate.
        self.imported = self.make_template(
            name="My Flyer",
            slug="my-flyer",
            owner=self.profile,
            category=TemplateCategory.MARKET_UPDATE,
        )

    def test_the_owner_sees_both(self):
        self.authenticate_as(self.user)
        names = {row["name"] for row in self.client.get(self.templates_url).data["results"]}
        self.assertEqual(names, {"Library Template", "My Flyer"})

    def test_another_agent_sees_only_the_library(self):
        self.authenticate_as(self.other_user)
        names = {row["name"] for row in self.client.get(self.templates_url).data["results"]}
        self.assertEqual(names, {"Library Template"})

    def test_another_agent_cannot_open_it_directly(self):
        self.authenticate_as(self.other_user)
        self.assertEqual(
            self.client.get(self.template_detail_url(self.imported)).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_another_agent_cannot_build_a_design_on_it(self):
        """The design copies the template's elements outright.

        Without this check, a guessed id would hand over someone else's
        artwork wholesale.
        """
        self.authenticate_as(self.other_user)
        response = self.client.post(
            self.designs_url,
            {"name": "Borrowed", "template": self.imported.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("template", response.data)

    def test_the_owner_can_build_a_design_on_it(self):
        self.authenticate_as(self.user)
        response = self.client.post(
            self.designs_url,
            {"name": "Mine", "template": self.imported.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_facet_counts_match_what_the_caller_can_see(self):
        """A count that includes invisible templates sends the user to an
        empty filter, which reads as a bug rather than a boundary."""
        self.authenticate_as(self.other_user)
        facets = self.client.get(self.template_facets_url).data
        total = sum(row["count"] for row in facets["categories"])
        self.assertEqual(total, 1)

    def test_the_shared_library_is_unowned(self):
        self.assertFalse(self.library.is_imported)
        self.assertTrue(self.imported.is_imported)


class ImportedTemplateSerializerTestCase(TemplateAPITestCase):
    def test_the_gallery_is_told_which_templates_have_a_real_preview(self):
        brokerage = self.make_brokerage("Acme Realty")
        user, _profile = self.make_agent_in(brokerage, "a@example.com")
        self.make_template()

        self.authenticate_as(user)
        [row] = self.client.get(self.templates_url).data["results"]

        self.assertIn("source_image_url", row)
        self.assertIsNone(row["source_image_url"])
        self.assertFalse(row["is_imported"])

    def test_every_supported_dimension_is_reachable_by_shape(self):
        """closest_dimension must be able to return each format.

        A format nothing can ever map onto is a format no import can open at,
        which would be invisible until someone imported artwork of that shape.
        """
        for key, dimension in SOCIAL_DIMENSIONS.items():
            self.assertEqual(closest_dimension(dimension.width, dimension.height), key)
