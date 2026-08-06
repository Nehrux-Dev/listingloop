"""Content calendar: seasonal templates used with no listing attached.

The point of this file is the "no listing" path. Everything in Step 5 assumed a
property; a Diwali card has none, and the whole flow — create, edit, render,
export — has to work anyway.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from apps.templates.models import (
    CalendarEvent,
    Design,
    ElementPermission,
    ElementType,
    Template,
    TemplateCategory,
    TemplateElement,
    TemplateStyle,
)
from apps.templates.tests.base import TemplateAPITestCase


def make_seasonal_template(**overrides) -> Template:
    """A festival card: no element references a listing."""
    defaults = {
        "name": "Diwali Card",
        "slug": "diwali-card",
        "category": TemplateCategory.DIWALI,
        "style": TemplateStyle.LUXURY,
        "layout_definition": {"background_color": "#0F172A"},
    }
    defaults.update(overrides)
    template = Template.objects.create(**defaults)

    TemplateElement.objects.create(
        template=template,
        key="greeting",
        label="Greeting",
        element_type=ElementType.TEXT,
        permission=ElementPermission.CONTENT_ONLY,
        geometry={"x": 0.08, "y": 0.3, "width": 0.84, "height": 0.16},
        style_properties={"font_size_ratio": 0.075, "color": "#FFFFFF"},
        default_content="Happy Diwali",
        constraints={"max_length": 60},
        z_index=5,
    )
    TemplateElement.objects.create(
        template=template,
        key="agent_name",
        label="Agent name",
        element_type=ElementType.TEXT,
        permission=ElementPermission.CONTENT_ONLY,
        geometry={"x": 0.1, "y": 0.85, "width": 0.8, "height": 0.05},
        style_properties={"font_size_ratio": 0.03, "color": "#FFFFFF"},
        content_source="agent.name",
        z_index=6,
    )
    TemplateElement.objects.create(
        template=template,
        key="disclaimer",
        label="Disclaimer",
        element_type=ElementType.TEXT,
        permission=ElementPermission.LOCKED,
        geometry={"x": 0.05, "y": 0.96, "width": 0.9, "height": 0.03},
        style_properties={"font_size_ratio": 0.013, "color": "#94A3B8"},
        content_source="brokerage.required_disclaimer",
        z_index=20,
    )
    return template


class SeasonalTemplateTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.seasonal = make_seasonal_template()
        self.listing_template = self.make_template()  # a New Listing template
        self.authenticate_as(self.agent)

    def test_seasonal_templates_are_marked_as_needing_no_listing(self):
        response = self.client.get(self.template_detail_url(self.seasonal))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["requires_listing"])
        self.assertTrue(response.data["is_seasonal"])

    def test_listing_templates_are_marked_as_needing_one(self):
        response = self.client.get(self.template_detail_url(self.listing_template))

        self.assertTrue(response.data["requires_listing"])
        self.assertFalse(response.data["is_seasonal"])

    def test_the_library_can_be_filtered_to_seasonal_templates(self):
        response = self.client.get(self.templates_url, {"seasonal": "true"})

        names = [row["name"] for row in response.data["results"]]
        self.assertEqual(names, ["Diwali Card"])

    def test_the_library_can_exclude_seasonal_templates(self):
        response = self.client.get(self.templates_url, {"seasonal": "false"})

        names = [row["name"] for row in response.data["results"]]
        self.assertNotIn("Diwali Card", names)

    def test_the_library_can_ask_for_everything_usable_without_a_listing(self):
        """Seasonal plus agent-led — what an agent between listings can post."""
        agent_led = self.make_template(
            name="About me",
            slug="about-me",
            category=TemplateCategory.AGENT_INTRODUCTION,
        )

        response = self.client.get(self.templates_url, {"no_listing_required": "true"})

        names = {row["name"] for row in response.data["results"]}
        self.assertIn("Diwali Card", names)
        self.assertIn(agent_led.name, names)
        self.assertNotIn(self.listing_template.name, names)

    def test_the_new_festival_categories_appear_in_the_facets(self):
        response = self.client.get(self.template_facets_url)

        values = {row["value"] for row in response.data["categories"]}
        for expected in ("christmas", "diwali", "eid", "lunar_new_year", "canada_day"):
            self.assertIn(expected, values)


class DesignWithoutListingTests(TemplateAPITestCase):
    """The whole flow, with nothing attached."""

    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.acme.required_disclaimer = "Figures are indicative only."
        self.acme.save()
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.profile.name = "Alex Agent"
        self.profile.save()
        self.seasonal = make_seasonal_template()
        self.authenticate_as(self.agent)

    def test_a_design_can_be_created_with_no_listing(self):
        response = self.client.post(
            self.designs_url,
            {"name": "Diwali 2026", "template": self.seasonal.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        design = Design.objects.get()
        self.assertIsNone(design.listing)

    def test_a_listing_template_still_requires_one(self):
        """A "Just Sold" card with no property has nothing to say."""
        listing_template = self.make_template()

        response = self.client.post(
            self.designs_url,
            {"name": "Empty", "template": listing_template.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("listing", response.data)
        self.assertIn("specific property", str(response.data["listing"]))

    def test_the_design_resolves_without_a_listing(self):
        design = self.make_design(self.seasonal, self.profile, listing=None)

        response = self.client.get(self.design_action_url(design, "resolved"))

        self.assertEqual(response.status_code, 200)
        by_key = {element["key"]: element for element in response.data["elements"]}
        # Agent and brokerage sources still resolve...
        self.assertEqual(by_key["agent_name"]["content"], "Alex Agent")
        self.assertEqual(by_key["disclaimer"]["content"], "Figures are indicative only.")
        # ...and the literal default is used where there is no source.
        self.assertEqual(by_key["greeting"]["content"], "Happy Diwali")

    def test_the_html_builds_without_a_listing(self):
        """The renderer must not assume a property exists."""
        from apps.templates.dimensions import get_dimension
        from apps.templates.html_builder import build_html
        from apps.templates.render_context import build_context

        design = self.make_design(self.seasonal, self.profile, listing=None)
        context = build_context(design)
        html = build_html(design, context, get_dimension("instagram_post"), {})

        self.assertIn("Happy Diwali", html)
        self.assertIn("Alex Agent", html)

    def test_permissions_still_apply_without_a_listing(self):
        design = self.make_design(self.seasonal, self.profile, listing=None)

        locked = self.client.patch(
            self.design_detail_url(design),
            {"overrides": {"disclaimer": {"text": "Removed"}}},
            format="json",
        )
        allowed = self.client.patch(
            self.design_detail_url(design),
            {"overrides": {"greeting": {"text": "Shubh Deepavali"}}},
            format="json",
        )

        self.assertEqual(locked.status_code, 400)
        self.assertEqual(allowed.status_code, 200)

    @mock.patch("apps.templates.rendering.requests.post")
    def test_a_listingless_design_exports(self, post):
        from apps.templates.tests.test_rendering import FakeResponse

        post.return_value = FakeResponse()
        design = self.make_design(self.seasonal, self.profile, listing=None)

        response = self.client.post(
            self.design_action_url(design, "export"),
            {"dimensions": ["instagram_post"]},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data["exports"]), 1)

    def test_a_design_can_be_tied_to_the_occasion(self):
        event = CalendarEvent.objects.create(
            name="Diwali",
            slug="diwali",
            category=TemplateCategory.DIWALI,
            date=timezone.localdate() + timedelta(days=30),
        )

        response = self.client.post(
            self.designs_url,
            {
                "name": "Diwali 2026",
                "template": self.seasonal.pk,
                "calendar_event": event.pk,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Design.objects.get().calendar_event, event)


class CalendarEventTests(TemplateAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.acme = self.make_brokerage("Acme Realty")
        self.agent, self.profile = self.make_agent_in(self.acme, "a@example.com")
        self.seasonal = make_seasonal_template()

        today = timezone.localdate()
        self.soon = CalendarEvent.objects.create(
            name="Diwali", slug="diwali", category=TemplateCategory.DIWALI,
            date=today + timedelta(days=10), needs_date_review=True,
        )
        self.later = CalendarEvent.objects.create(
            name="Christmas", slug="christmas", category=TemplateCategory.CHRISTMAS,
            date=today + timedelta(days=120),
        )
        self.past = CalendarEvent.objects.create(
            name="Canada Day", slug="canada-day", category=TemplateCategory.CANADA_DAY,
            date=today - timedelta(days=30),
        )
        self.events_url = reverse("templates:calendarevent-list")
        self.authenticate_as(self.agent)

    def test_only_upcoming_events_are_listed_by_default(self):
        """A calendar of past festivals is a history lesson, not a plan."""
        response = self.client.get(self.events_url)

        names = [row["name"] for row in response.data]
        self.assertEqual(names, ["Diwali", "Christmas"])

    def test_past_events_can_be_asked_for(self):
        response = self.client.get(self.events_url, {"include_past": "true"})

        self.assertEqual(len(response.data), 3)

    def test_events_can_be_limited_to_a_window(self):
        response = self.client.get(self.events_url, {"within_days": "30"})

        self.assertEqual([row["name"] for row in response.data], ["Diwali"])

    def test_each_event_reports_how_far_away_it_is(self):
        response = self.client.get(self.events_url)

        self.assertEqual(response.data[0]["days_away"], 10)
        self.assertFalse(response.data[0]["is_past"])

    def test_moving_dates_are_flagged_for_review(self):
        """Lunar dates are not computed, so it must be visible which are which."""
        response = self.client.get(self.events_url)
        by_name = {row["name"]: row for row in response.data}

        self.assertTrue(by_name["Diwali"]["needs_date_review"])
        self.assertFalse(by_name["Christmas"]["needs_date_review"])

    def test_an_event_reports_how_many_templates_it_has(self):
        response = self.client.get(self.events_url)
        by_name = {row["name"]: row for row in response.data}

        self.assertEqual(by_name["Diwali"]["template_count"], 1)
        self.assertEqual(by_name["Christmas"]["template_count"], 0)

    def test_the_templates_for_an_event_can_be_fetched(self):
        url = reverse("templates:calendarevent-templates-for-event", args=[self.soon.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["event"]["name"], "Diwali")
        self.assertEqual(len(response.data["templates"]), 1)
        # Nothing the calendar offers should demand a property.
        self.assertFalse(response.data["templates"][0]["requires_listing"])

    def test_inactive_events_are_hidden(self):
        self.soon.is_active = False
        self.soon.save()

        response = self.client.get(self.events_url)

        self.assertNotIn("Diwali", [row["name"] for row in response.data])

    def test_the_calendar_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.client.get(self.events_url).status_code, 401)

    def test_the_calendar_is_read_only(self):
        """Getting Eid wrong is not something to leave to a text field."""
        response = self.client.post(
            self.events_url,
            {"name": "Made up", "slug": "made-up", "category": "diwali", "date": "2027-01-01"},
            format="json",
        )

        self.assertEqual(response.status_code, 405)


class SeedCommandTests(TemplateAPITestCase):
    def test_the_seeded_calendar_is_dated_and_flagged(self):
        from io import StringIO

        from django.core.management import call_command

        call_command("seed_calendar", stdout=StringIO())

        self.assertTrue(CalendarEvent.objects.exists())
        # The moving festivals must be flagged; the fixed ones must not be.
        self.assertTrue(
            CalendarEvent.objects.filter(slug="diwali", needs_date_review=True).exists()
        )
        self.assertTrue(
            CalendarEvent.objects.filter(slug="christmas", needs_date_review=False).exists()
        )

    def test_reseeding_is_idempotent(self):
        from io import StringIO

        from django.core.management import call_command

        call_command("seed_calendar", stdout=StringIO())
        first = CalendarEvent.objects.count()
        call_command("seed_calendar", stdout=StringIO())

        self.assertEqual(CalendarEvent.objects.count(), first)

    def test_the_seeded_seasonal_templates_need_no_listing(self):
        from io import StringIO

        from django.core.management import call_command

        call_command("seed_templates", stdout=StringIO())

        seasonal = Template.objects.filter(category__in=["diwali", "eid", "christmas"])
        self.assertTrue(seasonal.exists())
        for template in seasonal:
            with self.subTest(template=template.slug):
                self.assertFalse(template.requires_listing)
                # And no element may depend on listing data.
                sources = [
                    element.content_source
                    for element in template.elements.all()
                    if element.content_source
                ]
                self.assertFalse(
                    [source for source in sources if source.startswith("listing.")],
                    f"{template.slug} references listing data but needs no listing",
                )

    def test_every_seeded_calendar_category_has_at_least_one_template(self):
        """An event with no templates is a dead end in the UI."""
        from io import StringIO

        from django.core.management import call_command

        call_command("seed_templates", stdout=StringIO())
        call_command("seed_calendar", stdout=StringIO())

        template_categories = set(
            Template.objects.filter(is_active=True).values_list("category", flat=True)
        )
        event_categories = set(
            CalendarEvent.objects.values_list("category", flat=True)
        )
        missing = sorted(event_categories - template_categories)

        self.assertEqual(
            missing,
            [],
            f"these calendar categories have no templates and would be dead "
            f"ends in the UI: {missing}",
        )
