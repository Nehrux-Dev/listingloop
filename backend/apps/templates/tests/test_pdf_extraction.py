"""Reading a PDF's own structure, and publishing what comes out.

The fixtures are built with PyMuPDF rather than checked in as files, so what
each test asserts about the output can be read against the page that produced
it instead of against an opaque blob.
"""

from __future__ import annotations

import io

from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.templates.importing import extract_page, normalise_elements, rasterise
from apps.templates.document import FILL_TYPES, SHAPE_TYPES
from apps.templates.dimensions import get_dimension
from apps.templates.document import (
    DocumentValidationError,
    new_element,
    validate_document,
)
from apps.templates.html_builder import build_html
from apps.templates.models import (
    Design,
    ElementType,
    ImportStatus,
    Template,
    TemplateImport,
)
from apps.templates.render_context import build_context
from apps.templates.pdf_extraction import (
    _FLAG_MONO,
    _FLAG_SERIF,
    _family_for,
    extract_pdf_layout,
    is_text_pdf,
)
from apps.templates.tests.base import TemplateAPITestCase

templates_url = reverse("templates:template-list")


def _pymupdf():
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - depends on the installed wheel
        import fitz as pymupdf
    return pymupdf


def make_dotted_pdf(*, dots: int = 6, spacing: float = 30.0) -> bytes:
    """A page whose ground is a regular grid of small dots."""
    pymupdf = _pymupdf()
    document = pymupdf.open()
    page = document.new_page(width=400, height=400)
    page.draw_rect(pymupdf.Rect(0, 0, 400, 400), color=None, fill=(1, 1, 1))
    for row in range(dots):
        for col in range(dots):
            centre = pymupdf.Point(20 + col * spacing, 20 + row * spacing)
            page.draw_circle(centre, 3, color=None, fill=(0.2, 0.3, 0.9))
    page.insert_text((40, 380), "On the dots", fontsize=12, color=(0, 0, 0))
    data = document.tobytes()
    document.close()
    return data


def make_rounded_pdf() -> bytes:
    """A page carrying a rounded panel and a circle."""
    pymupdf = _pymupdf()
    document = pymupdf.open()
    page = document.new_page(width=400, height=400)
    page.draw_rect(pymupdf.Rect(0, 0, 400, 400), color=None, fill=(1, 1, 1))
    page.draw_rect(
        pymupdf.Rect(40, 40, 360, 200), radius=0.2, color=None, fill=(0.4, 0.2, 0.1)
    )
    page.draw_circle(pymupdf.Point(200, 300), 50, color=None, fill=(0.1, 0.6, 0.3))
    data = document.tobytes()
    document.close()
    return data


def make_pdf(*, with_text: bool = True) -> bytes:
    """A one-page flyer: cream ground, a brown panel, a heading and a price."""
    pymupdf = _pymupdf()
    document = pymupdf.open()
    page = document.new_page(width=400, height=600)

    # Ground, then the visible ground on top of it — design tools lay a white
    # sheet down first, and the extractor has to prefer the one you can see.
    page.draw_rect(pymupdf.Rect(0, 0, 400, 600), color=None, fill=(1, 1, 1))
    page.draw_rect(pymupdf.Rect(0, 0, 400, 600), color=None, fill=(0.93, 0.89, 0.85))
    page.draw_rect(pymupdf.Rect(20, 40, 380, 260), color=None, fill=(0.47, 0.31, 0.17))

    if with_text:
        page.insert_text((40, 120), "Dream House", fontsize=32, color=(1, 1, 1))
        page.insert_text((40, 300), "$700,000", fontsize=24, color=(0, 0, 0))
        page.insert_text((40, 340), "+123-456-7890", fontsize=10, color=(0, 0, 0))
        page.insert_text((40, 370), "www.example.com", fontsize=10, color=(0, 0, 0))
        page.insert_text((40, 400), "12 Harbour Street", fontsize=10, color=(0, 0, 0))
        page.insert_text((40, 430), "Some words", fontsize=10, color=(0, 0, 0))

    data = document.tobytes()
    document.close()
    return data


class TextPdfDetectionTests(TemplateAPITestCase):
    """Which extractor a file gets routed to."""

    def test_a_pdf_with_text_is_recognised(self):
        self.assertTrue(is_text_pdf(make_pdf()))

    def test_a_pdf_with_no_text_is_not(self):
        """A scan is a picture of a flyer. There is nothing to read, so it has
        to go to the vision model."""
        self.assertFalse(is_text_pdf(make_pdf(with_text=False)))

    def test_rubbish_is_not_mistaken_for_a_pdf(self):
        self.assertFalse(is_text_pdf(b"not a pdf at all"))


class StructuralExtractionTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.data = make_pdf()
        self.page = rasterise(self.data, "flyer.pdf")
        self.payload = extract_pdf_layout(self.data, self.page.width, self.page.height)
        self.by_text = {
            element["text"]: element
            for element in self.payload["elements"]
            if element["text"]
        }

    def test_every_line_of_text_comes_back(self):
        self.assertIn("Dream House", self.by_text)
        self.assertIn("$700,000", self.by_text)
        self.assertIn("Some words", self.by_text)

    def test_the_visible_ground_wins_over_the_sheet_beneath_it(self):
        """Two fills cover the whole page. Size cannot separate them, so the
        later one in paint order — the one you can actually see — is the
        ground, and the white sheet underneath is dropped."""
        self.assertEqual(self.payload["page"]["background_color"], "#EDE3D9")
        grounds = [e for e in self.payload["elements"] if e["type"] == "background"]
        self.assertEqual(len(grounds), 1)

    def test_the_headline_names_the_template(self):
        self.assertEqual(self.payload["page"]["suggested_name"], "Dream House")

    def test_text_keeps_its_colour_and_size(self):
        headline = self.by_text["Dream House"]
        self.assertEqual(headline["style"]["color"], "#FFFFFF")
        # 32pt on a 600pt page rasterised to `page.height` pixels.
        expected = 32 * self.page.height / 600
        self.assertAlmostEqual(headline["style"]["font_size_px"], expected, delta=1.0)

    def test_geometry_is_in_raster_pixels(self):
        """Everything downstream measures against the raster the crops are cut
        from, so the two have to be in the same space."""
        panel = next(
            e for e in self.payload["elements"] if e["type"] == "shape" and e["role"] == "panel"
        )
        self.assertAlmostEqual(
            panel["transform"]["x"], 20 * self.page.width / 400, delta=1.0
        )
        self.assertAlmostEqual(
            panel["transform"]["width"], 360 * self.page.width / 400, delta=1.0
        )

    def test_text_is_stacked_above_panels(self):
        headline = self.by_text["Dream House"]
        panel = next(
            e for e in self.payload["elements"] if e["type"] == "shape" and e["role"] == "panel"
        )
        self.assertGreater(
            headline["transform"]["z_index"], panel["transform"]["z_index"]
        )

    def test_unmistakable_values_are_bound(self):
        self.assertEqual(self.by_text["$700,000"]["binding"], "price")
        self.assertEqual(self.by_text["+123-456-7890"]["binding"], "brokerage_phone")
        self.assertEqual(self.by_text["www.example.com"]["binding"], "brokerage_website")
        self.assertEqual(self.by_text["12 Harbour Street"]["binding"], "address")

    def test_ordinary_words_are_left_unbound(self):
        """Guessing a binding from a weak signal puts a listing's price into a
        decorative caption. Unbound is the safe answer."""
        self.assertEqual(self.by_text["Some words"]["binding"], "")

    def test_the_payload_survives_normalisation(self):
        """The whole point of matching the vision extractor's shape: nothing
        downstream should be able to tell which one ran."""
        elements = normalise_elements(self.payload, self.page)

        self.assertGreater(len(elements), 5)
        kinds = {element.element_type for element in elements}
        self.assertIn(ElementType.TEXT, kinds)
        self.assertIn(ElementType.COLOR_BLOCK, kinds)

    def test_a_flat_ground_is_not_baked_into_a_crop(self):
        """Together with the crop rule in importing: a page-sized colour block
        must not become a screenshot of the whole flyer."""
        elements = normalise_elements(self.payload, self.page)
        ground = next(e for e in elements if e.key.startswith("page_background"))

        self.assertEqual(ground.element_type, ElementType.COLOR_BLOCK)
        self.assertIsNone(ground.crop_box)


class FontClassificationTests(TemplateAPITestCase):
    """The family name files a face into the right substitute stack; the
    serif/mono flags remain the fallback for nameless Type3 subsets."""

    def test_the_family_name_beats_the_two_bucket_flags(self):
        self.assertEqual(_family_for("ABCDEF+AlexBrush-Regular", 0), "script")
        self.assertEqual(_family_for("BebasNeue-Regular", 0), "display")
        self.assertEqual(_family_for("RobotoCondensed-Bold", 0), "display")
        self.assertEqual(_family_for("CourierNew", 0), "mono")
        self.assertEqual(_family_for("PlayfairDisplay-Bold", 0), "serif")
        self.assertEqual(_family_for("Garamond-Regular", 0), "serif")

    def test_a_sans_face_never_lands_in_serif(self):
        # "serif" is a substring of sans-serif style names; the guard keeps a
        # sans face out of the serif bucket even when its name contains it.
        self.assertEqual(_family_for("OpenSans-Regular", 0), "body")
        self.assertEqual(_family_for("SomeSansSerif", 0), "body")

    def test_the_flags_remain_the_fallback_for_nameless_subsets(self):
        self.assertEqual(_family_for("", _FLAG_SERIF), "serif")
        self.assertEqual(_family_for("", _FLAG_MONO), "mono")
        self.assertEqual(_family_for("", 0), "body")


def make_italic_pdf() -> bytes:
    """A page whose one line is set in Times-Italic."""
    pymupdf = _pymupdf()
    document = pymupdf.open()
    page = document.new_page(width=400, height=600)
    page.draw_rect(pymupdf.Rect(0, 0, 400, 600), color=None, fill=(1, 1, 1))
    page.insert_text(
        (40, 120), "Elegant Living", fontsize=24, fontname="tiit", color=(0, 0, 0)
    )
    data = document.tobytes()
    document.close()
    return data


class TypographyCarryThroughTests(TemplateAPITestCase):
    """What the PDF knows about its type survives into the payload."""

    def setUp(self) -> None:
        super().setUp()
        data = make_italic_pdf()
        page = rasterise(data, "flyer.pdf")
        self.payload = extract_pdf_layout(data, page.width, page.height)
        self.line = next(
            element
            for element in self.payload["elements"]
            if element["text"] == "Elegant Living"
        )

    def test_an_italic_serif_face_keeps_both_properties(self):
        self.assertEqual(self.line["style"]["font_family"], "serif")
        self.assertEqual(self.line["style"].get("font_style"), "italic")

    def test_the_payload_declares_its_geometry_exact(self):
        """What unlocks the measured-width compensations in normalisation —
        only the structural reader may claim it."""
        self.assertTrue(self.payload["page"]["geometry_is_exact"])


class RotatedTextTests(TemplateAPITestCase):
    """A rotated line carries its angle instead of arriving as its envelope.

    The bbox of a vertical caption is a tall, thin rectangle; read as a
    horizontal box it renders as type smeared sideways across it. The writing
    direction says the angle, and the true box is recovered from the envelope.
    """

    def setUp(self) -> None:
        super().setUp()
        pymupdf = _pymupdf()
        document = pymupdf.open()
        page = document.new_page(width=400, height=600)
        page.draw_rect(pymupdf.Rect(0, 0, 400, 600), color=None, fill=(1, 1, 1))
        page.insert_text((60, 400), "SIDEWAYS CAPTION", fontsize=14, rotate=90)
        page.insert_text((40, 100), "Plain heading", fontsize=20)
        data = document.tobytes()
        document.close()
        raster = rasterise(data, "rotated.pdf")
        self.payload = extract_pdf_layout(data, raster.width, raster.height)
        self.by_text = {
            e["text"]: e for e in self.payload["elements"] if e["text"]
        }

    def test_the_rotated_line_knows_its_angle(self):
        caption = self.by_text["SIDEWAYS CAPTION"]
        self.assertAlmostEqual(abs(caption["transform"]["rotation"]), 90.0, delta=1.0)

    def test_the_rotated_box_is_the_line_not_its_envelope(self):
        """The unrotated box runs along the text: longer in width than height,
        even though the envelope on the page is taller than wide."""
        caption = self.by_text["SIDEWAYS CAPTION"]
        self.assertGreater(
            caption["transform"]["width"], caption["transform"]["height"]
        )

    def test_horizontal_text_stays_unrotated(self):
        self.assertEqual(self.by_text["Plain heading"]["transform"]["rotation"], 0)


class TextAlignmentInferenceTests(TemplateAPITestCase):
    """Alignment read from where the lines actually sit, never hardcoded.

    It decides which way a too-tight box may grow: growing a centred headline
    rightward shoves it off-axis.
    """

    def _payload_for(self, build) -> dict:
        pymupdf = _pymupdf()
        document = pymupdf.open()
        page = document.new_page(width=400, height=600)
        page.draw_rect(pymupdf.Rect(0, 0, 400, 600), color=None, fill=(1, 1, 1))
        build(page, pymupdf)
        data = document.tobytes()
        document.close()
        raster = rasterise(data, "align.pdf")
        return extract_pdf_layout(data, raster.width, raster.height)

    def test_a_line_dead_on_the_page_centreline_is_centred(self):
        pymupdf = _pymupdf()
        text = "OPEN HOUSE"
        width = pymupdf.get_text_length(text, fontname="helv", fontsize=24)
        payload = self._payload_for(
            lambda page, _: page.insert_text(((400 - width) / 2, 100), text, fontsize=24)
        )
        line = next(e for e in payload["elements"] if e["text"] == text)

        self.assertEqual(line["style"]["text_align"], "center")

    def test_an_ordinary_left_line_stays_left(self):
        payload = self._payload_for(
            lambda page, _: page.insert_text((40, 100), "Off to one side", fontsize=18)
        )
        line = next(e for e in payload["elements"] if e["text"] == "Off to one side")

        self.assertEqual(line["style"]["text_align"], "left")

    def test_ragged_lines_sharing_a_centre_are_centred(self):
        def build(page, pymupdf):
            for text, size, y in (("A MUCH LONGER LINE", 16, 100), ("SHORT", 16, 120)):
                width = pymupdf.get_text_length(text, fontname="helv", fontsize=size)
                page.insert_text(((400 - width) / 2, y), text, fontsize=size)

        payload = self._payload_for(build)
        aligns = {
            e["style"]["text_align"]
            for e in payload["elements"]
            if e["text"] in ("A MUCH LONGER LINE", "SHORT")
        }

        self.assertEqual(aligns, {"center"})


class EmbeddedImagePointerTests(TemplateAPITestCase):
    """A placed image remembers which stream it came from, so baking can go
    back to the original pixels instead of the size-capped raster."""

    def test_the_payload_carries_the_xref_and_placement(self):
        from PIL import Image

        pymupdf = _pymupdf()
        buffer = io.BytesIO()
        Image.new("RGB", (64, 64), "#3355EE").save(buffer, format="PNG")
        document = pymupdf.open()
        page = document.new_page(width=400, height=600)
        page.draw_rect(pymupdf.Rect(0, 0, 400, 600), color=None, fill=(1, 1, 1))
        page.insert_image(pymupdf.Rect(100, 150, 300, 350), stream=buffer.getvalue())
        page.insert_text((40, 500), "With a photo", fontsize=12)
        data = document.tobytes()
        document.close()

        raster = rasterise(data, "photo.pdf")
        payload = extract_pdf_layout(data, raster.width, raster.height)
        image = next(e for e in payload["elements"] if e["type"] == "image")

        self.assertGreater(image["source_xref"], 0)
        self.assertEqual(len(image["source_placement"]), 4)
        self.assertGreater(image["source_placement"][2], 0)
        self.assertGreater(image["source_placement"][3], 0)


def make_invisible_mask_pdf() -> bytes:
    """A page with a visible beige band and an invisible black rect over it.

    Design tools leave fully transparent shapes in the stream (masks, backdrops
    of deleted content); read without opacity each becomes an opaque black slab.
    """
    pymupdf = _pymupdf()
    document = pymupdf.open()
    page = document.new_page(width=400, height=400)
    page.draw_rect(pymupdf.Rect(0, 0, 400, 400), color=None, fill=(1, 1, 1))
    page.draw_rect(pymupdf.Rect(0, 300, 400, 400), color=None, fill=(0.7, 0.65, 0.6))
    page.draw_rect(pymupdf.Rect(0, 300, 400, 400), color=None, fill=(0, 0, 0), fill_opacity=0)
    page.draw_rect(
        pymupdf.Rect(50, 50, 150, 100), color=None, fill=(0.3, 0.2, 0.1), fill_opacity=0.4
    )
    page.insert_text((40, 380), "On the band", fontsize=12, color=(0, 0, 0))
    data = document.tobytes()
    document.close()
    return data


class OpacityTests(TemplateAPITestCase):
    """Transparent shapes must not come back as opaque black slabs."""

    def setUp(self) -> None:
        super().setUp()
        data = make_invisible_mask_pdf()
        page = rasterise(data, "flyer.pdf")
        self.payload = extract_pdf_layout(data, page.width, page.height)

    def test_a_fully_transparent_fill_is_dropped(self):
        blacks = [
            e
            for e in self.payload["elements"]
            if e["style"].get("background_color") == "#000000"
        ]
        self.assertEqual(blacks, [])

    def test_a_translucent_wash_keeps_its_opacity(self):
        washes = [
            e for e in self.payload["elements"] if e["style"].get("opacity", 1) < 1
        ]
        self.assertEqual(len(washes), 1)
        self.assertAlmostEqual(washes[0]["style"]["opacity"], 0.4, places=2)


class BulletsAreNotAPatternTests(TemplateAPITestCase):
    """Six list bullets in two columns must stay six dots, not become a
    tiling texture scattered through the list's own text."""

    def test_two_columns_of_bullets_stay_individual_marks(self):
        pymupdf = _pymupdf()
        document = pymupdf.open()
        page = document.new_page(width=400, height=400)
        page.draw_rect(pymupdf.Rect(0, 0, 400, 400), color=None, fill=(1, 1, 1))
        for col_x in (60, 220):
            for row in range(3):
                centre = pymupdf.Point(col_x, 100 + row * 20)
                page.draw_circle(centre, 2.2, color=None, fill=(0.34, 0.25, 0.2))
        page.insert_text((40, 380), "Features", fontsize=12, color=(0, 0, 0))
        data = document.tobytes()
        document.close()

        raster = rasterise(data, "flyer.pdf")
        payload = extract_pdf_layout(data, raster.width, raster.height)
        marks = [e for e in payload["elements"] if e["role"] == "mark"]
        patterns = [e for e in payload["elements"] if e["role"] == "dot_pattern"]
        self.assertEqual(len(marks), 6)
        self.assertEqual(patterns, [])


class VisibleImageBoxTests(TemplateAPITestCase):
    """A placed image is trimmed to the clip that frames it, so the baked crop
    holds the photo and not whatever sat next to the frame."""

    def _clip(self, rect, items=None):
        return {"scissor": rect, "items": items or [], "type": "clip"}

    def test_the_placement_is_trimmed_to_its_frame(self):
        from apps.templates.pdf_extraction import _visible_image_box

        pymupdf = _pymupdf()
        page_clip = self._clip(pymupdf.Rect(0, 0, 595, 842))
        frame = self._clip(pymupdf.Rect(59.5, 106, 221.7, 268))
        visible, radius = _visible_image_box((19, 106, 262, 268), [page_clip, frame])
        self.assertAlmostEqual(visible[0], 59.5)
        self.assertAlmostEqual(visible[2], 221.7)
        self.assertEqual(radius, 0.0)

    def test_a_tiny_unrelated_clip_does_not_crop_the_photo(self):
        from apps.templates.pdf_extraction import _visible_image_box

        pymupdf = _pymupdf()
        badge = self._clip(pymupdf.Rect(20, 110, 60, 150))
        visible, _ = _visible_image_box((19, 106, 262, 268), [badge])
        self.assertEqual(visible, (19, 106, 262, 268))

    def test_a_rounded_frame_hands_its_radius_to_the_photo(self):
        from apps.templates.pdf_extraction import _visible_image_box

        pymupdf = _pymupdf()
        rect = pymupdf.Rect(50, 50, 250, 250)
        # The rounded path alongside an axis-aligned scissor of the same size,
        # as design tools nest them: corner arcs of ~12pt.
        curve = [
            (
                "c",
                pymupdf.Point(50, 62),
                pymupdf.Point(50, 50),
                pymupdf.Point(50, 50),
                pymupdf.Point(62, 50),
            )
        ]
        plain = self._clip(rect)
        rounded = self._clip(rect, items=[("re", rect)] + curve)
        visible, radius = _visible_image_box((30, 30, 270, 270), [plain, rounded])
        self.assertEqual(visible, (50, 50, 250, 250))
        self.assertGreater(radius, 0)


class ExtractorRoutingTests(TemplateAPITestCase):
    """`extract_page` picks the reader; it does not call the model needlessly."""

    def test_a_text_pdf_is_read_structurally_and_costs_nothing(self):
        data = make_pdf()
        page = rasterise(data, "flyer.pdf")

        result = extract_page(data, page)

        self.assertEqual(result.model, "pdf-structure")
        self.assertEqual(result.prompt_tokens, 0)
        self.assertEqual(result.completion_tokens, 0)
        self.assertTrue(result.payload["elements"])


class PublishToLibraryTests(TemplateAPITestCase):
    """The Upload button: a private draft becomes everybody's template."""

    def setUp(self) -> None:
        super().setUp()
        self.nehrux = self.make_nehrux_admin()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.owner_profile = self.make_agent_in(self.acme, "owner@example.com")[1]
        self.draft = self.make_template(
            name="Imported draft", slug="imported-draft", owner=self.owner_profile
        )

    def publish_url(self, template) -> str:
        return reverse("templates:template-publish", args=[template.pk])

    def test_an_imported_draft_is_private_until_published(self):
        self.assertFalse(
            Template.objects.visible_to(self.agent).filter(pk=self.draft.pk).exists()
        )

    def test_publishing_clears_the_owner_and_reaches_every_agent(self):
        self.authenticate_as(self.nehrux)

        response = self.client.post(self.publish_url(self.draft), {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.draft.refresh_from_db()
        self.assertIsNone(self.draft.owner)
        self.assertTrue(self.draft.is_active)
        self.assertTrue(
            Template.objects.visible_to(self.agent).filter(pk=self.draft.pk).exists()
        )

    def test_an_agent_cannot_publish(self):
        """Otherwise one brokerage's artwork lands in a rival's gallery."""
        self.authenticate_as(self.agent)

        response = self.client.post(self.publish_url(self.draft), {}, format="json")

        self.assertEqual(response.status_code, 403)
        self.draft.refresh_from_db()
        self.assertIsNotNone(self.draft.owner)

    def test_publishing_twice_is_refused_rather_than_silently_repeated(self):
        self.authenticate_as(self.nehrux)
        self.client.post(self.publish_url(self.draft), {}, format="json")

        again = self.client.post(self.publish_url(self.draft), {}, format="json")

        self.assertEqual(again.status_code, 409)

    def test_publishing_requires_authentication(self):
        self.assertEqual(
            self.client.post(self.publish_url(self.draft), {}, format="json").status_code,
            401,
        )


class DashboardLoginTests(TemplateAPITestCase):
    """The staff logins, and the one thing uploading needs from them."""

    def test_the_platform_login_gets_what_uploading_needs(self):
        from io import StringIO

        from django.core.management import call_command

        from apps.accounts.models import AgentProfile, Role, User

        out = StringIO()
        call_command(
            "create_dashboard_login", dashboard="platform",
            password="s3cret-pw", stdout=out,
        )

        user = User.objects.get(email="nehrux@nehrux.com")
        self.assertEqual(user.role, Role.NEHRUX_ADMIN)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("s3cret-pw"))
        # An upload is owned by a profile, and the signal that makes one skips
        # every role but agent — so without this the import endpoint 403s.
        self.assertTrue(AgentProfile.objects.filter(user=user).exists())

    def test_running_it_again_updates_rather_than_duplicating(self):
        from django.core.management import call_command

        from apps.accounts.models import User

        call_command(
            "create_dashboard_login", dashboard="platform",
            password="first-one", verbosity=0,
        )
        call_command(
            "create_dashboard_login", dashboard="platform",
            password="second-one", verbosity=0,
        )

        self.assertEqual(User.objects.filter(email="nehrux@nehrux.com").count(), 1)
        self.assertTrue(
            User.objects.get(email="nehrux@nehrux.com").check_password("second-one")
        )

    def test_a_super_admin_can_queue_an_import(self):
        from django.core.management import call_command

        from apps.accounts.models import User
        from apps.accounts.tests.base import PASSWORD

        # The base helper signs in with its own password, so the account is
        # created with that one — this test is about the upload, not the
        # credential (see the login tests in apps.accounts for that).
        call_command(
            "create_dashboard_login", dashboard="platform",
            password=PASSWORD, verbosity=0,
        )
        self.authenticate_as(User.objects.get(email="nehrux@nehrux.com"))

        response = self.client.post(
            reverse("templates:templateimport-list"),
            {
                "file": SimpleUploadedFile(
                    "flyer.pdf", make_pdf(), content_type="application/pdf"
                ),
                "category": "new_listing",
                "style": "luxury",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 202, response.data)

    def test_the_agency_login_administers_a_brokerage(self):
        """A brokerage admin with no brokerage reaches their dashboard and finds
        nothing on it — every panel there is scoped to the firm they run."""
        from django.core.management import call_command

        from apps.accounts.models import Brokerage, Role, User

        call_command(
            "create_dashboard_login", dashboard="agency",
            password="agency-pw", brokerage="Demo Agency", verbosity=0,
        )

        user = User.objects.get(email="agency@nehrux.com")
        self.assertEqual(user.role, Role.BROKERAGE_ADMIN)
        self.assertTrue(user.check_password("agency-pw"))
        # Not a superuser: the agency admin is the customer, not the platform.
        self.assertFalse(user.is_superuser)
        brokerage = Brokerage.objects.get(name="Demo Agency")
        self.assertIn(user, brokerage.admins.all())
        self.assertEqual(user.agent_profile.brokerage_id, brokerage.pk)

    def test_the_two_logins_have_different_usernames(self):
        """Both resolve from a bare name, so their local parts must not clash —
        an ambiguous name resolves to nobody and locks both out."""
        from django.core.management import call_command

        from apps.accounts.models import User

        call_command(
            "create_dashboard_login", dashboard="platform", password="a", verbosity=0
        )
        call_command(
            "create_dashboard_login", dashboard="agency", password="b", verbosity=0
        )

        locals_ = {
            user.email.split("@")[0]
            for user in User.objects.filter(email__endswith="@nehrux.com")
        }
        self.assertEqual(locals_, {"nehrux", "agency"})


class FillClassificationTests(TemplateAPITestCase):
    """A fill is described, never assumed to be a flat colour.

    Flattening a dotted ground into one solid rectangle is not a rounding
    error — it is a different design, and one anybody looking at the page can
    see is wrong.
    """

    def setUp(self) -> None:
        super().setUp()
        self.data = make_dotted_pdf()
        self.page = rasterise(self.data, "dots.pdf")
        self.payload = extract_pdf_layout(self.data, self.page.width, self.page.height)
        self.shapes = [e for e in self.payload["elements"] if e["type"] == "shape"]

    def test_a_grid_of_dots_becomes_one_pattern_not_many_shapes(self):
        patterns = [e for e in self.shapes if e["style"]["fill_type"] == "dot_pattern"]

        self.assertEqual(len(patterns), 1)
        # 36 dots went in. One element comes out — not 36, and not zero.
        self.assertLess(len(self.shapes), 5)

    def test_the_pattern_carries_what_it_takes_to_redraw_it(self):
        pattern = next(e for e in self.shapes if e["style"]["fill_type"] == "dot_pattern")
        style = pattern["style"]

        self.assertTrue(style["dot_color"].startswith("#"))
        self.assertGreater(style["dot_radius_px"], 0)
        # 30pt spacing on a 400pt page, scaled into raster pixels.
        expected = 30 * self.page.width / 400
        self.assertAlmostEqual(style["dot_spacing_x_px"], expected, delta=2.0)
        self.assertAlmostEqual(style["dot_spacing_y_px"], expected, delta=2.0)

    def test_the_pattern_carries_no_flat_fill_to_paint_over_it(self):
        """A solid colour underneath the dots is the flattening this avoids."""
        pattern = next(e for e in self.shapes if e["style"]["fill_type"] == "dot_pattern")

        self.assertEqual(pattern["style"]["background_color"], "")

    def test_the_pattern_survives_into_renderable_style(self):
        elements = normalise_elements(self.payload, self.page)
        dotted = next(
            e for e in elements if e.style_properties.get("fill_type") == "dot_pattern"
        )

        self.assertIn("dot_color", dotted.style_properties)
        self.assertGreater(dotted.style_properties["dot_radius_ratio"], 0)
        self.assertGreater(dotted.style_properties["dot_spacing_x_ratio"], 0)
        self.assertNotIn("background_color", dotted.style_properties)

    def test_a_scatter_of_marks_is_not_called_a_pattern(self):
        """Three dots in no particular arrangement are three marks."""
        pymupdf = _pymupdf()
        document = pymupdf.open()
        page = document.new_page(width=200, height=200)
        page.draw_rect(pymupdf.Rect(0, 0, 200, 200), color=None, fill=(1, 1, 1))
        for point in [(17, 23), (140, 61), (58, 175)]:
            page.draw_circle(pymupdf.Point(*point), 4, color=None, fill=(0.9, 0.1, 0.1))
        data = document.tobytes()
        document.close()

        raster = rasterise(data, "marks.pdf")
        payload = extract_pdf_layout(data, raster.width, raster.height)

        kinds = {e["style"].get("fill_type") for e in payload["elements"]}
        self.assertNotIn("dot_pattern", kinds)


class ShapeClassificationTests(TemplateAPITestCase):
    """A bounding box describes a rectangle and misdescribes everything else."""

    def setUp(self) -> None:
        super().setUp()
        self.data = make_rounded_pdf()
        self.page = rasterise(self.data, "shapes.pdf")
        self.payload = extract_pdf_layout(self.data, self.page.width, self.page.height)
        self.shapes = [
            e for e in self.payload["elements"] if e["type"] in ("shape", "background")
        ]

    def test_a_circle_is_an_ellipse_with_a_radius_that_rounds_it(self):
        circle = next(e for e in self.shapes if e["style"]["shape_type"] == "ellipse")

        # Half the shorter side: what makes a box render as a circle.
        half = min(circle["transform"]["width"], circle["transform"]["height"]) / 2
        self.assertAlmostEqual(circle["style"]["border_radius_px"], half, delta=2.0)

    def test_a_rounded_panel_keeps_its_corners(self):
        panel = next(
            e for e in self.shapes if e["style"]["shape_type"] == "rounded_rect"
        )

        self.assertGreater(panel["style"]["border_radius_px"], 0)

    def test_the_flat_ground_is_still_a_rectangle(self):
        ground = next(e for e in self.shapes if e["type"] == "background")

        self.assertEqual(ground["style"]["shape_type"], "rectangle")
        self.assertEqual(ground["style"]["fill_type"], "solid_color")

    def test_nothing_is_left_unclassified(self):
        """Silence would be read downstream as 'flat rectangle', which is the
        assumption this whole pass exists to stop making."""
        for shape in self.shapes:
            self.assertIn(shape["style"]["fill_type"], FILL_TYPES)
            self.assertIn(shape["style"]["shape_type"], SHAPE_TYPES)

    def test_radius_survives_into_renderable_style(self):
        elements = normalise_elements(self.payload, self.page)

        rounded = [e for e in elements if e.style_properties.get("border_radius_ratio")]
        self.assertGreaterEqual(len(rounded), 2)


#: Throttle history and the Celery broker both live in Redis, which these tests
#: must not need. A local cache keeps the rate limiter honest and in-process.
LOCAL_CACHE = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}


def rates(agent: str, admin: str):
    """Patch the rates where the throttle actually reads them.

    `SimpleRateThrottle.THROTTLE_RATES` is a class attribute bound at import,
    so `override_settings(REST_FRAMEWORK=...)` changes the setting and the
    throttle never notices — the tests pass while limiting nothing, which is
    the worst outcome available for a rate-limit test.
    """
    from rest_framework.throttling import SimpleRateThrottle

    return mock.patch.dict(
        SimpleRateThrottle.THROTTLE_RATES,
        {"template_import": agent, "template_import_admin": admin},
    )


class ImportThrottleTests(TemplateAPITestCase):
    """Who the low ceiling is for, and who it is not.

    The limit exists because an import can mean a paid vision call. That holds
    for an agent importing their own artwork; it does not hold for the platform
    owner stocking the library, whose text PDFs are read structurally and cost
    nothing to extract.
    """

    def setUp(self) -> None:
        super().setUp()
        from apps.accounts.models import AgentProfile

        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.nehrux = self.make_nehrux_admin()
        AgentProfile.objects.get_or_create(user=self.nehrux)
        self.url = reverse("templates:templateimport-list")

    def upload(self):
        """One upload with the worker stubbed — this is about admission, not
        extraction, and a real queue call would need a broker."""
        with mock.patch("apps.templates.views.import_template_artwork.delay"):
            return self.client.post(
                self.url,
                {
                    "file": SimpleUploadedFile(
                        "flyer.pdf", make_pdf(), content_type="application/pdf"
                    ),
                    "category": "new_listing",
                    "style": "luxury",
                },
                format="multipart",
            )

    def scope_for(self, user) -> str:
        """Which throttle scope the view picks for this user."""
        from rest_framework.test import APIRequestFactory

        from apps.templates.views import TemplateImportViewSet

        view = TemplateImportViewSet()
        request = APIRequestFactory().post(self.url)
        request.user = user
        view.request = request
        view.get_throttles()
        return view.throttle_scope

    def test_the_platform_owner_gets_the_admin_scope(self):
        self.assertEqual(self.scope_for(self.nehrux), "template_import_admin")

    def test_an_agent_keeps_the_cost_controlled_scope(self):
        self.assertEqual(self.scope_for(self.agent), "template_import")

    @override_settings(CACHES=LOCAL_CACHE)
    def test_the_agent_ceiling_still_bites(self):
        self.authenticate_as(self.agent)

        with rates("2/hour", "50/hour"):
            codes = [self.upload().status_code for _ in range(4)]

        self.assertEqual(codes[:2], [202, 202])
        self.assertEqual(codes[2:], [429, 429])

    @override_settings(CACHES=LOCAL_CACHE)
    def test_the_platform_owner_is_not_cut_off_at_the_agent_limit(self):
        """Stocking the library is a sitting-down job. Being stopped after two
        uploads is the product refusing its own supply side."""
        self.authenticate_as(self.nehrux)

        with rates("2/hour", "50/hour"):
            codes = [self.upload().status_code for _ in range(4)]

        self.assertEqual(codes, [202, 202, 202, 202])

    @override_settings(CACHES=LOCAL_CACHE)
    def test_the_admin_ceiling_is_a_ceiling_and_not_an_exemption(self):
        """Higher, not absent — it is the runaway-loop backstop."""
        self.authenticate_as(self.nehrux)

        with rates("2/hour", "3/hour"):
            codes = [self.upload().status_code for _ in range(5)]

        self.assertEqual(codes.count(429), 2)


class RemoveFromLibraryTests(TemplateAPITestCase):
    """Taking a template back out of every agent's gallery."""

    def setUp(self) -> None:
        super().setUp()
        self.nehrux = self.make_nehrux_admin()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template(name="Published", slug="published")

    def detail_url(self, template) -> str:
        return reverse("templates:template-detail", args=[template.pk])

    def test_an_unused_template_is_deleted_outright(self):
        self.authenticate_as(self.nehrux)

        response = self.client.delete(self.detail_url(self.template))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Template.objects.filter(pk=self.template.pk).exists())

    def test_it_disappears_from_the_agent_gallery(self):
        """The whole point: removed here means gone there."""
        self.authenticate_as(self.agent)
        before = [t["name"] for t in self.client.get(templates_url).data["results"]]
        self.assertIn("Published", before)

        self.authenticate_as(self.nehrux)
        self.client.delete(self.detail_url(self.template))

        self.authenticate_as(self.agent)
        after = [t["name"] for t in self.client.get(templates_url).data["results"]]
        self.assertNotIn("Published", after)

    def test_a_template_with_designs_is_retired_rather_than_deleted(self):
        """`Design.template` is PROTECT, and that protection is worth keeping:
        an agent's finished flyer must not vanish because somebody tidied the
        library. Retiring achieves what was actually asked — gone from the
        gallery — without taking their work with it."""
        design = self.make_design(self.template, self.profile)
        self.authenticate_as(self.nehrux)

        response = self.client.delete(self.detail_url(self.template))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["retired"])
        self.assertEqual(response.data["designs"], 1)
        self.template.refresh_from_db()
        self.assertFalse(self.template.is_active)
        # The design is untouched and still openable.
        self.assertTrue(Design.objects.filter(pk=design.pk).exists())

    def test_a_retired_template_is_also_gone_from_the_gallery(self):
        self.make_design(self.template, self.profile)
        self.authenticate_as(self.nehrux)
        self.client.delete(self.detail_url(self.template))

        self.authenticate_as(self.agent)
        names = [t["name"] for t in self.client.get(templates_url).data["results"]]

        self.assertNotIn("Published", names)

    def test_an_agent_cannot_remove_a_template(self):
        self.authenticate_as(self.agent)

        response = self.client.delete(self.detail_url(self.template))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Template.objects.filter(pk=self.template.pk).exists())

    def test_a_brokerage_admin_cannot_either(self):
        """The library is one shelf shared by every agency — a customer
        removing from it would be deleting a rival firm's templates too."""
        broker = self.make_brokerage_admin("broker@example.com")
        self.acme.admins.add(broker)
        self.authenticate_as(broker)

        response = self.client.delete(self.detail_url(self.template))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Template.objects.filter(pk=self.template.pk).exists())

    def test_removing_requires_authentication(self):
        self.assertEqual(self.client.delete(self.detail_url(self.template)).status_code, 401)

    def test_reading_the_library_is_still_open_to_agents(self):
        """Locking down delete must not lock down the gallery."""
        self.authenticate_as(self.agent)

        self.assertEqual(self.client.get(templates_url).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url(self.template)).status_code, 200)


class PatternReachesTheRendererTests(TemplateAPITestCase):
    """The whole chain, not just the first link.

    Extraction, storage and rendering are three links, and a change to the
    first alone is invisible: the extractor returns pattern data, the document
    validator drops any key it does not know, and the renderer draws a flat
    box. These pin all three.
    """

    def setUp(self) -> None:
        super().setUp()
        self.style = {
            "fill_type": "dot_pattern",
            "dot_color": "#3355EE",
            "dot_radius_ratio": 0.004,
            "dot_spacing_x_ratio": 0.05,
            "dot_spacing_y_ratio": 0.05,
        }

    def test_storage_keeps_the_pattern_rather_than_dropping_it(self):
        element = new_element("shape")
        element["style"] = {**self.style, "background_color": "#FFFFFF"}

        stored = validate_document([element])[0]["style"]

        self.assertEqual(stored["fill_type"], "dot_pattern")
        self.assertEqual(stored["dot_color"], "#3355EE")
        self.assertEqual(stored["dot_spacing_x_ratio"], 0.05)

    def test_the_renderer_draws_the_pattern(self):
        acme = self.make_brokerage("Acme Realty")
        agent, profile = self.make_agent_in(acme, "a@example.com")
        template = self.make_template()
        design = self.make_design(template, profile)
        element = design.elements[0]
        element["type"] = "shape"
        element["style"] = self.style
        design.elements = [element]
        design.save(update_fields=["elements"])

        html = build_html(
            design, build_context(design), get_dimension("instagram_post"), {}
        )

        self.assertIn("radial-gradient", html)
        self.assertIn("#3355EE", html)
        self.assertIn("background-size", html)

    def test_an_incomplete_pattern_is_rescued_from_the_raster(self):
        """Told it is a pattern but given nothing to redraw one with. The
        region's own pixels are the tie-breaker: on this flyer the box sits on
        the flat cream ground, so the *measured* colour — not a guess — is
        what it becomes. A region the raster shows as genuinely patterned
        keeps its `unsupported_pattern` marker instead (see the rescue tests
        in test_importing)."""
        page = rasterise(make_pdf(), "flyer.pdf")
        payload = layout_with_broken_pattern()

        [element] = normalise_elements(payload, page)

        self.assertEqual(element.style_properties["fill_type"], "solid_color")
        # The cream ground of make_pdf, as the raster shows it — allow the
        # rasteriser a rounding unit per channel.
        measured = element.style_properties["background_color"]
        for channel, expected in zip((1, 3, 5), (0xED, 0xE3, 0xD9)):
            self.assertAlmostEqual(
                int(measured[channel : channel + 2], 16), expected, delta=2
            )


def layout_with_broken_pattern() -> dict:
    """A dot_pattern element missing its spacing — as a model might return it."""
    return {
        "page": {"background_color": "#FFFFFF", "suggested_name": "Broken"},
        "elements": [
            {
                "id": "e1",
                "type": "shape",
                "role": "panel",
                "binding": "",
                "text": "",
                "mask": [],
                "transform": {
                    "x": 10, "y": 10, "width": 100, "height": 100,
                    "rotation": 0, "z_index": 1,
                },
                "style": {
                    "color": "", "background_color": "#123456", "font_size_px": 0,
                    "font_weight": "", "font_family": "", "text_align": "",
                    "text_transform": "none", "line_height": 0, "opacity": 1,
                    "border_radius_px": 0, "border_width_px": 0, "border_color": "",
                    "gradient": "", "fill_type": "dot_pattern", "shape_type": "rectangle",
                    "dot_color": "#000000", "dot_radius_px": 0,
                    "dot_spacing_x_px": 0, "dot_spacing_y_px": 0,
                },
            }
        ],
    }


class ImportWarningsTests(TemplateAPITestCase):
    """A half-worked import must not look like one that worked."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.job = TemplateImport.objects.create(
            agent=self.profile,
            original_filename="flyer.pdf",
            status=ImportStatus.SUCCEEDED,
            template=self.template,
        )

    def warnings_for(self, job):
        from apps.templates.serializers import TemplateImportSerializer

        return TemplateImportSerializer(job).data["warnings"]

    def flag(self, key: str, fill_type: str) -> None:
        element = self.template.elements.get(key=key)
        element.style_properties = {**element.style_properties, "fill_type": fill_type}
        element.save(update_fields=["style_properties"])

    def test_a_clean_import_warns_about_nothing(self):
        """A review list that cries wolf is one nobody reads."""
        self.assertEqual(self.warnings_for(self.job), [])

    def test_an_unclassifiable_fill_is_reported(self):
        self.flag("badge", "unsupported_pattern")

        warnings = self.warnings_for(self.job)

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["fill_type"], "unsupported_pattern")
        self.assertIn("could not be identified", warnings[0]["issue"])
        # Named, so it can be found on the canvas.
        self.assertTrue(warnings[0]["element"])

    def test_every_flagged_element_is_listed(self):
        self.flag("badge", "unsupported_pattern")
        self.flag("price", "image_texture")

        self.assertEqual(len(self.warnings_for(self.job)), 2)

    def test_fixing_an_element_clears_its_warning(self):
        """Derived from the elements rather than stored on the job, so a fix in
        the editor cannot leave a stale complaint behind."""
        self.flag("badge", "unsupported_pattern")
        self.assertEqual(len(self.warnings_for(self.job)), 1)

        self.flag("badge", "solid_color")

        self.assertEqual(self.warnings_for(self.job), [])

    def test_a_job_with_no_template_yet_reports_nothing(self):
        pending = TemplateImport.objects.create(
            agent=self.profile, original_filename="x.pdf", status=ImportStatus.RUNNING
        )

        self.assertEqual(self.warnings_for(pending), [])

    def test_warnings_reach_the_api(self):
        self.flag("badge", "unsupported_pattern")
        self.authenticate_as(self.agent)

        response = self.client.get(
            reverse("templates:templateimport-detail", args=[self.job.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["warnings"]), 1)


class AlignmentAndGroupingTests(TemplateAPITestCase):
    """Tidying what neither reader can see: intent.

    Both measure each element on its own. A designer aligned two panels; the
    extractor reports them four pixels apart. That is invisible at source scale
    and obvious once the template is re-rendered at another size, because the
    error scales with everything else.
    """

    def payload_for(self, build) -> dict:
        pymupdf = _pymupdf()
        document = pymupdf.open()
        page = document.new_page(width=400, height=560)
        page.draw_rect(pymupdf.Rect(0, 0, 400, 560), color=None, fill=(0.96, 0.94, 0.90))
        build(page, pymupdf)
        data = document.tobytes()
        document.close()
        raster = rasterise(data, "probe.pdf")
        return extract_page(data, raster).payload

    def test_near_identical_edges_become_identical(self):
        """Not merely closer — identical. Two boxes that each picked whichever
        anchor moved them least landed a pixel apart, which is the exact thing
        this removes."""

        def build(page, pymupdf):
            page.insert_text((40, 430), "ALIGNED A", fontsize=14)
            page.insert_text((42, 460), "ALIGNED B", fontsize=14)
            page.insert_text((41, 490), "ALIGNED C", fontsize=14)

        payload = self.payload_for(build)
        xs = {
            round(e["transform"]["x"], 2)
            for e in payload["elements"]
            if e["type"] == "text"
        }

        self.assertEqual(len(xs), 1, f"expected one shared x, got {sorted(xs)}")

    def test_a_deliberate_offset_is_left_alone(self):
        """Snapping everything would destroy real layout. Only near-misses."""

        def build(page, pymupdf):
            page.insert_text((40, 430), "LEFT", fontsize=14)
            page.insert_text((240, 460), "INDENTED", fontsize=14)

        payload = self.payload_for(build)
        xs = {
            round(e["transform"]["x"], 2)
            for e in payload["elements"]
            if e["type"] == "text"
        }

        self.assertEqual(len(xs), 2)

    def test_the_canvas_size_travels_with_the_geometry(self):
        """Geometry measured against one size and applied against another is
        wrong in a way no validation catches.

        The page needs text: a PDF with none is a scan as far as the router is
        concerned, and goes to the vision model instead.
        """
        payload = self.payload_for(
            lambda page, pymupdf: page.insert_text((40, 100), "Anything", fontsize=12)
        )

        self.assertGreater(payload["page"]["width"], 0)
        self.assertGreater(payload["page"]["height"], 0)

    def test_adjacent_content_is_grouped(self):
        def build(page, pymupdf):
            page.insert_text((40, 300), "Phone", fontsize=11)
            page.insert_text((40, 316), "Website", fontsize=11)

        payload = self.payload_for(build)
        groups = {
            e["style"].get("group_id")
            for e in payload["elements"]
            if e["style"].get("group_id")
        }

        self.assertEqual(len(groups), 1)

    def test_distant_content_is_not_grouped(self):
        def build(page, pymupdf):
            page.insert_text((40, 60), "Top", fontsize=11)
            page.insert_text((40, 520), "Bottom", fontsize=11)

        payload = self.payload_for(build)
        groups = [
            e["style"].get("group_id")
            for e in payload["elements"]
            if e["style"].get("group_id")
        ]

        self.assertEqual(groups, [])

    def test_panels_are_never_group_members(self):
        """A panel touches everything sitting on it. Including them chained
        every neighbour to every other through the thing they sat on, and
        produced one group of forty-two elements."""

        def build(page, pymupdf):
            page.draw_rect(pymupdf.Rect(20, 200, 380, 400), color=None, fill=(0.4, 0.2, 0.1))
            page.insert_text((40, 260), "On the panel", fontsize=11)
            page.insert_text((40, 280), "Also on it", fontsize=11)

        payload = self.payload_for(build)
        grouped_types = {
            e["type"] for e in payload["elements"] if e["style"].get("group_id")
        }

        self.assertEqual(grouped_types, {"text"})

    def test_a_group_id_survives_into_stored_style(self):
        """It rides on the style so it reaches designs without a migration."""
        element = new_element("text")
        element["style"] = {"group_id": "group_2"}

        self.assertEqual(validate_document([element])[0]["style"]["group_id"], "group_2")

    def test_a_hostile_group_id_is_refused(self):
        element = new_element("text")
        element["style"] = {"group_id": "url(http://evil/)"}

        with self.assertRaises(DocumentValidationError):
            validate_document([element])
