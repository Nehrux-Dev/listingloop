"""The template data resolver and `{{ placeholder }}` interpolation.

The point of onboarding is that an agent enters their professional and brand
information once. These tests are what hold that promise: the resolver has to
find that data without the template knowing where it lives, and a design must
never be asked for it again.
"""

from __future__ import annotations

import shutil
import tempfile

from django.test import override_settings

from apps.accounts.models import BrandKit
from apps.accounts.tests.base import make_image_file
from apps.templates.html_builder import interpolate, unresolved_placeholders
from apps.templates.render_context import build_context, build_template_context
from apps.templates.tests.base import TemplateAPITestCase

MEDIA_ROOT = tempfile.mkdtemp(prefix="real-estate-context-media-")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class TemplateContextTests(TemplateAPITestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Harbour & Co Realty")
        self.acme.required_disclaimer = "All figures are a guide only."
        self.acme.phone = "+1 416 555 0000"
        self.acme.licence_number = "BRK-42"
        self.acme.save()

        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.agent.first_name = "John"
        self.agent.last_name = "Smith"
        self.agent.save()

        self.profile.name = "John Smith"
        self.profile.job_title = "REALTOR®"
        self.profile.phone = "+1 416 555 0100"
        self.profile.email = "john@example.com"
        self.profile.tagline = "Your Toronto Home Expert"
        self.profile.licence_number = "RECO-123456"
        self.profile.save()

        self.listing = self.make_verified_listing(self.profile, self.agent)

    # -- shape ---------------------------------------------------------------

    def test_the_context_has_the_four_documented_sections(self):
        context = build_template_context(self.profile, self.listing)

        self.assertEqual(
            {"agent", "brokerage", "brand", "property"} & set(context),
            {"agent", "brokerage", "brand", "property"},
        )

    def test_agent_information_comes_from_onboarding(self):
        agent = build_template_context(self.profile, self.listing)["agent"]

        self.assertEqual(agent["full_name"], "John Smith")
        self.assertEqual(agent["job_title"], "REALTOR®")
        self.assertEqual(agent["phone"], "+1 416 555 0100")
        self.assertEqual(agent["email"], "john@example.com")
        self.assertEqual(agent["tagline"], "Your Toronto Home Expert")
        self.assertEqual(agent["licence_number"], "RECO-123456")

    def test_brokerage_information_comes_from_onboarding(self):
        brokerage = build_template_context(self.profile, self.listing)["brokerage"]

        self.assertEqual(brokerage["name"], "Harbour & Co Realty")
        self.assertEqual(brokerage["disclaimer"], "All figures are a guide only.")
        self.assertEqual(brokerage["licence_number"], "BRK-42")

    def test_property_information_comes_from_the_listing(self):
        prop = build_template_context(self.profile, self.listing)["property"]

        self.assertEqual(prop["address"], self.listing.address)
        self.assertEqual(prop["bedrooms"], 4)
        self.assertEqual(prop["price"], 1850000.0)
        self.assertEqual(prop["property_type"], "House")

    def test_the_agents_own_brand_kit_wins(self):
        BrandKit.objects.create(agent=self.profile, primary_color="#123456")

        brand = build_template_context(self.profile, self.listing)["brand"]

        self.assertEqual(brand["primary_color"], "#123456")

    def test_the_brokerage_brand_kit_is_the_fallback(self):
        """So an agent who never set personal colours still gets branded work."""
        BrandKit.objects.create(brokerage=self.acme, primary_color="#654321")

        brand = build_template_context(self.profile, self.listing)["brand"]

        self.assertEqual(brand["primary_color"], "#654321")

    def test_defaults_apply_when_there_is_no_brand_kit_at_all(self):
        brand = build_template_context(self.profile, self.listing)["brand"]

        self.assertTrue(brand["primary_color"].startswith("#"))
        self.assertTrue(brand["font"])

    def test_property_is_empty_without_a_listing(self):
        """Seasonal and agent-led templates have no property."""
        context = build_template_context(self.profile, None)

        self.assertEqual(context["property"], {})
        self.assertTrue(context["agent"]["full_name"])

    def test_the_original_key_names_still_resolve(self):
        """Templates authored before this resolver keep working."""
        context = build_template_context(self.profile, self.listing)

        self.assertIs(context["brand_kit"], context["brand"])
        self.assertIs(context["listing"], context["property"])

    def test_a_design_resolves_through_the_same_function(self):
        """One implementation of “what data does a template get”."""
        design = self.make_design(self.make_template(), self.profile, self.listing)

        from_design = build_context(design)
        direct = build_template_context(self.profile, self.listing)

        self.assertEqual(from_design["agent"]["full_name"], direct["agent"]["full_name"])
        self.assertEqual(from_design["property"]["address"], direct["property"]["address"])

    def test_images_are_inlined_for_the_renderer(self):
        self.profile.photo = make_image_file("headshot.png")
        self.profile.save()
        self.acme.logo = make_image_file("logo.png")
        self.acme.save()
        self.profile.refresh_from_db()

        context = build_template_context(self.profile, self.listing)

        self.assertTrue(context["agent"]["photo"].startswith("data:image/"))
        self.assertTrue(context["brokerage"]["logo"].startswith("data:image/"))


class PlaceholderTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.context = {
            "agent": {"full_name": "John Smith", "phone": "+1 416 555 0100"},
            "brokerage": {"name": "Harbour & Co", "disclaimer": ""},
            "brand": {"primary_color": "#123456"},
            "property": {"price": 1850000.0, "bedrooms": 4, "photos": ["a", "b"]},
        }

    def test_a_placeholder_is_substituted(self):
        self.assertEqual(
            interpolate("Presented by {{ agent.full_name }}", self.context),
            "Presented by John Smith",
        )

    def test_several_placeholders_in_one_string(self):
        result = interpolate(
            "{{ agent.full_name }} at {{ brokerage.name }} — {{ agent.phone }}",
            self.context,
        )

        self.assertEqual(result, "John Smith at Harbour & Co — +1 416 555 0100")

    def test_whitespace_inside_the_braces_is_tolerated(self):
        self.assertEqual(
            interpolate("{{agent.full_name}} / {{   agent.full_name   }}", self.context),
            "John Smith / John Smith",
        )

    def test_a_filter_can_format_the_value(self):
        self.assertEqual(
            interpolate("{{ property.price | currency }}", self.context),
            "$1,850,000",
        )

    def test_an_unknown_placeholder_becomes_empty_not_literal(self):
        """A rendered image reading "{{ agent.nickname }}" is worse than a gap —
        and the completion gate is what stops the gap reaching a render."""
        result = interpolate("Ask {{ agent.nickname }} today", self.context)

        self.assertNotIn("{{", result)
        self.assertEqual(result, "Ask  today")

    def test_text_without_placeholders_is_untouched(self):
        self.assertEqual(interpolate("Just some copy.", self.context), "Just some copy.")

    def test_indexing_into_a_list_works(self):
        self.assertEqual(interpolate("{{ property.photos[1] }}", self.context), "b")

    def test_unresolved_placeholders_can_be_listed(self):
        missing = unresolved_placeholders(
            "{{ agent.full_name }} {{ brokerage.disclaimer }} {{ agent.nickname }}",
            self.context,
        )

        self.assertEqual(set(missing), {"brokerage.disclaimer", "agent.nickname"})

    def test_a_string_with_no_placeholders_reports_none_missing(self):
        self.assertEqual(unresolved_placeholders("Plain copy", self.context), [])


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class PlaceholderRenderingTests(TemplateAPITestCase):
    """Placeholders resolving through the real element pipeline."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Harbour & Co Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.profile.name = "John Smith"
        self.profile.phone = "+1 416 555 0100"
        self.profile.save()
        self.listing = self.make_verified_listing(self.profile, self.agent)

    def test_a_template_default_can_use_placeholders(self):
        from apps.templates.dimensions import get_dimension
        from apps.templates.html_builder import build_html
        from apps.templates.models import ElementPermission, ElementType, TemplateElement

        template = self.make_template()
        TemplateElement.objects.create(
            template=template,
            key="byline",
            label="Byline",
            element_type=ElementType.TEXT,
            permission=ElementPermission.CONTENT_ONLY,
            geometry={"x": 0.1, "y": 0.9, "width": 0.8, "height": 0.05},
            style_properties={"font_size_ratio": 0.02},
            default_content="Presented by {{ agent.full_name }} · {{ agent.phone }}",
        )
        design = self.make_design(template, self.profile, self.listing)

        html = build_html(
            design, build_context(design), get_dimension("instagram_post"), {}
        )

        self.assertIn("Presented by John Smith", html)
        self.assertIn("+1 416 555 0100", html)
        self.assertNotIn("{{", html)

    def test_an_agents_own_override_can_use_placeholders_too(self):
        from apps.templates.dimensions import get_dimension
        from apps.templates.html_builder import build_html

        template = self.make_template()
        design = self.make_design(
            template,
            self.profile,
            self.listing,
            overrides={"headline": {"text": "Call {{ agent.full_name }}"}},
        )

        html = build_html(
            design, build_context(design), get_dimension("instagram_post"), {}
        )

        self.assertIn("Call John Smith", html)
