"""The seed_templates command, focused on "Feature Showcase — Warm Editorial".

That template was authored from a client-supplied reference image specifically
to exercise every capability this build added: STATIC_GRAPHIC (the generated
dot-cluster asset), a FREE text element (cloneable, rotatable), and a listing
photo used alongside two agent-uploaded ones. Worth its own coverage — a
regression here is a regression in the actual proof that the conversion
process works, not just an abstract feature.
"""

from __future__ import annotations

import shutil
import tempfile

from django.core.management import call_command
from django.test import override_settings

from apps.templates.models import ElementType, Template
from apps.templates.tests.base import TemplateAPITestCase

MEDIA_ROOT = tempfile.mkdtemp(prefix="real-estate-seed-templates-media-")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class FeatureShowcaseSeedTests(TemplateAPITestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        call_command("seed_templates")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.template = Template.objects.get(slug="feature-showcase-warm-editorial")

    def test_it_is_active_and_needs_no_listing(self):
        self.assertTrue(self.template.is_active)
        self.assertFalse(self.template.requires_listing)

    def test_it_has_the_expected_element_count(self):
        self.assertEqual(self.template.elements.count(), 13)

    def test_the_dot_cluster_is_a_real_generated_asset(self):
        dots = self.template.elements.get(key="dot_cluster")

        self.assertEqual(dots.element_type, ElementType.STATIC_GRAPHIC)
        self.assertTrue(dots.static_asset)
        self.assertGreater(dots.static_asset.size, 0)

    def test_every_element_of_the_seeded_template_copies_into_a_design_unlocked(self):
        """The seeded library is the product's own content, and it is the
        strongest place to check the new contract: if anything Nehrux authors
        could still arrive locked, an agent would meet it on day one."""
        from apps.templates.document import elements_from_template

        elements = elements_from_template(self.template)

        self.assertEqual(len(elements), self.template.elements.count())
        self.assertEqual([], [e["name"] for e in elements if e["locked"]])
        self.assertTrue(all(e["visible"] for e in elements))

    def test_the_hero_photo_auto_fills_from_a_listing(self):
        """The binding survives the copy, which is what makes property data
        land on the right element when the template is opened."""
        from apps.templates.document import elements_from_template

        photo = self.template.elements.get(key="primary_photo")
        self.assertEqual(photo.content_source, "listing.photo")

        copied = next(
            e for e in elements_from_template(self.template)
            if e["original_element_id"] == "primary_photo"
        )
        self.assertEqual(copied["bound_to"], "photo_1")

    def test_a_colour_that_would_inject_css_is_still_refused(self):
        """The check that outlived the permission model.

        `background_color` is interpolated straight into a style attribute in
        HTML a real browser then executes, so `#fff;background-image:url(...)`
        would be an outbound request from the renderer to a host the caller
        picked. That was never a permission rule — it is why every colour is
        matched against a hex literal or a brand token and nothing else.
        """
        from apps.templates.document import (
            DocumentValidationError,
            elements_from_template,
        )
        from apps.templates.document import validate_document

        elements = elements_from_template(self.template)
        elements[0]["style"]["background_color"] = (
            "#ffffff;background-image:url(https://example.invalid/x.png)"
        )

        with self.assertRaises(DocumentValidationError):
            validate_document(elements)

    def test_rerunning_the_seed_command_does_not_duplicate_it(self):
        call_command("seed_templates")

        self.assertEqual(
            Template.objects.filter(slug="feature-showcase-warm-editorial").count(), 1
        )
        self.template.refresh_from_db()
        self.assertEqual(self.template.elements.count(), 13)

    def test_it_renders_to_a_real_image_with_no_listing_attached(self):
        from apps.templates.html_builder import build_html
        from apps.templates.models import Design
        from apps.templates.render_context import build_context
        from apps.templates.rendering import resolve_images

        acme = self.make_brokerage("Acme Realty")
        _agent, profile = self.make_agent_in(acme, "showcase@example.com")
        design = Design.objects.create(
            name="Render check", template=self.template, agent=profile, listing=None
        )

        html = build_html(
            design, build_context(design), _dimension(), resolve_images(design)
        )

        # The dot cluster and the two locked colour shapes must appear even
        # though nothing about this design was customised — decorative
        # elements are not something an agent opts into.
        self.assertIn("data:image/png;base64,", html)  # the dot cluster
        self.assertIn("Exquisite solutions for your space.", html)
        self.assertIn("Learn more", html)


def _dimension():
    from apps.templates.dimensions import get_dimension

    return get_dimension("instagram_story")
