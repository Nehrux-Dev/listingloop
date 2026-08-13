"""The export readiness gate.

"Do not silently render broken/empty elements" — this is the
check that holds that line, and the tests below are mostly about it *not*
over-firing, because a gate that blocks things it shouldn't gets worked around.
"""

from __future__ import annotations

import shutil
import tempfile
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from apps.accounts.tests.base import make_image_file
from apps.listings.models import ListingPhoto
from apps.templates.models import ElementType, TemplateElement
from apps.templates.readiness import (
    DesignNotReadyError,
    assess_design,
    require_design_ready,
)
from apps.templates.render_context import build_context
from apps.templates.tests.base import TemplateAPITestCase
from apps.templates.tests.test_calendar import make_seasonal_template

MEDIA_ROOT = tempfile.mkdtemp(prefix="real-estate-readiness-media-")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ReadinessTestCase(TemplateAPITestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.acme.required_disclaimer = "A guide only."
        self.acme.logo = make_image_file("logo.png")
        self.acme.save()

        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.profile.name = "Alex Agent"
        self.profile.phone = "+1 416 555 0100"
        self.profile.photo = make_image_file("headshot.png")
        self.profile.save()

        self.template = self.make_template()
        self.listing = self.make_verified_listing(self.profile, self.agent)
        ListingPhoto.objects.create(
            listing=self.listing, image=make_image_file("hero.png"), order=0
        )
        self.design = self.make_design(self.template, self.profile, self.listing)
        self.authenticate_as(self.agent)

    def missing_labels(self, design=None):
        design = design or self.design
        return [item.label for item in assess_design(design, build_context(design))]

    def recopy(self):
        """Re-copy the template into the design.

        Needed whenever a test adds a TemplateElement after ``setUp`` has
        already created the design. That is not a quirk of the fixture — it is
        the copy architecture: a design is a snapshot, so a template edited
        afterwards does not reach back into designs already made from it.
        ``test_a_template_element_added_later_does_not_appear`` pins exactly
        that, so this helper cannot quietly paper over a regression in it.
        """
        self.design.reset_document()
        self.design.save(update_fields=["elements"])


class GateTests(ReadinessTestCase):
    def test_a_complete_design_is_ready(self):
        require_design_ready(self.design, build_context(self.design))  # no raise

        self.assertEqual(self.missing_labels(), [])

    def test_an_element_bound_to_missing_data_blocks(self):
        """The hero photo is bound to the listing's first photo. With no photo
        the design would export a blank rectangle, so it is refused."""
        self.listing.photos.all().delete()

        with self.assertRaises(DesignNotReadyError) as ctx:
            require_design_ready(self.design, build_context(self.design))

        self.assertIn("Main photo", str(ctx.exception))

    def test_deleting_the_element_is_a_valid_way_to_clear_the_block(self):
        """The old model had no answer to "I do not want a photo on this one" —
        `required` was the template's decision. Now it is the agent's."""
        self.listing.photos.all().delete()
        hero = self.element_of(self.design, "hero_photo")
        self.design.elements = [
            element for element in self.design.elements if element["id"] != hero["id"]
        ]
        self.design.save(update_fields=["elements"])

        require_design_ready(self.design, build_context(self.design))  # no raise

    def test_a_template_element_added_later_does_not_appear_in_an_existing_design(self):
        """The copy is a snapshot. Editing a template must not reach into work
        an agent has already started — that is the whole reason for the copy."""
        before = len(self.design.elements)
        TemplateElement.objects.create(
            template=self.template,
            key="added_after_the_fact",
            label="Added later",
            element_type=ElementType.TEXT,
            geometry={"x": 0.1, "y": 0.9, "width": 0.5, "height": 0.04},
            default_content="New",
        )

        self.design.refresh_from_db()

        self.assertEqual(len(self.design.elements), before)
        self.assertNotIn(
            "added_after_the_fact",
            [e["original_element_id"] for e in self.design.elements],
        )

    def test_a_missing_listing_photo_points_at_the_listing_not_the_profile(self):
        """Sending an agent to Brokerage settings to fix a listing photo is
        worse than a vague message — they would look and find nothing wrong."""
        self.listing.photos.all().delete()

        missing = assess_design(self.design, build_context(self.design))

        self.assertEqual(missing[0].step, "listing")

    def test_a_missing_brokerage_disclaimer_blocks_and_names_the_step(self):
        self.acme.required_disclaimer = ""
        self.acme.save()
        self.profile.refresh_from_db()

        missing = assess_design(self.design, build_context(self.design))

        self.assertIn("Required disclaimer", [item.label for item in missing])
        self.assertEqual(
            next(item.step for item in missing if item.label == "Required disclaimer"),
            "brokerage",
        )

    def test_a_template_that_never_shows_a_logo_is_not_blocked_for_one(self):
        """The reason this is per-design and not per-profile."""
        self.acme.logo = None
        self.acme.save()
        self.profile.refresh_from_db()

        # The listing template shows no brokerage logo, so removing it changes
        # nothing.
        self.assertEqual(self.missing_labels(), [])

    def test_a_hidden_element_is_not_required(self):
        """An agent who switched something off has decided it is not needed."""
        self.listing.photos.all().delete()
        self.element_of(self.design, "hero_photo")["visible"] = False
        self.design.save()

        self.assertEqual(self.missing_labels(), [])

    def test_an_optional_empty_element_does_not_block(self):
        TemplateElement.objects.create(
            template=self.template,
            key="optional_note",
            label="Optional note",
            element_type=ElementType.TEXT,
            geometry={"x": 0.1, "y": 0.5, "width": 0.8, "height": 0.05},
            style_properties={"font_size_ratio": 0.02},
            # No content_source and no default — simply an empty box the
            # agent left on the canvas, which is their business.
        )
        self.recopy()

        self.assertEqual(self.missing_labels(), [])

    def test_a_duplicate_field_is_reported_once(self):
        """A template can show the same thing twice; say so once."""
        self.acme.required_disclaimer = ""
        self.acme.save()
        TemplateElement.objects.create(
            template=self.template,
            key="disclaimer_repeat",
            label="Disclaimer again",
            element_type=ElementType.TEXT,
            geometry={"x": 0.1, "y": 0.8, "width": 0.8, "height": 0.03},
            style_properties={"font_size_ratio": 0.013},
            content_source="brokerage.required_disclaimer",
        )
        self.profile.refresh_from_db()
        self.recopy()

        labels = self.missing_labels()

        self.assertEqual(labels.count("Required disclaimer"), 1)

    def test_an_unresolved_placeholder_blocks(self):
        """"Call " with no number reads as finished when it is not."""
        self.profile.phone = ""
        self.profile.save()
        TemplateElement.objects.create(
            template=self.template,
            key="byline",
            label="Byline",
            element_type=ElementType.TEXT,
            geometry={"x": 0.1, "y": 0.7, "width": 0.8, "height": 0.05},
            style_properties={"font_size_ratio": 0.02},
            default_content="Call {{ agent.phone }} today",
        )
        self.recopy()

        self.assertIn("Professional phone", self.missing_labels())

    def test_a_seasonal_design_with_no_listing_is_judged_on_its_own_terms(self):
        seasonal = make_seasonal_template()
        design = self.make_design(seasonal, self.profile, listing=None)

        # No listing at all, and that is fine — nothing on the card asks for one.
        self.assertEqual(self.missing_labels(design), [])


class GateApiTests(ReadinessTestCase):
    @mock.patch("apps.templates.rendering.requests.post")
    def test_a_ready_design_exports(self, post):
        from apps.templates.tests.test_rendering import FakeResponse

        post.return_value = FakeResponse()

        response = self.client.post(
            self.design_action_url(self.design, "export"),
            {"dimensions": ["facebook"]},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)

    @mock.patch("apps.templates.rendering.requests.post")
    def test_an_unready_design_is_refused_before_anything_renders(self, post):
        self.listing.photos.all().delete()

        response = self.client.post(
            self.design_action_url(self.design, "export"),
            {"dimensions": ["facebook"]},
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("Main photo", response.data["detail"])
        # Nothing was rendered, so nothing was paid for.
        post.assert_not_called()

    def test_the_refusal_names_the_screen_that_fixes_it(self):
        self.acme.required_disclaimer = ""
        self.acme.save()

        response = self.client.post(
            self.design_action_url(self.design, "export"),
            {"dimensions": ["facebook"]},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("brokerage", response.data["steps"])
        self.assertTrue(response.data["missing"][0]["step_label"])

    def test_readiness_can_be_checked_without_exporting(self):
        response = self.client.get(self.design_action_url(self.design, "readiness"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ready"])
        self.assertEqual(response.data["missing"], [])

    def test_readiness_reports_gaps_while_the_agent_is_still_working(self):
        self.listing.photos.all().delete()

        response = self.client.get(self.design_action_url(self.design, "readiness"))

        self.assertFalse(response.data["ready"])
        self.assertEqual(response.data["missing"][0]["label"], "Main photo")

    @mock.patch("apps.templates.rendering.requests.post")
    def test_preview_is_not_gated(self, post):
        """Seeing what is missing is exactly why an agent previews."""
        from apps.templates.tests.test_rendering import FakeResponse

        post.return_value = FakeResponse()
        self.listing.photos.all().delete()

        response = self.client.post(
            self.design_action_url(self.design, "preview"),
            {"dimension": "instagram_post"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_another_agent_cannot_probe_readiness(self):
        other_agent, _ = self.make_agent_in(self.acme, "b@example.com")
        self.authenticate_as(other_agent)

        response = self.client.get(self.design_action_url(self.design, "readiness"))

        self.assertEqual(response.status_code, 404)
