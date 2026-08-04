"""Seed the template library.

Templates are product content, so this is how they get authored until there is
an internal tool for it. Idempotent: safe to re-run, and re-running updates
existing templates in place rather than duplicating them.

Each template demonstrates the four permission levels on purpose:

  locked        brokerage logo, compliance disclaimer — never editable
  content_only  the headline text, the hero photo — swap, do not move
  styled        accent bar, badge — recoloured within an allowlist
  free          the price block — moved and restyled within bounds
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.templates.models import (
    ElementPermission,
    ElementType,
    Template,
    TemplateCategory,
    TemplateElement,
    TemplateStyle,
)

# Colour palettes an agent may pick from on `styled` elements. Restricting to
# an allowlist is what stops a brand-consistent template becoming a free-for-all.
BRAND_PALETTE = ["@primary_color", "@secondary_color", "@accent_color"]
NEUTRALS = ["#FFFFFF", "#0F172A", "#F8FAFC", "#111827"]


def _listing_hero(**overrides):
    element = {
        "key": "hero_photo",
        "label": "Main photo",
        "element_type": ElementType.IMAGE,
        "permission": ElementPermission.CONTENT_ONLY,
        "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.56},
        "style_properties": {"object_fit": "cover"},
        "content_source": "listing.photo",
        "constraints": {"required": True},
        "z_index": 1,
    }
    element.update(overrides)
    return element


def _scrim(y=0.30, height=0.26):
    return {
        "key": "hero_scrim",
        "label": "Photo shading",
        "element_type": ElementType.COLOR_BLOCK,
        "permission": ElementPermission.LOCKED,
        "geometry": {"x": 0.0, "y": y, "width": 1.0, "height": height},
        "style_properties": {
            "background_gradient": "linear-gradient(to bottom, rgba(15,23,42,0), rgba(15,23,42,0.85))"
        },
        "z_index": 2,
    }


def _disclaimer(y=0.955):
    return {
        "key": "disclaimer",
        "label": "Compliance disclaimer",
        "element_type": ElementType.TEXT,
        # Locked: regulatory text is not the agent's to reword.
        "permission": ElementPermission.LOCKED,
        "geometry": {"x": 0.05, "y": y, "width": 0.9, "height": 0.04},
        "style_properties": {
            "font_size_ratio": 0.013,
            "color": "#94A3B8",
            "line_height": 1.3,
        },
        "content_source": "brokerage.required_disclaimer",
        "z_index": 20,
    }


def _brokerage_logo(x=0.72, y=0.885):
    return {
        "key": "brokerage_logo",
        "label": "Brokerage logo",
        # Locked: brand assets are the brokerage's, not the agent's.
        "permission": ElementPermission.LOCKED,
        "element_type": ElementType.LOGO,
        "geometry": {"x": x, "y": y, "width": 0.22, "height": 0.05},
        "style_properties": {"object_fit": "contain"},
        "content_source": "brokerage.logo",
        "z_index": 21,
    }


def _agent_block(y=0.87):
    return [
        {
            "key": "agent_photo",
            "label": "Agent photo",
            "element_type": ElementType.IMAGE,
            "permission": ElementPermission.CONTENT_ONLY,
            "geometry": {"x": 0.06, "y": y, "width": 0.09, "height": 0.055},
            "style_properties": {"object_fit": "cover", "border_radius_ratio": 0.05},
            "content_source": "agent.photo",
            "z_index": 21,
        },
        {
            "key": "agent_name",
            "label": "Agent name",
            "element_type": ElementType.TEXT,
            "permission": ElementPermission.CONTENT_ONLY,
            "geometry": {"x": 0.17, "y": y, "width": 0.4, "height": 0.03},
            "style_properties": {"font_size_ratio": 0.022, "font_weight": "700", "color": "#FFFFFF"},
            "content_source": "agent.name",
            "constraints": {"max_length": 60},
            "z_index": 21,
        },
        {
            "key": "agent_title",
            "label": "Agent title and phone",
            "element_type": ElementType.TEXT,
            "permission": ElementPermission.CONTENT_ONLY,
            "geometry": {"x": 0.17, "y": y + 0.028, "width": 0.45, "height": 0.028},
            "style_properties": {"font_size_ratio": 0.016, "color": "#CBD5E1"},
            "content_source": "agent.job_title",
            "constraints": {"max_length": 80},
            "z_index": 21,
        },
    ]


def _footer_bar(y=0.855):
    return {
        "key": "footer_bar",
        "label": "Footer band",
        "element_type": ElementType.COLOR_BLOCK,
        "permission": ElementPermission.STYLED,
        "geometry": {"x": 0.0, "y": y, "width": 1.0, "height": 0.145},
        "style_properties": {"background_color": "@primary_color"},
        "constraints": {"allowed_colors": BRAND_PALETTE + ["#0F172A", "#111827"]},
        "z_index": 19,
    }


def _price_free(y=0.44):
    """The one element an agent can genuinely move — within a bounded strip."""
    return {
        "key": "price",
        "label": "Price",
        "element_type": ElementType.TEXT,
        "permission": ElementPermission.FREE,
        "geometry": {"x": 0.06, "y": y, "width": 0.6, "height": 0.09},
        "style_properties": {
            "font_size_ratio": 0.062,
            "font_weight": "700",
            "color": "#FFFFFF",
            "format": "currency",
        },
        "content_source": "listing.price",
        "constraints": {
            # Free, but not anywhere: it must stay over the photo, where the
            # scrim guarantees it is legible.
            "bounds": {"x": 0.04, "y": 0.30, "width": 0.92, "height": 0.26},
            "min_font_size_ratio": 0.03,
            "max_font_size_ratio": 0.09,
            "allowed_colors": NEUTRALS + BRAND_PALETTE,
            "max_length": 40,
        },
        "z_index": 10,
    }


def _badge(text, y=0.05):
    return {
        "key": "badge",
        "label": "Status badge",
        "element_type": ElementType.BADGE,
        "permission": ElementPermission.STYLED,
        "geometry": {"x": 0.06, "y": y, "width": 0.34, "height": 0.045},
        "style_properties": {
            "background_color": "@accent_color",
            "color": "#FFFFFF",
            "font_size_ratio": 0.019,
            "font_weight": "700",
            "letter_spacing_em": 0.16,
            "text_transform": "uppercase",
            "text_align": "center",
            "vertical_align": "center",
            "border_radius_ratio": 0.006,
            "padding_ratio": 0.012,
        },
        "default_content": text,
        "constraints": {
            "allowed_colors": BRAND_PALETTE + NEUTRALS,
            "max_length": 24,
            "min_font_size_ratio": 0.014,
            "max_font_size_ratio": 0.026,
        },
        "z_index": 11,
    }


def _address_block(y=0.60):
    return [
        {
            "key": "address",
            "label": "Address",
            "element_type": ElementType.TEXT,
            "permission": ElementPermission.CONTENT_ONLY,
            "geometry": {"x": 0.06, "y": y, "width": 0.88, "height": 0.07},
            "style_properties": {
                "font_size_ratio": 0.042,
                "font_weight": "700",
                "color": "@primary_color",
                "line_height": 1.15,
            },
            "content_source": "listing.address",
            "constraints": {"max_length": 120, "required": True},
            "z_index": 5,
        },
        {
            "key": "location",
            "label": "Suburb, state, postcode",
            "element_type": ElementType.TEXT,
            "permission": ElementPermission.CONTENT_ONLY,
            "geometry": {"x": 0.06, "y": y + 0.07, "width": 0.88, "height": 0.035},
            "style_properties": {"font_size_ratio": 0.024, "color": "@secondary_color"},
            "content_source": "listing.location",
            "constraints": {"max_length": 120},
            "z_index": 5,
        },
    ]


def _stat_caption(key, x, y, text):
    """One caption per stat, positioned under its own number.

    A single caption string with padding spaces looked fine at one canvas size
    and fell apart at the others — captions have to be positioned, not spaced.
    """
    return {
        "key": key,
        "label": f"{text} label",
        "element_type": ElementType.TEXT,
        "permission": ElementPermission.LOCKED,
        "geometry": {"x": x, "y": y, "width": 0.22, "height": 0.028},
        "style_properties": {
            "font_size_ratio": 0.015,
            "color": "@secondary_color",
            "letter_spacing_em": 0.12,
            "text_transform": "uppercase",
        },
        "default_content": text,
        "z_index": 6,
    }


def _stats(y=0.73):
    return [
        {
            "key": "beds",
            "label": "Bedrooms",
            "element_type": ElementType.TEXT,
            "permission": ElementPermission.CONTENT_ONLY,
            "geometry": {"x": 0.06, "y": y, "width": 0.2, "height": 0.05},
            "style_properties": {
                "font_size_ratio": 0.034,
                "font_weight": "700",
                "color": "@primary_color",
            },
            "content_source": "listing.bedrooms",
            "z_index": 6,
        },
        {
            "key": "baths",
            "label": "Bathrooms",
            "element_type": ElementType.TEXT,
            "permission": ElementPermission.CONTENT_ONLY,
            "geometry": {"x": 0.30, "y": y, "width": 0.2, "height": 0.05},
            "style_properties": {
                "font_size_ratio": 0.034,
                "font_weight": "700",
                "color": "@primary_color",
            },
            "content_source": "listing.bathrooms",
            "z_index": 6,
        },
        {
            "key": "area",
            "label": "Square footage",
            "element_type": ElementType.TEXT,
            "permission": ElementPermission.CONTENT_ONLY,
            "geometry": {"x": 0.54, "y": y, "width": 0.4, "height": 0.05},
            "style_properties": {
                "font_size_ratio": 0.034,
                "font_weight": "700",
                "color": "@primary_color",
                "format": "number",
            },
            "content_source": "listing.square_footage",
            "z_index": 6,
        },
        _stat_caption("beds_label", 0.06, y + 0.048, "Beds"),
        _stat_caption("baths_label", 0.30, y + 0.048, "Baths"),
        _stat_caption("area_label", 0.54, y + 0.048, "Sq ft"),
    ]


def listing_template(*, name, slug, category, style, badge_text, description):
    """A listing-led layout, shared by the property-centric categories."""
    return {
        "name": name,
        "slug": slug,
        "category": category,
        "style": style,
        "description": description,
        "layout_definition": {
            "background_color": "#FFFFFF",
            "base_aspect": "4:5",
            "notes": "Geometry is fractional; renders at all social dimensions.",
        },
        "elements": [
            # Sits behind the photo so a listing without one still renders as a
            # deliberate design rather than a white gap.
            {
                "key": "hero_backdrop",
                "label": "Photo backdrop",
                "element_type": ElementType.COLOR_BLOCK,
                "permission": ElementPermission.LOCKED,
                "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.56},
                "style_properties": {"background_color": "@primary_color"},
                "z_index": 0,
            },
            _listing_hero(),
            _scrim(),
            _badge(badge_text),
            _price_free(),
            *_address_block(),
            *_stats(),
            _footer_bar(),
            *_agent_block(),
            _brokerage_logo(),
            _disclaimer(),
        ],
    }


def agent_template():
    return {
        "name": "Agent Introduction — Editorial",
        "slug": "agent-introduction-editorial",
        "category": TemplateCategory.AGENT_INTRODUCTION,
        "style": TemplateStyle.EDITORIAL,
        "description": "Portrait-led introduction. No listing required.",
        "layout_definition": {"background_color": "@primary_color", "base_aspect": "4:5"},
        "elements": [
            {
                "key": "agent_photo",
                "label": "Agent photo",
                "element_type": ElementType.IMAGE,
                "permission": ElementPermission.CONTENT_ONLY,
                "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.6},
                "style_properties": {"object_fit": "cover"},
                "content_source": "agent.photo",
                "constraints": {"required": True},
                "z_index": 1,
            },
            _badge("Meet your agent"),
            {
                "key": "agent_name",
                "label": "Agent name",
                "element_type": ElementType.TEXT,
                "permission": ElementPermission.CONTENT_ONLY,
                "geometry": {"x": 0.06, "y": 0.65, "width": 0.88, "height": 0.07},
                "style_properties": {
                    "font_size_ratio": 0.05,
                    "font_weight": "700",
                    "color": "#FFFFFF",
                },
                "content_source": "agent.name",
                "constraints": {"max_length": 60, "required": True},
                "z_index": 5,
            },
            {
                "key": "tagline",
                "label": "Tagline",
                "element_type": ElementType.TEXT,
                "permission": ElementPermission.STYLED,
                "geometry": {"x": 0.06, "y": 0.735, "width": 0.88, "height": 0.09},
                "style_properties": {
                    "font_size_ratio": 0.026,
                    "color": "#CBD5E1",
                    "line_height": 1.4,
                },
                "content_source": "agent.tagline",
                "constraints": {
                    "max_length": 160,
                    "allowed_colors": ["#CBD5E1", "#FFFFFF", "@accent_color"],
                    "min_font_size_ratio": 0.018,
                    "max_font_size_ratio": 0.034,
                },
                "z_index": 5,
            },
            _brokerage_logo(x=0.06, y=0.87),
            _disclaimer(),
        ],
    }


SEED = [
    listing_template(
        name="New Listing — Bold",
        slug="new-listing-bold",
        category=TemplateCategory.NEW_LISTING,
        style=TemplateStyle.BOLD,
        badge_text="Just listed",
        description="High-contrast listing announcement with a large price block.",
    ),
    listing_template(
        name="New Listing — Luxury",
        slug="new-listing-luxury",
        category=TemplateCategory.NEW_LISTING,
        style=TemplateStyle.LUXURY,
        badge_text="New to market",
        description="Restrained type and generous spacing for premium stock.",
    ),
    listing_template(
        name="Coming Soon — Minimal",
        slug="coming-soon-minimal",
        category=TemplateCategory.COMING_SOON,
        style=TemplateStyle.MINIMAL,
        badge_text="Coming soon",
        description="Teaser layout for pre-market listings.",
    ),
    listing_template(
        name="Open House — Warm",
        slug="open-house-warm",
        category=TemplateCategory.OPEN_HOUSE,
        style=TemplateStyle.WARM,
        badge_text="Open house",
        description="Inspection announcement with room for time and date.",
    ),
    listing_template(
        name="Just Sold — Classic",
        slug="just-sold-classic",
        category=TemplateCategory.JUST_SOLD,
        style=TemplateStyle.CLASSIC,
        badge_text="Sold",
        description="Result announcement.",
    ),
    listing_template(
        name="Price Reduced — Bold",
        slug="price-reduced-bold",
        category=TemplateCategory.PRICE_REDUCED,
        style=TemplateStyle.BOLD,
        badge_text="Price reduced",
        description="Draws the eye to the new price.",
    ),
    listing_template(
        name="Leased — Minimal",
        slug="leased-minimal",
        category=TemplateCategory.LEASED,
        style=TemplateStyle.MINIMAL,
        badge_text="Leased",
        description="Rental result announcement.",
    ),
    agent_template(),
]


class Command(BaseCommand):
    help = "Create or update the seed template library."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        for spec in SEED:
            elements = spec.pop("elements")
            template, created = Template.objects.update_or_create(
                slug=spec["slug"], defaults=spec
            )

            # Replace elements wholesale: they are template definition, not
            # user data, and partial updates would leave orphans behind.
            template.elements.all().delete()
            for element in elements:
                TemplateElement.objects.create(template=template, **element)

            verb = "created" if created else "updated"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{verb}: {template.name} ({len(elements)} elements)"
                )
            )
            spec["elements"] = elements  # keep SEED reusable within a process

        self.stdout.write(f"\n{Template.objects.count()} templates in the library.")
