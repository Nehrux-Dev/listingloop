"""Shared helpers for the template-system tests."""

from __future__ import annotations

from django.urls import reverse

from apps.listings.tests.base import ListingAPITestCase
from apps.templates.models import (
    Design,
    ElementPermission,
    ElementType,
    Template,
    TemplateCategory,
    TemplateElement,
    TemplateStyle,
)

__all__ = ["TemplateAPITestCase"]


class TemplateAPITestCase(ListingAPITestCase):
    """Adds template/design URLs and a fixture template covering all four
    permission levels, so every test can exercise the full contract."""

    templates_url = reverse("templates:template-list")
    template_facets_url = reverse("templates:template-facets")
    designs_url = reverse("templates:design-list")
    exports_url = reverse("templates:designexport-list")
    dimensions_url = reverse("templates:render-dimensions")

    @staticmethod
    def template_detail_url(template) -> str:
        return reverse("templates:template-detail", args=[template.pk])

    @staticmethod
    def design_detail_url(design) -> str:
        return reverse("templates:design-detail", args=[design.pk])

    @staticmethod
    def design_action_url(design, action: str) -> str:
        return reverse(f"templates:design-{action}", args=[design.pk])

    @staticmethod
    def make_template(**overrides) -> Template:
        """A template with one element per permission level.

        locked        `disclaimer`
        content_only  `headline`, `hero_photo`
        styled        `badge`
        free          `price`
        """
        defaults = {
            "name": "Test Template",
            "slug": "test-template",
            "category": TemplateCategory.NEW_LISTING,
            "style": TemplateStyle.BOLD,
            "layout_definition": {"background_color": "#FFFFFF"},
        }
        defaults.update(overrides)
        template = Template.objects.create(**defaults)

        TemplateElement.objects.create(
            template=template,
            key="disclaimer",
            label="Compliance disclaimer",
            element_type=ElementType.TEXT,
            permission=ElementPermission.LOCKED,
            geometry={"x": 0.05, "y": 0.95, "width": 0.9, "height": 0.04},
            style_properties={"font_size_ratio": 0.013, "color": "#94A3B8"},
            content_source="brokerage.required_disclaimer",
            z_index=20,
        )
        TemplateElement.objects.create(
            template=template,
            key="headline",
            label="Headline",
            element_type=ElementType.TEXT,
            permission=ElementPermission.CONTENT_ONLY,
            geometry={"x": 0.06, "y": 0.6, "width": 0.88, "height": 0.08},
            style_properties={"font_size_ratio": 0.04, "color": "#0F172A"},
            content_source="listing.address",
            constraints={"max_length": 60},
            z_index=5,
        )
        TemplateElement.objects.create(
            template=template,
            key="hero_photo",
            label="Main photo",
            element_type=ElementType.IMAGE,
            permission=ElementPermission.CONTENT_ONLY,
            geometry={"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.55},
            content_source="listing.photo",
            constraints={"required": True},
            z_index=1,
        )
        TemplateElement.objects.create(
            template=template,
            key="badge",
            label="Status badge",
            element_type=ElementType.BADGE,
            permission=ElementPermission.STYLED,
            geometry={"x": 0.06, "y": 0.05, "width": 0.3, "height": 0.045},
            style_properties={"background_color": "#2563EB", "color": "#FFFFFF"},
            default_content="Just listed",
            constraints={
                "allowed_colors": ["#2563EB", "#0F172A", "#C2874A"],
                "min_font_size_ratio": 0.014,
                "max_font_size_ratio": 0.026,
                "max_length": 24,
            },
            z_index=11,
        )
        TemplateElement.objects.create(
            template=template,
            key="price",
            label="Price",
            element_type=ElementType.TEXT,
            permission=ElementPermission.FREE,
            geometry={"x": 0.06, "y": 0.42, "width": 0.5, "height": 0.09},
            style_properties={"font_size_ratio": 0.06, "color": "#FFFFFF", "format": "currency"},
            content_source="listing.price",
            constraints={
                "bounds": {"x": 0.04, "y": 0.30, "width": 0.92, "height": 0.26},
                "min_font_size_ratio": 0.03,
                "max_font_size_ratio": 0.09,
                "allowed_colors": ["#FFFFFF", "#0F172A"],
            },
            z_index=10,
        )
        return template

    def make_design(self, template, agent_profile, listing=None, **overrides) -> Design:
        data = {
            "name": "Test Design",
            "template": template,
            "agent": agent_profile,
            "listing": listing,
            "overrides": {},
        }
        data.update(overrides)
        return Design.objects.create(**data)

    def make_verified_listing(self, agent_profile, user, **overrides):
        listing = self.make_listing(agent_profile, **overrides)
        listing.mark_verified(user)
        listing.refresh_from_db()
        return listing
