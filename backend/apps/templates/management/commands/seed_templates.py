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

from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.templates.models import (
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
        "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.56},
        "style_properties": {"object_fit": "cover"},
        "content_source": "listing.photo",
        "z_index": 1,
    }
    element.update(overrides)
    return element


def _scrim(y=0.30, height=0.26):
    return {
        "key": "hero_scrim",
        "label": "Photo shading",
        "element_type": ElementType.COLOR_BLOCK,
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
            "geometry": {"x": 0.06, "y": y, "width": 0.09, "height": 0.055},
            "style_properties": {"object_fit": "cover", "border_radius_ratio": 0.05},
            "content_source": "agent.photo",
            "z_index": 21,
        },
        {
            "key": "agent_name",
            "label": "Agent name",
            "element_type": ElementType.TEXT,
            "geometry": {"x": 0.17, "y": y, "width": 0.4, "height": 0.03},
            "style_properties": {"font_size_ratio": 0.022, "font_weight": "700", "color": "#FFFFFF"},
            "content_source": "agent.name",
            "z_index": 21,
        },
        {
            "key": "agent_title",
            "label": "Agent title and phone",
            "element_type": ElementType.TEXT,
            "geometry": {"x": 0.17, "y": y + 0.028, "width": 0.45, "height": 0.028},
            "style_properties": {"font_size_ratio": 0.016, "color": "#CBD5E1"},
            "content_source": "agent.job_title",
            "z_index": 21,
        },
    ]


def _footer_bar(y=0.855):
    return {
        "key": "footer_bar",
        "label": "Footer band",
        "element_type": ElementType.COLOR_BLOCK,
        "geometry": {"x": 0.0, "y": y, "width": 1.0, "height": 0.145},
        "style_properties": {"background_color": "@primary_color"},
        "z_index": 19,
    }


def _price_free(y=0.44):
    """The one element an agent can genuinely move — within a bounded strip."""
    return {
        "key": "price",
        "label": "Price",
        "element_type": ElementType.TEXT,
        "geometry": {"x": 0.06, "y": y, "width": 0.6, "height": 0.09},
        "style_properties": {
            "font_size_ratio": 0.062,
            "font_weight": "700",
            "color": "#FFFFFF",
            "format": "currency",
        },
        "content_source": "listing.price",
        "z_index": 10,
    }


def _badge(text, y=0.05):
    return {
        "key": "badge",
        "label": "Status badge",
        "element_type": ElementType.BADGE,
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
        "z_index": 11,
    }


def _address_block(y=0.60):
    return [
        {
            "key": "address",
            "label": "Address",
            "element_type": ElementType.TEXT,
            "geometry": {"x": 0.06, "y": y, "width": 0.88, "height": 0.07},
            "style_properties": {
                "font_size_ratio": 0.042,
                "font_weight": "700",
                "color": "@primary_color",
                "line_height": 1.15,
            },
            "content_source": "listing.address",
            "z_index": 5,
        },
        {
            "key": "location",
            "label": "Suburb, state, postcode",
            "element_type": ElementType.TEXT,
            "geometry": {"x": 0.06, "y": y + 0.07, "width": 0.88, "height": 0.035},
            "style_properties": {"font_size_ratio": 0.024, "color": "@secondary_color"},
            "content_source": "listing.location",
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
                "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.6},
                "style_properties": {"object_fit": "cover"},
                "content_source": "agent.photo",
                "z_index": 1,
            },
            _badge("Meet your agent"),
            {
                "key": "agent_name",
                "label": "Agent name",
                "element_type": ElementType.TEXT,
                "geometry": {"x": 0.06, "y": 0.65, "width": 0.88, "height": 0.07},
                "style_properties": {
                    "font_size_ratio": 0.05,
                    "font_weight": "700",
                    "color": "#FFFFFF",
                },
                "content_source": "agent.name",
                "z_index": 5,
            },
            {
                "key": "tagline",
                "label": "Tagline",
                "element_type": ElementType.TEXT,
                "geometry": {"x": 0.06, "y": 0.735, "width": 0.88, "height": 0.09},
                "style_properties": {
                    "font_size_ratio": 0.026,
                    "color": "#CBD5E1",
                    "line_height": 1.4,
                },
                "content_source": "agent.tagline",
                "z_index": 5,
            },
            _brokerage_logo(x=0.06, y=0.87),
            _disclaimer(),
        ],
    }


def seasonal_template(*, name, slug, category, style, greeting, subtitle, description):
    """A festival card. No listing, and no element that references one.

    Every content_source here points at the agent or the brokerage, so the
    template renders correctly with ``design.listing = None`` — which is the
    whole point of the content calendar.
    """
    return {
        "name": name,
        "slug": slug,
        "category": category,
        "style": style,
        "description": description,
        "layout_definition": {
            "background_color": "@primary_color",
            "base_aspect": "1:1",
            "notes": "Seasonal card — renders without a listing.",
        },
        "elements": [
            {
                "key": "backdrop",
                "label": "Background",
                "element_type": ElementType.COLOR_BLOCK,
                "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                "style_properties": {"background_color": "@primary_color"},
                "z_index": 0,
            },
            {
                "key": "accent_bar",
                "label": "Accent bar",
                "element_type": ElementType.COLOR_BLOCK,
                "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.014},
                "style_properties": {"background_color": "@accent_color"},
                "z_index": 2,
            },
            {
                "key": "greeting",
                "label": "Greeting",
                "element_type": ElementType.TEXT,
                # Content-only: the agent may reword the greeting, but the
                # layout of a festival card is the designer's business.
                "geometry": {"x": 0.08, "y": 0.30, "width": 0.84, "height": 0.16},
                "style_properties": {
                    "font_size_ratio": 0.075,
                    "font_weight": "700",
                    "color": "#FFFFFF",
                    "text_align": "center",
                    "line_height": 1.1,
                },
                "default_content": greeting,
                "z_index": 5,
            },
            {
                "key": "subtitle",
                "label": "Message",
                "element_type": ElementType.TEXT,
                "geometry": {"x": 0.12, "y": 0.48, "width": 0.76, "height": 0.12},
                "style_properties": {
                    "font_size_ratio": 0.028,
                    "color": "#E2E8F0",
                    "text_align": "center",
                    "line_height": 1.4,
                },
                "default_content": subtitle,
                "z_index": 5,
            },
            {
                "key": "agent_photo",
                "label": "Agent photo",
                "element_type": ElementType.IMAGE,
                "geometry": {"x": 0.42, "y": 0.66, "width": 0.16, "height": 0.16},
                "style_properties": {"object_fit": "cover", "border_radius_ratio": 0.08},
                "content_source": "agent.photo",
                "z_index": 6,
            },
            {
                "key": "agent_name",
                "label": "Agent name",
                "element_type": ElementType.TEXT,
                "geometry": {"x": 0.1, "y": 0.845, "width": 0.8, "height": 0.05},
                "style_properties": {
                    "font_size_ratio": 0.03,
                    "font_weight": "700",
                    "color": "#FFFFFF",
                    "text_align": "center",
                },
                "content_source": "agent.name",
                "z_index": 6,
            },
            _brokerage_logo(x=0.39, y=0.905),
            _disclaimer(y=0.962),
        ],
    }


SEASONAL_SEED = [
    seasonal_template(
        name="Christmas — Classic",
        slug="christmas-classic",
        category=TemplateCategory.CHRISTMAS,
        style=TemplateStyle.CLASSIC,
        greeting="Merry Christmas",
        subtitle="Wishing you and your family a warm and restful season.",
        description="Seasonal greeting. No listing required.",
    ),
    seasonal_template(
        name="Diwali — Luxury",
        slug="diwali-luxury",
        category=TemplateCategory.DIWALI,
        style=TemplateStyle.LUXURY,
        greeting="Happy Diwali",
        subtitle="Wishing you light, prosperity and happiness this festival season.",
        description="Diwali greeting. No listing required.",
    ),
    seasonal_template(
        name="Eid — Minimal",
        slug="eid-minimal",
        category=TemplateCategory.EID,
        style=TemplateStyle.MINIMAL,
        greeting="Eid Mubarak",
        subtitle="Wishing you and your loved ones peace and joy.",
        description="Eid greeting. No listing required.",
    ),
    seasonal_template(
        name="Lunar New Year — Bold",
        slug="lunar-new-year-bold",
        category=TemplateCategory.LUNAR_NEW_YEAR,
        style=TemplateStyle.BOLD,
        greeting="Happy Lunar New Year",
        subtitle="Wishing you good fortune, health and happiness in the year ahead.",
        description="Lunar New Year greeting. No listing required.",
    ),
    seasonal_template(
        name="Canada Day — Bold",
        slug="canada-day-bold",
        category=TemplateCategory.CANADA_DAY,
        style=TemplateStyle.BOLD,
        greeting="Happy Canada Day",
        subtitle="Celebrating the communities we get to call home.",
        description="Canada Day greeting. No listing required.",
    ),
    seasonal_template(
        name="New Year — Editorial",
        slug="new-year-editorial",
        category=TemplateCategory.NEW_YEAR,
        style=TemplateStyle.EDITORIAL,
        greeting="Happy New Year",
        subtitle="Thank you for a wonderful year. Here's to the next one.",
        description="New Year greeting. No listing required.",
    ),
    seasonal_template(
        name="Thanksgiving — Warm",
        slug="thanksgiving-warm",
        category=TemplateCategory.THANKSGIVING,
        style=TemplateStyle.WARM,
        greeting="Happy Thanksgiving",
        subtitle="Grateful for the families we have helped find a home this year.",
        description="Thanksgiving greeting. No listing required.",
    ),
    seasonal_template(
        name="Easter — Minimal",
        slug="easter-minimal",
        category=TemplateCategory.EASTER,
        style=TemplateStyle.MINIMAL,
        greeting="Happy Easter",
        subtitle="Wishing you a restful long weekend with the people you love.",
        description="Easter greeting. No listing required.",
    ),
    # The four below exist so no seeded calendar event is a dead end — an
    # occasion that appears in the calendar with nothing to click is worse
    # than one that is not listed at all.
    seasonal_template(
        name="Hanukkah — Minimal",
        slug="hanukkah-minimal",
        category=TemplateCategory.HANUKKAH,
        style=TemplateStyle.MINIMAL,
        greeting="Happy Hanukkah",
        subtitle="Wishing you light and warmth through the festival.",
        description="Hanukkah greeting. No listing required.",
    ),
    seasonal_template(
        name="Australia Day — Minimal",
        slug="australia-day-minimal",
        category=TemplateCategory.AUSTRALIA_DAY,
        style=TemplateStyle.MINIMAL,
        greeting="26 January",
        subtitle="A day that means different things to different people. Thinking of all our neighbours.",
        description=(
            "Deliberately understated — 26 January is contested, and a "
            "celebratory card is not the right note for every audience."
        ),
    ),
    seasonal_template(
        name="Mother's Day — Warm",
        slug="mothers-day-warm",
        category=TemplateCategory.MOTHERS_DAY,
        style=TemplateStyle.WARM,
        greeting="Happy Mother's Day",
        subtitle="Thinking of all the mothers making a house a home today.",
        description="Mother's Day greeting. No listing required.",
    ),
    seasonal_template(
        name="Father's Day — Warm",
        slug="fathers-day-warm",
        category=TemplateCategory.FATHERS_DAY,
        style=TemplateStyle.WARM,
        greeting="Happy Father's Day",
        subtitle="Wishing all the dads a good day with the people they love.",
        description="Father's Day greeting. No listing required.",
    ),
]


def _dot_cluster_asset() -> ContentFile:
    """A small five-dot decorative cluster (3 over 2), rendered with Pillow.

    This is the STATIC_GRAPHIC use case in its purest form: artwork that is
    part of the template's design and is not a photo of anything, not brand
    data, not listing data — so it cannot come from content_source the way
    everything else on this page does. Generated here rather than checked in
    as a binary asset, so `seed_templates` stays the single, reproducible
    source of the whole template — re-running it regenerates the exact same
    file rather than depending on something living outside the repo.
    """
    from PIL import Image, ImageDraw

    scale = 4  # supersample, then downscale, for a clean anti-aliased edge
    dot, gap = 66 * scale, 6 * scale
    brown = (161, 90, 46, 255)  # matches accent_color below

    width = 3 * dot + 2 * gap
    height = 2 * dot + gap
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    for i in range(3):
        x = i * (dot + gap)
        draw.ellipse([x, 0, x + dot, dot], fill=brown)
    row2_offset = (width - (2 * dot + gap)) // 2
    for i in range(2):
        x = row2_offset + i * (dot + gap)
        draw.ellipse([x, dot + gap, x + dot, dot + gap + dot], fill=brown)

    image = image.resize((width // scale, height // scale), Image.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return ContentFile(buffer.getvalue(), name="dot_cluster.png")


def feature_showcase_template():
    """Authored from a client-supplied reference PNG (a furniture/interior
    brand promo card), converted into independent elements rather than kept
    as one flat image — see apps/templates/models.py for why that split
    matters. Demonstrates every element type this build added:

      STATIC_GRAPHIC  the dot cluster — decorative, never listing/brand data
      geometry.rotation  available to the FREE offer text below (not preset;
                          an agent rotates it if they want to, same as any
                          other FREE element now can)
      a FREE text block  the offer callout, duplicable like `price` is on
                          the listing templates

    The source image roughly rounds the hero photos into an asymmetric
    "D" shape (square corners on one side, fully round on the other).
    html_builder's border_radius_ratio is uniform on all four corners, so
    this uses a generously large radius instead — a rounded rectangle
    rather than the exact silhouette. Close in spirit, not a pixel clone;
    extending CSS support for four independent corners wasn't worth it for
    one template.
    """
    accent = "#A15A2E"
    ink = "#241811"
    body_ink = "#5C4A3D"
    cream = "#EAE3D6"

    return {
        "name": "Feature Showcase — Warm Editorial",
        "slug": "feature-showcase-warm-editorial",
        "category": TemplateCategory.MARKET_UPDATE,
        "style": TemplateStyle.WARM,
        "description": (
            "Photo-led brand/feature showcase with a seasonal offer callout. "
            "No listing required — works from a listing photo if one is set, "
            "otherwise the agent uploads their own."
        ),
        "layout_definition": {"background_color": cream},
        "elements": [
            {
                "key": "top_bar",
                "label": "Accent bar",
                "element_type": ElementType.COLOR_BLOCK,
                "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.012},
                "style_properties": {"background_color": accent},
                "z_index": 1,
            },
            {
                "key": "headline",
                "label": "Headline",
                "element_type": ElementType.TEXT,
                "geometry": {"x": 0.08, "y": 0.035, "width": 0.62, "height": 0.16},
                "style_properties": {
                    "font_size_ratio": 0.052,
                    "font_weight": "800",
                    "color": ink,
                    "line_height": 1.05,
                },
                "default_content": "Exquisite solutions for your space.",
                "z_index": 5,
            },
            {
                "key": "subheadline",
                "label": "Subheading",
                "element_type": ElementType.TEXT,
                "geometry": {"x": 0.08, "y": 0.205, "width": 0.55, "height": 0.05},
                "style_properties": {
                    "font_size_ratio": 0.022,
                    "color": ink,
                    "text_transform": "uppercase",
                    "letter_spacing_em": 0.02,
                    "line_height": 1.35,
                },
                "default_content": "Exquisite solution\nSuperior craft",
                "z_index": 5,
            },
            {
                "key": "primary_photo",
                "label": "Primary photo",
                "element_type": ElementType.IMAGE,
                "geometry": {"x": 0.0, "y": 0.275, "width": 0.62, "height": 0.195},
                "style_properties": {"object_fit": "cover", "border_radius_ratio": 0.5},
                # Auto-fills from the listing when there is one; the agent can
                # still upload their own via image-replace when there isn't.
                "content_source": "listing.photo",
                "z_index": 2,
            },
            {
                "key": "accent_ring",
                "label": "Circle accent",
                "element_type": ElementType.COLOR_BLOCK,
                "geometry": {"x": 0.66, "y": 0.275, "width": 0.30, "height": 0.135},
                "style_properties": {"background_color": accent, "border_radius_ratio": 0.5},
                "z_index": 2,
            },
            {
                "key": "accent_photo",
                "label": "Feature photo",
                "element_type": ElementType.IMAGE,
                "geometry": {"x": 0.685, "y": 0.29, "width": 0.25, "height": 0.105},
                "style_properties": {"object_fit": "cover", "border_radius_ratio": 0.5},
                "z_index": 3,
            },
            {
                "key": "dot_cluster",
                "label": "Decorative dots",
                "element_type": ElementType.STATIC_GRAPHIC,
                "geometry": {"x": 0.08, "y": 0.485, "width": 0.14, "height": 0.045},
                "style_properties": {"object_fit": "contain"},
                "static_asset": _dot_cluster_asset(),
                "z_index": 2,
            },
            {
                "key": "secondary_photo",
                "label": "Secondary photo",
                "element_type": ElementType.IMAGE,
                "geometry": {"x": 0.44, "y": 0.5, "width": 0.56, "height": 0.175},
                "style_properties": {"object_fit": "cover", "border_radius_ratio": 0.5},
                "z_index": 2,
            },
            {
                "key": "craft_heading",
                "label": "Left column heading",
                "element_type": ElementType.TEXT,
                "geometry": {"x": 0.08, "y": 0.71, "width": 0.32, "height": 0.05},
                "style_properties": {"font_size_ratio": 0.024, "font_weight": "800", "color": ink},
                "default_content": "Superior craft",
                "z_index": 5,
            },
            {
                "key": "craft_body",
                "label": "Left column text",
                "element_type": ElementType.TEXT,
                "geometry": {"x": 0.08, "y": 0.758, "width": 0.34, "height": 0.11},
                "style_properties": {"font_size_ratio": 0.016, "color": body_ink, "line_height": 1.4},
                "default_content": (
                    "Thoughtfully made furniture, built to last and designed "
                    "around how you actually live."
                ),
                "z_index": 5,
            },
            {
                "key": "offer_heading",
                "label": "Right column heading",
                "element_type": ElementType.TEXT,
                "geometry": {"x": 0.5, "y": 0.71, "width": 0.42, "height": 0.06},
                "style_properties": {"font_size_ratio": 0.024, "font_weight": "800", "color": ink},
                "default_content": "Striking offers this season!",
                "z_index": 5,
            },
            {
                # The FREE demo element for this template — matches the role
                # `price` plays on the listing templates: move, resize,
                # restyle, duplicate and (now) rotate, all within bounds.
                "key": "offer_body",
                "label": "Right column text",
                "element_type": ElementType.TEXT,
                "geometry": {"x": 0.5, "y": 0.775, "width": 0.42, "height": 0.09},
                "style_properties": {"font_size_ratio": 0.016, "color": body_ink, "line_height": 1.4},
                "default_content": "Save up to 45% off selected items — ends soon.",
                "z_index": 5,
            },
            {
                "key": "cta_button",
                "label": "Call-to-action button",
                "element_type": ElementType.BADGE,
                "geometry": {"x": 0.08, "y": 0.905, "width": 0.5, "height": 0.055},
                "style_properties": {
                    "background_color": accent,
                    "color": "#FFFFFF",
                    "font_weight": "700",
                    "font_size_ratio": 0.02,
                    "text_align": "center",
                    "vertical_align": "center",
                },
                "default_content": "Learn more",
                "z_index": 6,
            },
        ],
    }


SEED = SEASONAL_SEED + [
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
    feature_showcase_template(),
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
