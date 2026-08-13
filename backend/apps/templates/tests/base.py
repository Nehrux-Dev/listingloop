"""Shared helpers for the template-system tests."""

from __future__ import annotations

from django.urls import reverse

from apps.listings.tests.base import ListingAPITestCase
from apps.templates.document import elements_from_template
from apps.templates.models import (
    Design,
    ElementType,
    Template,
    TemplateCategory,
    TemplateElement,
    TemplateStyle,
)

__all__ = ["TemplateAPITestCase"]


class TemplateAPITestCase(ListingAPITestCase):
    """Adds template/design URLs and a fixture template.

    The fixture used to be built around the four permission tiers — one
    element per tier, so every test could exercise the contract. There are no
    tiers now, so it is built around the things that actually differ between
    elements: what type they are, whether they carry a data binding, and
    whether their content is literal.
    """

    templates_url = reverse("templates:template-list")
    template_facets_url = reverse("templates:template-facets")
    designs_url = reverse("templates:design-list")
    exports_url = reverse("templates:designexport-list")
    dimensions_url = reverse("templates:render-dimensions")
    element_kinds_url = reverse("templates:design-element-kinds")

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
    def design_element_url(design, element_id: str, action: str) -> str:
        """URL for a per-element action — currently only ``reset-element``."""
        return reverse(
            f"templates:design-{action}",
            kwargs={"pk": design.pk, "element_id": element_id},
        )

    @staticmethod
    def make_template(**overrides) -> Template:
        """A template covering every element type and both content styles.

        ``disclaimer``  bound text, brokerage-sourced (drives readiness)
        ``headline``    bound text, listing-sourced
        ``hero_photo``  bound image
        ``badge``       literal text on a filled box (becomes a `button`)
        ``price``       bound text with a currency format
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
            geometry={"x": 0.06, "y": 0.6, "width": 0.88, "height": 0.08},
            style_properties={"font_size_ratio": 0.04, "color": "#0F172A"},
            content_source="listing.full_address",
            z_index=5,
        )
        TemplateElement.objects.create(
            template=template,
            key="hero_photo",
            label="Main photo",
            element_type=ElementType.IMAGE,
            geometry={"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.55},
            content_source="listing.photo",
            z_index=1,
        )
        TemplateElement.objects.create(
            template=template,
            key="badge",
            label="Status badge",
            element_type=ElementType.BADGE,
            geometry={"x": 0.06, "y": 0.05, "width": 0.3, "height": 0.045},
            style_properties={"background_color": "#2563EB", "color": "#FFFFFF"},
            default_content="Just listed",
            z_index=11,
        )
        TemplateElement.objects.create(
            template=template,
            key="price",
            label="Price",
            element_type=ElementType.TEXT,
            geometry={"x": 0.06, "y": 0.42, "width": 0.5, "height": 0.09},
            style_properties={"font_size_ratio": 0.06, "color": "#FFFFFF", "format": "currency"},
            content_source="listing.price",
            z_index=10,
        )
        return template

    def make_design(self, template, agent_profile, listing=None, **overrides) -> Design:
        """A design with its document already copied in.

        The copy normally happens in ``DesignSerializer.create``; doing it here
        too means a test that builds a design directly through the ORM gets the
        same starting state an agent would, rather than an empty canvas that
        only fills in on first render.
        """
        data = {
            "name": "Test Design",
            "template": template,
            "agent": agent_profile,
            "listing": listing,
        }
        data.update(overrides)
        data.setdefault("elements", elements_from_template(template))
        return Design.objects.create(**data)

    @staticmethod
    def element_of(design, original_key: str) -> dict:
        """The design element copied from a given template element key.

        Tests know template keys (``price``, ``badge``); a design's elements
        carry generated ids. This is the bridge, and using it rather than an
        index keeps a test readable when the element order changes.
        """
        for element in design.elements:
            if element.get("original_element_id") == original_key:
                return element
        raise AssertionError(
            f"No element copied from {original_key!r}; have "
            f"{[e.get('original_element_id') for e in design.elements]}"
        )

    def make_verified_listing(self, agent_profile, user, **overrides):
        listing = self.make_listing(agent_profile, **overrides)
        listing.mark_verified(user)
        listing.refresh_from_db()
        return listing
