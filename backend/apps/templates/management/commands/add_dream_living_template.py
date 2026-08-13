"""Create the "Your Dream Living Space" flyer template, and nothing else.

WHY THIS IS ITS OWN COMMAND RATHER THAN A SEED_TEMPLATES ENTRY
-----------------------------------------------------------------------------
``seed_templates`` rebuilds the whole library. Running it to add one template
also silently recreates every template that has been deliberately deleted —
which has happened here before, and was not welcome. So a new template gets a
narrowly scoped command that touches exactly one slug and leaves the rest of
the library alone.

Geometry comes from a layer-by-layer extraction of the supplied flyer artwork,
measured against its own 1414x2000 canvas and stored normalised (x/1414,
y/2000). It is a reconstruction of that composition, not a design inspired by
it: every text string is the artwork's own wording, and every photo region
keeps its measured box.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.templates.models import (
    ElementType,
    Template,
    TemplateCategory,
    TemplateElement,
    TemplateStyle,
)

SLUG = "your-dream-living-space"

INK = "#1A1A1A"
CHARCOAL = "#3B3A38"
CREAM = "#FCF9F0"
WHITE = "#FFFFFF"

#: The artwork's own canvas. Every geometry below is a fraction of these.
SRC_W = 1414
SRC_H = 2000


def box(x, y, w, h):
    """Pixel box on the source artwork -> normalised geometry."""
    return {
        "x": round(x / SRC_W, 4),
        "y": round(y / SRC_H, 4),
        "width": round(w / SRC_W, 4),
        "height": round(h / SRC_H, 4),
        "rotation": 0.0,
    }


def ratio(px):
    """Font size in source pixels -> font_size_ratio.

    Scaled against the canvas's *smaller* side, which is what
    ``type_scale_reference`` uses, so type stays inside its box at every
    output format rather than only at this one.
    """
    return round(px / min(SRC_W, SRC_H), 4)


ELEMENTS = [
    # -- backdrop panels ----------------------------------------------------
    {
        "key": "hero_photo",
        "label": "Hero property photo",
        "element_type": ElementType.IMAGE,
        "geometry": box(0, 0, 1004, 670),
        "style_properties": {"object_fit": "cover", "object_position": "center center"},
        "content_source": "listing.photos[0]",
        "z_index": 1,
    },
    {
        "key": "location_panel",
        "label": "Location panel",
        "element_type": ElementType.COLOR_BLOCK,
        "geometry": box(1004, 560, 354, 270),
        "style_properties": {"background_color": CHARCOAL},
        "z_index": 2,
    },
    {
        "key": "summary_panel",
        "label": "Summary panel",
        "element_type": ElementType.COLOR_BLOCK,
        "geometry": box(0, 670, 1004, 160),
        "style_properties": {"background_color": CHARCOAL},
        "z_index": 2,
    },
    {
        "key": "footer_bar",
        "label": "Footer bar",
        "element_type": ElementType.COLOR_BLOCK,
        "geometry": box(0, 1950, 1414, 50),
        "style_properties": {"background_color": CHARCOAL},
        "z_index": 2,
    },
    # -- masthead -----------------------------------------------------------
    {
        "key": "brand_name",
        "label": "Brand name",
        "element_type": ElementType.TEXT,
        # Wider and two lines tall than the artwork's "BORCELLE" strictly
        # needs: this binds to the real brokerage name, and a longer one wraps.
        # At the artwork's own box it clipped mid-word.
        "geometry": box(71, 80, 430, 90),
        "style_properties": {
            "font_size_ratio": ratio(28),
            "font_weight": "400",
            "color": INK,
            "text_transform": "uppercase",
            "letter_spacing_em": 0.04,
        },
        "content_source": "brokerage.name",
        "default_content": "BORCELLE",
        "z_index": 10,
    },
    {
        "key": "headline",
        "label": "Headline",
        "element_type": ElementType.TEXT,
        "geometry": box(566, 76, 806, 210),
        "style_properties": {
            "font_size_ratio": ratio(105),
            "font_weight": "400",
            "color": INK,
            "text_transform": "uppercase",
            "text_align": "right",
            "line_height": 1.0,
        },
        "default_content": "Your dream\nliving space",
        "z_index": 10,
    },
    # -- summary + location -------------------------------------------------
    {
        "key": "summary_text",
        "label": "Property summary",
        "element_type": ElementType.TEXT,
        "geometry": box(71, 700, 891, 90),
        "style_properties": {
            "font_size_ratio": ratio(27),
            "font_weight": "400",
            "color": WHITE,
            "line_height": 1.45,
        },
        "content_source": "listing.description",
        "default_content": (
            "Experience upscale living in this stunning modern house, featuring "
            "open spaces, sleek design, and top-notch amenities"
        ),
        "z_index": 10,
    },
    {
        "key": "location_label",
        "label": "Location label",
        "element_type": ElementType.TEXT,
        "geometry": box(1075, 630, 269, 40),
        "style_properties": {
            "font_size_ratio": ratio(28),
            "font_weight": "700",
            "color": WHITE,
            "text_transform": "uppercase",
        },
        "default_content": "Location",
        "z_index": 10,
    },
    {
        "key": "location_value",
        "label": "Property address",
        "element_type": ElementType.TEXT,
        "geometry": box(1075, 706, 283, 80),
        "style_properties": {
            "font_size_ratio": ratio(30),
            "font_weight": "400",
            "color": WHITE,
            "text_transform": "uppercase",
            "line_height": 1.25,
        },
        "content_source": "listing.full_address",
        "default_content": "123 Anywhere\nSt., Any City",
        "z_index": 10,
    },
    # -- interior photo grid ------------------------------------------------
    {
        "key": "interior_photo_1",
        "label": "Interior photo 1",
        "element_type": ElementType.IMAGE,
        "geometry": box(0, 910, 471, 380),
        "style_properties": {"object_fit": "cover", "object_position": "center center"},
        "content_source": "listing.photos[1]",
        "z_index": 3,
    },
    {
        "key": "interior_photo_2",
        "label": "Interior photo 2",
        "element_type": ElementType.IMAGE,
        "geometry": box(481, 910, 474, 380),
        "style_properties": {"object_fit": "cover", "object_position": "center center"},
        "content_source": "listing.photos[2]",
        "z_index": 3,
    },
    {
        "key": "interior_photo_3",
        "label": "Interior photo 3",
        "element_type": ElementType.IMAGE,
        "geometry": box(0, 1300, 471, 390),
        "style_properties": {"object_fit": "cover", "object_position": "center center"},
        "content_source": "listing.photos[3]",
        "z_index": 3,
    },
    {
        "key": "interior_photo_4",
        "label": "Interior photo 4",
        "element_type": ElementType.IMAGE,
        "geometry": box(481, 1300, 474, 390),
        "style_properties": {"object_fit": "cover", "object_position": "center center"},
        "content_source": "listing.photos[4]",
        "z_index": 3,
    },
    # -- property features --------------------------------------------------
    {
        "key": "features_heading",
        "label": "Features heading",
        "element_type": ElementType.TEXT,
        "geometry": box(1011, 920, 325, 95),
        "style_properties": {
            "font_size_ratio": ratio(36),
            "font_weight": "700",
            "color": INK,
            "text_transform": "uppercase",
            "line_height": 1.1,
        },
        "default_content": "Property\nfeatures",
        "z_index": 10,
    },
    {
        "key": "features_rule",
        "label": "Features rule",
        "element_type": ElementType.DIVIDER,
        "geometry": box(1011, 1040, 332, 3),
        "style_properties": {"background_color": INK},
        "z_index": 4,
    },
]

#: The five icon + label rows. Icons are agent-fillable image slots rather
#: than baked artwork, because the source glyphs were not supplied — an empty
#: slot is visible and replaceable, whereas a missing static asset renders as
#: nothing and cannot be selected.
FEATURE_ROWS = [
    ("bathrooms", 1092, "2 bathrooms", 90, 52),
    ("bedrooms", 1230, "3 bedrooms", 88, 46),
    ("kitchen", 1360, "Kitchen", 84, 50),
    ("area", 1496, "1000 sq. ft.", 84, 48),
    ("garage", 1624, "Garage", 90, 40),
]

for index, (name, y_px, label_text, icon_w, icon_h) in enumerate(FEATURE_ROWS):
    ELEMENTS.append(
        {
            "key": f"feature_icon_{name}",
            "label": f"Feature icon — {label_text}",
            "element_type": ElementType.IMAGE,
            "geometry": box(1018, y_px, icon_w, icon_h),
            "style_properties": {"object_fit": "contain", "object_position": "center center"},
            "z_index": 5,
        }
    )
    ELEMENTS.append(
        {
            "key": f"feature_label_{name}",
            "label": f"Feature — {label_text}",
            "element_type": ElementType.TEXT,
            "geometry": box(1110, y_px + 4, 283, 44),
            "style_properties": {
                "font_size_ratio": ratio(28),
                "font_weight": "400",
                "color": INK,
                "text_transform": "uppercase",
                "vertical_align": "center",
            },
            "default_content": label_text,
            "z_index": 10,
        }
    )

ELEMENTS += [
    # -- price / contact footer --------------------------------------------
    {
        "key": "footer_rule",
        "label": "Footer rule",
        "element_type": ElementType.DIVIDER,
        "geometry": box(0, 1752, 1414, 3),
        "style_properties": {"background_color": INK},
        "z_index": 4,
    },
    {
        "key": "price_label",
        "label": "Price label",
        "element_type": ElementType.TEXT,
        "geometry": box(71, 1788, 354, 40),
        "style_properties": {
            "font_size_ratio": ratio(32),
            "font_weight": "700",
            "color": INK,
            "text_transform": "uppercase",
        },
        "default_content": "Offered at",
        "z_index": 10,
    },
    {
        "key": "price_value",
        "label": "Price",
        "element_type": ElementType.TEXT,
        "geometry": box(71, 1826, 594, 100),
        "style_properties": {
            "font_size_ratio": ratio(90),
            "font_weight": "900",
            "color": INK,
            "line_height": 1.0,
        },
        "content_source": "listing.price",
        "default_content": "$1.599.999",
        "z_index": 10,
    },
    {
        "key": "footer_divider",
        "label": "Footer divider",
        "element_type": ElementType.DIVIDER,
        "geometry": box(742, 1786, 3, 130),
        "style_properties": {"background_color": INK},
        "z_index": 4,
    },
    {
        "key": "contact_label",
        "label": "Contact label",
        "element_type": ElementType.TEXT,
        "geometry": box(912, 1788, 396, 40),
        "style_properties": {
            "font_size_ratio": ratio(32),
            "font_weight": "700",
            "color": INK,
            "text_transform": "uppercase",
        },
        "default_content": "Contact us now",
        "z_index": 10,
    },
    {
        "key": "contact_phone",
        "label": "Phone",
        "element_type": ElementType.TEXT,
        "geometry": box(912, 1844, 311, 40),
        "style_properties": {
            "font_size_ratio": ratio(28),
            "font_weight": "400",
            "color": INK,
        },
        "content_source": "agent.phone",
        "default_content": "+123-456-7890",
        "z_index": 10,
    },
    {
        "key": "contact_website",
        "label": "Website",
        "element_type": ElementType.TEXT,
        "geometry": box(912, 1888, 396, 40),
        "style_properties": {
            "font_size_ratio": ratio(28),
            "font_weight": "400",
            "color": INK,
            "text_transform": "uppercase",
        },
        "content_source": "brokerage.website",
        "default_content": "reallygreatsite.com",
        "z_index": 10,
    },
]


class Command(BaseCommand):
    help = "Create or refresh the 'Your Dream Living Space' flyer template only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Rebuild this template's elements if it already exists.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        existing = Template.objects.filter(slug=SLUG).first()
        if existing and not options["replace"]:
            self.stdout.write(
                self.style.WARNING(
                    f"'{SLUG}' already exists ({existing.elements.count()} elements). "
                    "Pass --replace to rebuild it."
                )
            )
            return

        template, created = Template.objects.update_or_create(
            slug=SLUG,
            defaults={
                "name": "Your Dream Living Space — Flyer",
                # Deliberately NOT one of LISTING_CATEGORIES. Every field here
                # binds to listing data through content_source and fills in the
                # moment a listing is attached — but each also carries the
                # artwork's own wording as default_content, so the flyer opens
                # and edits with no listing at all. Marking it NEW_LISTING would
                # gate the whole template behind listing verification for a
                # design that renders perfectly well without one.
                "category": TemplateCategory.MARKET_UPDATE,
                "style": TemplateStyle.MINIMAL,
                "description": (
                    "A4 property flyer: hero exterior, four interior photos, a "
                    "feature checklist and a price/contact footer. Reconstructed "
                    "from the supplied artwork. Attach a listing to auto-fill "
                    "the photos, address and price."
                ),
                "layout_definition": {"background_color": CREAM},
                "default_dimension": "flyer_portrait",
                "allows_added_elements": True,
                "is_active": True,
            },
        )

        # Only this template's elements are touched.
        template.elements.all().delete()
        for spec in ELEMENTS:
            TemplateElement.objects.create(template=template, **spec)

        verb = "created" if created else "rebuilt"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: {template.name} ({template.elements.count()} elements, "
                f"opens at {template.default_dimension})"
            )
        )
        self.stdout.write(
            f"library now holds {Template.objects.count()} template(s) — "
            "no other template was touched."
        )
