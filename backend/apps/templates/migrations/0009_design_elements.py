"""The design document replaces the override diff.

Three things happen here, in this order and for this reason:

  1. ``Design.elements`` is added.
  2. Every existing design is backfilled: its template's elements are copied
     in, the design's ``overrides`` are folded on top, and its
     ``extra_elements`` are appended as ordinary elements. A design that has
     been worked on for weeks must not come out of this migration looking like
     a fresh copy of its template.
  3. ``TemplateElement.permission`` is dropped.

Step 3 comes last on purpose: the backfill in step 2 does not read it, but a
reverse migration has to put a value back, and doing the drop after the data
move keeps the two halves independently reversible.

The backfill does NOT import ``apps.templates.document``. Migrations run
against historical models and must keep working when that module changes
shape; everything it needs is a few dozen lines, written out here against the
frozen schema.
"""

from __future__ import annotations

import uuid

from django.db import migrations, models

# Frozen copies of the mappings in document.py. Duplicated deliberately: this
# migration must produce the same result in a year's time regardless of what
# the live module has become.
TYPE_FROM_TEMPLATE = {
    "text": "text",
    "image": "image",
    "logo": "logo",
    "color_block": "shape",
    "divider": "line",
    "badge": "button",
    "static_graphic": "image",
}

BINDING_BY_PATH = {
    "property.price": "price", "listing.price": "price",
    "property.bedrooms": "bedrooms", "listing.bedrooms": "bedrooms",
    "property.bathrooms": "bathrooms", "listing.bathrooms": "bathrooms",
    "property.square_footage": "area", "listing.square_footage": "area",
    "property.location": "location", "listing.location": "location",
    "property.full_address": "address", "listing.full_address": "address",
    "property.property_type": "property_type", "listing.property_type": "property_type",
    "property.description": "description", "listing.description": "description",
    "property.photos[0]": "photo_1", "listing.photos[0]": "photo_1",
    "property.photos[1]": "photo_2", "listing.photos[1]": "photo_2",
    "property.photos[2]": "photo_3", "listing.photos[2]": "photo_3",
    "property.photos[3]": "photo_4", "listing.photos[3]": "photo_4",
    "property.photos[4]": "photo_5", "listing.photos[4]": "photo_5",
    "property.main_photo": "photo_1", "listing.main_photo": "photo_1",
    "property.photo": "photo_1", "listing.photo": "photo_1",
    "agent.full_name": "agent_name", "agent.name": "agent_name",
    "agent.phone": "agent_phone", "agent.email": "agent_email",
    "agent.job_title": "agent_title", "agent.licence_number": "agent_licence",
    "agent.photo": "agent_photo",
    "brokerage.name": "brokerage_name", "brokerage.phone": "brokerage_phone",
    "brokerage.website": "brokerage_website", "brokerage.logo": "brokerage_logo",
    "brokerage.disclaimer": "disclaimer",
    "brokerage.required_disclaimer": "disclaimer",
}

STYLE_KEYS = {
    "color", "background_color", "border_color", "tint_color",
    "font_size_ratio", "line_height", "letter_spacing_em", "opacity",
    "border_radius_ratio", "border_width_ratio", "padding_ratio",
    "font_weight", "text_align", "vertical_align", "font_style",
    "text_transform", "text_decoration", "object_fit", "object_position",
    "border_style", "background_gradient", "format",
}

IMAGE_TYPES = {"image", "logo", "icon"}


def _new_id():
    return f"el-{uuid.uuid4().hex[:12]}"


def _element(template_element, override, index):
    """One template element plus this design's override for it."""
    element_type = TYPE_FROM_TEMPLATE.get(template_element.element_type, "text")

    geometry = dict(template_element.geometry or {})
    geometry.update(override.get("geometry") or {})

    style = {
        key: value
        for key, value in (template_element.style_properties or {}).items()
        if key in STYLE_KEYS and value is not None
    }
    for key, value in override.items():
        if key in STYLE_KEYS and value is not None:
            style[key] = value

    # Content. An image element's content is a storage key: the agent's own
    # `image_key` override if they set one, otherwise the template's static
    # asset if it had one, otherwise nothing (it resolves from content_source).
    if element_type in IMAGE_TYPES:
        content = override.get("image_key") or ""
        if not content and template_element.element_type == "static_graphic":
            content = template_element.static_asset.name if template_element.static_asset else ""
    else:
        content = override.get("text")
        if content is None:
            content = template_element.default_content or ""

    source = template_element.content_source or ""
    # Text the agent typed themselves detaches from the data that fed it —
    # otherwise a later "sync from property data" would silently throw their
    # wording away. Flagged rather than unbound so the sync stays *possible*.
    manually_overridden = "text" in override or "image_key" in override

    z_index = override.get("z_index")
    if z_index is None:
        z_index = template_element.z_index or index

    return {
        "id": _new_id(),
        "original_element_id": template_element.key,
        "type": element_type,
        "name": template_element.label or template_element.key.replace("_", " ").title(),
        # The migration that unlocks everything. Whatever tier the element
        # carried, the design's copy arrives editable.
        "locked": False,
        "visible": not bool(override.get("hidden")),
        "transform": {
            "x": float(geometry.get("x", 0.0)),
            "y": float(geometry.get("y", 0.0)),
            "width": float(geometry.get("width", 0.2)),
            "height": float(geometry.get("height", 0.1)),
            "rotation": float(geometry.get("rotation", 0.0)),
            "z_index": int(z_index),
        },
        "content": content,
        "content_source": source,
        "bound_to": BINDING_BY_PATH.get(source),
        "manually_overridden": manually_overridden,
        "style": style,
    }


def _extra_element(entry, index):
    """One entry of the old ``extra_elements`` list, as a document element."""
    element_type = TYPE_FROM_TEMPLATE.get(entry.get("element_type", "text"), "text")
    geometry = entry.get("geometry") or {}
    style = {
        key: value
        for key, value in (entry.get("style") or {}).items()
        if key in STYLE_KEYS and value is not None
    }
    content = entry.get("content") or ""
    return {
        "id": _new_id(),
        # Added by the agent, so there is no template original to reset to.
        "original_element_id": None,
        "type": element_type,
        "name": entry.get("label") or "Added element",
        "locked": False,
        "visible": not bool(entry.get("hidden")),
        "transform": {
            "x": float(geometry.get("x", 0.0)),
            "y": float(geometry.get("y", 0.0)),
            "width": float(geometry.get("width", 0.2)),
            "height": float(geometry.get("height", 0.1)),
            "rotation": float(geometry.get("rotation", 0.0)),
            "z_index": int(entry.get("z_index", index)),
        },
        "content": "" if element_type in IMAGE_TYPES else str(content),
        "content_source": "",
        "bound_to": None,
        "manually_overridden": True,
        "style": style,
    }


def backfill(apps, schema_editor):
    Design = apps.get_model("templates", "Design")

    for design in Design.objects.select_related("template").prefetch_related(
        "template__elements"
    ):
        if design.elements:
            continue
        overrides = design.overrides or {}
        elements = [
            _element(template_element, dict(overrides.get(template_element.key, {})), index)
            for index, template_element in enumerate(design.template.elements.all())
        ]
        offset = len(elements)
        elements.extend(
            _extra_element(entry, offset + index)
            for index, entry in enumerate(design.extra_elements or [])
        )
        design.elements = elements
        design.save(update_fields=["elements"])


def unbackfill(apps, schema_editor):
    """Reversing drops the document and leaves the old fields as they were.

    `overrides` and `extra_elements` were never cleared by the forward
    migration precisely so this direction has something to fall back to.
    """
    Design = apps.get_model("templates", "Design")
    Design.objects.update(elements=[])


class Migration(migrations.Migration):

    dependencies = [("templates", "0008_template_default_dimension")]

    operations = [
        migrations.AddField(
            model_name="design",
            name="elements",
            field=models.JSONField(blank=True, default=list, verbose_name="elements"),
        ),
        migrations.AlterField(
            model_name="design",
            name="overrides",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Superseded by `elements`. Retained so pre-canvas designs "
                    "remain readable; no code path writes this field."
                ),
                verbose_name="overrides (legacy)",
            ),
        ),
        migrations.AlterField(
            model_name="design",
            name="extra_elements",
            field=models.JSONField(
                blank=True, default=list, verbose_name="extra elements (legacy)"
            ),
        ),
        migrations.RunPython(backfill, unbackfill),
        migrations.RemoveField(model_name="templateelement", name="permission"),
    ]
