"""Rendering pipeline: HTML composition, multi-dimension export, storage.

The renderer service itself is stubbed — these tests are about everything
Django owns: resolving a design into HTML, mapping fractional geometry onto
four different canvases, persisting exports through the storage abstraction,
and failing usefully when the browser service is down.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from unittest import mock

from django.test import override_settings

from apps.accounts.tests.base import make_image_file
from apps.listings.models import ListingPhoto
from apps.templates.dimensions import SOCIAL_DIMENSIONS, get_dimension
from apps.templates.html_builder import build_html
from apps.templates.models import (
    DesignExport,
    ElementType,
    ExportFormat,
    TemplateElement,
)
from apps.templates.render_context import build_context
from apps.templates.tests.base import TemplateAPITestCase

MEDIA_ROOT = tempfile.mkdtemp(prefix="real-estate-design-media-")

PNG_BYTES = make_image_file("render.png").read()


class FakeResponse:
    def __init__(self, status_code=200, content=PNG_BYTES, headers=None, payload=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"Content-Type": "image/png", "X-Render-Ms": "142"}
        self._payload = payload or {}

    def json(self):
        return self._payload


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class RenderingTestCase(TemplateAPITestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.acme.required_disclaimer = "Figures are indicative only."
        self.acme.save()
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        ListingPhoto.objects.create(
            listing=self.listing, image=make_image_file("hero.png"), order=0
        )
        self.design = self.make_design(self.template, self.profile, self.listing)
        self.authenticate_as(self.agent)


class HtmlBuilderTests(RenderingTestCase):
    """Composition happens in Python, so it can be asserted on directly."""

    def _html(self, dimension_key="instagram_post"):
        context = build_context(self.design)
        return build_html(self.design, context, get_dimension(dimension_key), {})

    def edit(self, original_key: str, **fields):
        """Change one of the design's own elements — what editing now means."""
        element = self.element_of(self.design, original_key)
        element.update(fields)
        self.design.save(update_fields=["elements"])
        return element

    def test_content_resolves_from_the_listing(self):
        html = self._html()

        self.assertIn(self.listing.address, html)
        self.assertIn("$1,850,000", html)  # price, currency-formatted
        self.assertIn("Figures are indicative only.", html)  # locked disclaimer

    def test_the_agents_own_words_replace_the_bound_value(self):
        self.edit("headline", content="Beachside living", manually_overridden=True)

        html = self._html()

        self.assertIn("Beachside living", html)
        self.assertNotIn(self.listing.address, html)

    def test_images_are_inlined_not_linked(self):
        """The renderer has no network and no storage access by design."""
        html = self._html()

        self.assertIn("data:image/png;base64,", html)
        external = re.findall(r'src="(?!data:)([^"]+)"', html)
        self.assertEqual(external, [], f"template referenced external URLs: {external}")

    def test_text_is_escaped(self):
        self.edit(
            "headline",
            content="<script>alert(1)</script>",
            manually_overridden=True,
        )

        html = self._html()

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_hidden_elements_are_omitted(self):
        self.edit("badge", visible=False)

        self.assertNotIn("Just listed", self._html())

    def test_geometry_scales_with_the_canvas(self):
        """One template, four canvases — the whole point of fractional coords."""
        post = self._html("instagram_post")     # 1080 x 1080
        facebook = self._html("facebook")       # 1200 x 630

        # headline sits at x = 0.06 of the canvas width in both.
        self.assertIn(f"left:{0.06 * 1080:.2f}px", post)
        self.assertIn(f"left:{0.06 * 1200:.2f}px", facebook)

    def test_story_geometry_respects_the_safe_area(self):
        """Story chrome overlays the top and bottom; content is inset."""
        story_dimension = get_dimension("instagram_story")
        html = self._html("instagram_story")

        # y = 0 maps to the top of the safe area, not the top of the canvas.
        expected_top = story_dimension.safe_inset_top * story_dimension.height
        self.assertIn(f"top:{expected_top:.2f}px", html)
        self.assertGreater(expected_top, 0)

    def test_type_scales_with_the_smaller_side(self):
        """Post and Story share a width, so they must share a type size.

        Scaling type with canvas *height* grew Story type by 1.8x without
        widening the text box, and long headings wrapped into the element
        below. The smaller side is the reference that keeps text inside its box
        in every aspect ratio.
        """
        post = self._html("instagram_post")     # 1080 x 1080
        story = self._html("instagram_story")   # 1080 x 1920
        facebook = self._html("facebook")       # 1200 x 630

        self.assertIn(f"font-size:{0.04 * 1080:.2f}px", post)
        self.assertIn(f"font-size:{0.04 * 1080:.2f}px", story)
        self.assertIn(f"font-size:{0.04 * 630:.2f}px", facebook)

    def test_text_boxes_clip_rather_than_overlap(self):
        """Overflow onto the next element is worse than a clipped descender."""
        self.assertIn("overflow:hidden", self._html())

    def test_brand_kit_references_resolve(self):
        """`@accent_color` in a template resolves against the design's brand."""
        from apps.accounts.models import BrandKit

        BrandKit.objects.create(agent=self.profile, primary_color="#123456")
        # Edited on the design, not the template: a design that was copied
        # before this change would otherwise not see it, which is the whole
        # point of the copy.
        headline = self.element_of(self.design, "headline")
        headline["style"]["color"] = "@primary_color"
        self.design.save(update_fields=["elements"])

        self.assertIn("color:#123456", self._html())


class TemplateArtworkTests(RenderingTestCase):
    """Decorative, template-owned artwork.

    It used to be its own element type (STATIC_GRAPHIC) with its own resolver,
    because a template's `static_asset` was the one image an override could
    never reach. Copying the template into the design collapsed that: the
    asset's storage key is copied into the element's `content`, and from then
    on it is an ordinary image — editable, replaceable, deletable, like
    everything else on the canvas.
    """

    def setUp(self) -> None:
        super().setUp()
        self.graphic = TemplateElement.objects.create(
            template=self.template,
            key="ribbon",
            label="Decorative ribbon",
            element_type=ElementType.STATIC_GRAPHIC,
            geometry={"x": 0.0, "y": 0.0, "width": 0.2, "height": 0.2},
            static_asset=make_image_file("ribbon.png"),
            z_index=30,
        )
        # Re-copied, because the design in setUp was made before this element.
        self.design.reset_document()
        self.design.save(update_fields=["elements"])

    def render(self):
        from apps.templates.rendering import resolve_images

        return build_html(
            self.design,
            build_context(self.design),
            get_dimension("instagram_post"),
            resolve_images(self.design),
        )

    def test_the_asset_is_copied_into_the_design_as_an_ordinary_image(self):
        ribbon = self.element_of(self.design, "ribbon")

        self.assertEqual(ribbon["type"], "image")
        self.assertTrue(ribbon["content"], "the asset key should have been copied")
        self.assertFalse(ribbon["locked"])

    def test_it_renders_as_an_inlined_image(self):
        self.assertIn("data:image/png;base64,", self.render())

    def test_it_disappears_when_its_content_is_cleared(self):
        """No file, no <img> — the same 'render nothing' rule every element
        follows, and now reachable by an agent deleting the picture."""
        ribbon = self.element_of(self.design, "ribbon")
        ribbon["content"] = ""
        self.design.save(update_fields=["elements"])

        # The only other image on this template is the hero photo; if the
        # ribbon rendered, there would be a second data URI.
        self.assertEqual(self.render().count("data:image/png;base64,"), 1)

    def test_the_editor_resolved_view_gets_a_real_data_uri_not_a_raw_key(self):
        """The canvas cannot draw a storage key. `resolved_content` is the
        resolved form; `content` stays the raw key the panel edits."""
        response = self.client.get(
            self.design_action_url(self.design, "resolved"),
            {"dimension": "instagram_post"},
        )

        self.assertEqual(response.status_code, 200, response.data)
        ribbon = self._resolved(response, "ribbon")
        self.assertTrue(str(ribbon["resolved_content"]).startswith("data:image/png;base64,"))
        self.assertFalse(str(ribbon["content"]).startswith("data:"))

    def test_the_resolved_view_reports_z_index_and_safe_area(self):
        """A visual editor has to stack and position elements the same way an
        export would — it needs the same numbers html_builder uses."""
        response = self.client.get(
            self.design_action_url(self.design, "resolved"),
            {"dimension": "instagram_story"},
        )

        self.assertIn("safe_inset_top", response.data)
        self.assertGreater(response.data["safe_inset_top"], 0)
        self.assertEqual(self._resolved(response, "ribbon")["transform"]["z_index"], 30)

    def test_the_artwork_is_editable_like_anything_else(self):
        """The old contract refused this outright: a static graphic was locked
        and every write to it was a 400. It is the agent's canvas now."""
        elements = list(self.design.elements)
        for element in elements:
            if element["original_element_id"] == "ribbon":
                element["transform"] = {**element["transform"], "x": 0.5}
                element["style"] = {"opacity": 0.4}

        response = self.client.patch(
            self.design_detail_url(self.design),
            {"elements": elements},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        ribbon = self.element_of(self.design, "ribbon")
        self.assertEqual(ribbon["transform"]["x"], 0.5)
        self.assertEqual(ribbon["style"]["opacity"], 0.4)

    def test_an_image_element_still_refuses_a_url_as_its_content(self):
        """The one check that was never about permissions: a URL here would be
        fetched by the renderer, from our container, to a host the caller
        chose. That refusal survives the rewrite."""
        elements = list(self.design.elements)
        for element in elements:
            if element["original_element_id"] == "ribbon":
                element["content"] = "https://example.invalid/leak.png"

        response = self.client.patch(
            self.design_detail_url(self.design),
            {"elements": elements},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not a URL", str(response.data))

    def _resolved(self, response, original_key: str) -> dict:
        for element in response.data["elements"]:
            if element.get("original_element_id") == original_key:
                return element
        raise AssertionError(f"no resolved element for {original_key!r}")


class ExportTests(RenderingTestCase):
    def _export_url(self):
        return self.design_action_url(self.design, "export")

    @mock.patch("apps.templates.rendering.requests.post")
    def test_export_at_every_social_dimension(self, post):
        """One design, every supported size, one request."""
        post.return_value = FakeResponse()

        response = self.client.post(
            self._export_url(),
            {"dimensions": list(SOCIAL_DIMENSIONS), "export_format": "png"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        # The export response also carries the compliance report — an export
        # that passed its checks says so, rather than leaving it implied.
        self.assertEqual(len(response.data["exports"]), len(SOCIAL_DIMENSIONS))
        self.assertIn("compliance", response.data)

        by_dimension = {row["dimension"]: row for row in response.data["exports"]}
        self.assertEqual(by_dimension["instagram_post"]["width"], 1080)
        self.assertEqual(by_dimension["instagram_post"]["height"], 1080)
        self.assertEqual(by_dimension["instagram_story"]["height"], 1920)
        self.assertEqual(by_dimension["facebook"]["width"], 1200)
        self.assertEqual(by_dimension["linkedin"]["height"], 627)

        self.assertEqual(DesignExport.objects.count(), len(SOCIAL_DIMENSIONS))

    @mock.patch("apps.templates.rendering.requests.post")
    def test_each_dimension_is_rendered_at_its_own_size(self, post):
        post.return_value = FakeResponse()

        self.client.post(
            self._export_url(),
            {"dimensions": ["instagram_post", "instagram_story"]},
            format="json",
        )

        sizes = [
            (call.kwargs["json"]["width"], call.kwargs["json"]["height"])
            for call in post.call_args_list
        ]
        self.assertEqual(sizes, [(1080, 1080), (1080, 1920)])

    @mock.patch("apps.templates.rendering.requests.post")
    def test_exports_are_saved_through_the_storage_abstraction(self, post):
        post.return_value = FakeResponse()

        self.client.post(self._export_url(), {"dimensions": ["facebook"]}, format="json")

        export = DesignExport.objects.get()
        # Same namespaced-key convention as every other stored file, so exports
        # migrate to object storage with everything else.
        self.assertTrue(export.image.name.startswith("designs/exports/"))
        self.assertTrue(export.image.storage.exists(export.image.name))
        self.assertEqual(export.bytes, len(PNG_BYTES))
        self.assertEqual(export.render_ms, 142)

    @mock.patch("apps.templates.rendering.requests.post")
    def test_jpg_export(self, post):
        post.return_value = FakeResponse(
            headers={"Content-Type": "image/jpeg", "X-Render-Ms": "90"}
        )

        response = self.client.post(
            self._export_url(),
            {"dimensions": ["linkedin"], "export_format": "jpg"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["exports"]), 1)
        export = DesignExport.objects.get()
        self.assertEqual(export.export_format, ExportFormat.JPG)
        self.assertTrue(export.image.name.endswith(".jpg"))
        self.assertEqual(post.call_args.kwargs["json"]["format"], "jpg")

    @mock.patch("apps.templates.rendering.requests.post")
    def test_pdf_export(self, post):
        post.return_value = FakeResponse(
            content=b"%PDF-1.7 fake pdf bytes",
            headers={"Content-Type": "application/pdf", "X-Render-Ms": "210"},
        )

        response = self.client.post(
            self._export_url(),
            {"dimensions": ["instagram_post"], "export_format": "pdf"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        export = DesignExport.objects.get()
        self.assertEqual(export.export_format, ExportFormat.PDF)
        self.assertTrue(export.image.name.endswith(".pdf"))
        # The renderer payload asks for the print pipeline, not a screenshot.
        self.assertEqual(post.call_args.kwargs["json"]["format"], "pdf")

    @mock.patch("apps.templates.rendering.requests.post")
    def test_duplicate_dimensions_are_rendered_once(self, post):
        post.return_value = FakeResponse()

        self.client.post(
            self._export_url(),
            {"dimensions": ["facebook", "facebook"]},
            format="json",
        )

        self.assertEqual(post.call_count, 1)

    def test_unknown_dimension_is_rejected(self):
        response = self.client.post(
            self._export_url(), {"dimensions": ["myspace"]}, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_empty_dimension_list_is_rejected(self):
        response = self.client.post(self._export_url(), {"dimensions": []}, format="json")

        self.assertEqual(response.status_code, 400)

    @mock.patch("apps.templates.rendering.requests.post")
    def test_exports_are_listed_for_their_design(self, post):
        post.return_value = FakeResponse()
        self.client.post(self._export_url(), {"dimensions": ["facebook"]}, format="json")

        response = self.client.get(self.exports_url, {"design": self.design.pk})

        self.assertEqual(response.data["count"], 1)
        self.assertTrue(response.data["results"][0]["image_url"].startswith("http"))

    @mock.patch("apps.templates.rendering.requests.post")
    def test_the_renderer_token_is_sent(self, post):
        post.return_value = FakeResponse()

        self.client.post(self._export_url(), {"dimensions": ["facebook"]}, format="json")

        self.assertIn("X-Renderer-Token", post.call_args.kwargs["headers"])

    @mock.patch("apps.templates.rendering.requests.post")
    def test_preview_returns_an_inline_image_and_saves_nothing(self, post):
        post.return_value = FakeResponse()

        response = self.client.post(
            self.design_action_url(self.design, "preview"),
            {"dimension": "instagram_post"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["image"].startswith("data:image/png;base64,"))
        self.assertEqual(DesignExport.objects.count(), 0)


class RenderFailureTests(RenderingTestCase):
    @mock.patch("apps.templates.rendering.requests.post")
    def test_renderer_unreachable_gives_503_and_saves_nothing(self, post):
        import requests

        post.side_effect = requests.ConnectionError("connection refused")

        response = self.client.post(
            self.design_action_url(self.design, "export"),
            {"dimensions": ["facebook"]},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("saved", response.data["detail"])
        self.assertEqual(DesignExport.objects.count(), 0)

    @mock.patch("apps.templates.rendering.requests.post")
    def test_renderer_error_gives_502(self, post):
        post.return_value = FakeResponse(
            status_code=500, payload={"detail": "Render failed: page crashed"}
        )

        response = self.client.post(
            self.design_action_url(self.design, "export"),
            {"dimensions": ["facebook"]},
            format="json",
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(DesignExport.objects.count(), 0)

    @mock.patch("apps.templates.rendering.requests.post")
    def test_a_partial_bundle_keeps_what_succeeded(self, post):
        """Second dimension fails: the first is still saved and reported."""
        import requests

        post.side_effect = [FakeResponse(), requests.ConnectionError("gone")]

        response = self.client.post(
            self.design_action_url(self.design, "export"),
            {"dimensions": ["instagram_post", "facebook"]},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(DesignExport.objects.count(), 1)
        self.assertEqual(DesignExport.objects.get().dimension, "instagram_post")


class RenderPermissionTests(RenderingTestCase):
    """Rendering costs a browser page and writes a file — it is not a read."""

    def setUp(self) -> None:
        super().setUp()
        self.other_agent, self.other_profile = self.make_agent_in(
            self.acme, "b@example.com"
        )

    @mock.patch("apps.templates.rendering.requests.post")
    def test_another_agent_cannot_export_your_design(self, post):
        post.return_value = FakeResponse()
        self.authenticate_as(self.other_agent)

        response = self.client.post(
            self.design_action_url(self.design, "export"),
            {"dimensions": ["facebook"]},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        post.assert_not_called()

    @mock.patch("apps.templates.rendering.requests.post")
    def test_another_agent_cannot_preview_your_design(self, post):
        post.return_value = FakeResponse()
        self.authenticate_as(self.other_agent)

        response = self.client.post(
            self.design_action_url(self.design, "preview"), {}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        post.assert_not_called()

    @mock.patch("apps.templates.rendering.requests.post")
    def test_another_agent_cannot_list_your_exports(self, post):
        post.return_value = FakeResponse()
        self.client.post(
            self.design_action_url(self.design, "export"),
            {"dimensions": ["facebook"]},
            format="json",
        )

        self.authenticate_as(self.other_agent)
        response = self.client.get(self.exports_url)

        self.assertEqual(response.data["count"], 0)


class DimensionEndpointTests(TemplateAPITestCase):
    def test_dimensions_are_published(self):
        agent, _ = self.make_agent_in(self.make_brokerage("Acme"), "a@example.com")
        self.authenticate_as(agent)

        response = self.client.get(self.dimensions_url)

        self.assertEqual(response.status_code, 200)
        keys = {row["key"] for row in response.data}
        # The four platform formats must always be offered. The set is allowed
        # to grow — portrait_tall was added for artwork whose native shape is
        # neither square nor a Story — so this asserts presence, not equality;
        # freezing it made adding a format look like a regression.
        self.assertLessEqual(
            {"instagram_post", "instagram_story", "facebook", "linkedin"}, keys
        )
        self.assertEqual(keys, set(SOCIAL_DIMENSIONS))

    def test_safe_area_insets_are_published(self):
        """A canvas editor needs these to place elements the same place
        html_builder does — without them Story content would be positioned
        against the raw canvas edge, under the platform's own chrome."""
        agent, _ = self.make_agent_in(self.make_brokerage("Acme"), "a@example.com")
        self.authenticate_as(agent)

        response = self.client.get(self.dimensions_url)

        by_key = {row["key"]: row for row in response.data}
        self.assertGreater(by_key["instagram_story"]["safe_inset_top"], 0)
        self.assertGreater(by_key["instagram_story"]["safe_inset_bottom"], 0)
        self.assertEqual(by_key["instagram_post"]["safe_inset_top"], 0)
