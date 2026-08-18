"""The render-and-compare validation stage.

The scoring is pure — two images in, a number out — so it is tested by handing
it PNGs directly, with no browser anywhere. Only ``validate_extraction``'s thin
renderer call is stubbed, to prove the orchestration treats a renderer outage as
"validation was off" rather than a failed import.
"""

from __future__ import annotations

import io
from unittest import mock

from PIL import Image

from apps.templates.importing import ExtractedElement, RasterPage
from apps.templates.models import ElementType
from apps.templates import extraction_validation as ev
from apps.templates.tests.base import TemplateAPITestCase


def _png(fill, size=(200, 200), block=None, block_fill=(0, 0, 0)):
    image = Image.new("RGB", size, fill)
    if block:
        left, top, right, bottom = block
        image.paste(Image.new("RGB", (right - left, bottom - top), block_fill), (left, top))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _element(key, x, y, w, h, kind=ElementType.TEXT, content="Hello"):
    return ExtractedElement(
        key=key,
        label=key,
        element_type=kind,
        geometry={"x": x, "y": y, "width": w, "height": h, "rotation": 0},
        style_properties={"color": "#000000", "font_size_ratio": 0.05},
        content_source="",
        default_content=content,
        z_index=0,
    )


class ScoreImagesTestCase(TemplateAPITestCase):
    def test_identical_renders_score_one(self):
        png = _png("#FFFFFF", block=(20, 20, 60, 60), block_fill=(200, 40, 40))
        result = ev.score_images(png, png)
        self.assertGreater(result.score, 0.999)
        self.assertTrue(result.ok)

    def test_a_different_render_scores_below_one(self):
        original = _png("#FFFFFF", block=(20, 20, 60, 60), block_fill=(200, 40, 40))
        rendered = _png("#FFFFFF")  # the block is missing
        result = ev.score_images(original, rendered)
        self.assertLess(result.score, 1.0)

    def test_a_shifted_element_is_reported_as_an_offset(self):
        # Original has the block at x=20..60; the render has it 4px to the right.
        original = _png("#FFFFFF", block=(20, 20, 60, 60), block_fill=(200, 40, 40))
        rendered = _png("#FFFFFF", block=(24, 20, 64, 60), block_fill=(200, 40, 40))
        # An element whose box covers the block region (0.1..0.3 of 200 = 20..60).
        element = _element("blk", 0.1, 0.1, 0.2, 0.2, kind=ElementType.IMAGE)
        result = ev.score_images(original, rendered, [element])
        self.assertTrue(result.issues)
        top = result.issues[0]
        self.assertEqual(top["element_id"], "blk")
        self.assertEqual(top["type"], "offset")
        self.assertEqual(top["delta_x"], 4)


class BuildPreviewHtmlTestCase(TemplateAPITestCase):
    def test_a_text_element_renders_its_literal_content(self):
        page = RasterPage(png=_png("#FFFFFF"), width=200, height=200)
        html = ev.build_preview_html([_element("t", 0.1, 0.1, 0.5, 0.1)], page)
        self.assertIn("Hello", html)
        self.assertIn("position:absolute", html)


class ValidateExtractionTestCase(TemplateAPITestCase):
    def setUp(self):
        super().setUp()
        self.page = RasterPage(png=_png("#FFFFFF", block=(20, 20, 60, 60)), width=200, height=200)
        self.elements = [_element("t", 0.1, 0.1, 0.5, 0.1)]

    def test_a_renderer_outage_is_not_fatal(self):
        with mock.patch.object(ev, "render_layout", return_value=None):
            result = ev.validate_extraction(self.elements, self.page)
        self.assertFalse(result.ok)

    def test_a_matching_render_scores_high(self):
        # Feed the source straight back as the "render": a perfect match.
        with mock.patch.object(ev, "render_layout", return_value=self.page.png):
            result = ev.validate_extraction(self.elements, self.page)
        self.assertTrue(result.ok)
        self.assertGreater(result.score, 0.999)
