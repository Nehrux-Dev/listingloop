"""Compose the HTML for one design at one dimension.

Django owns this, not the renderer service. The renderer stays a dumb
"HTML in, image out" box, which means it can be swapped, scaled or replaced
without any template logic moving with it — and it can be tested here, in
Python, without a browser.

Geometry is fractional, so mapping a template onto Instagram Post, Story,
Facebook or LinkedIn is arithmetic rather than four hand-built layouts. Element
coordinates are mapped into the *safe area* of the target dimension so nothing
important lands under platform chrome.
"""

from __future__ import annotations

import html
import json
from typing import Any

from apps.templates.dimensions import Dimension
from apps.templates.models import ElementType
from apps.templates.render_context import resolve_path

#: Only families we know are installed in the renderer image. A brand kit can
#: name anything; unknown families fall back rather than silently rendering in
#: whatever the browser picks, which would differ between environments.
SAFE_FONT_STACK = (
    "'DejaVu Sans', 'Liberation Sans', 'Noto Sans', 'Helvetica Neue', Arial, sans-serif"
)


def _format_value(value: Any, fmt: str | None) -> str:
    if value is None:
        return ""
    if fmt == "currency":
        try:
            return f"${float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)
    if fmt == "number":
        try:
            return f"{float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)
    if fmt == "upper":
        return str(value).upper()
    if fmt == "list":
        return " · ".join(str(item) for item in value) if isinstance(value, list) else str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def resolve_element_content(element, override: dict, context: dict) -> Any:
    """Override wins, then the element's content source, then its default."""
    if element.element_type in (ElementType.IMAGE, ElementType.LOGO):
        if override.get("image_key"):
            # Resolved by the caller into a data URI; see build_html.
            return override["image_key"]
        if element.content_source:
            return resolve_path(context, element.content_source)
        return element.default_content or None

    if "text" in override:
        return override["text"]
    if element.content_source:
        value = resolve_path(context, element.content_source)
        if value not in (None, "", []):
            return _format_value(value, element.style_properties.get("format"))
    return element.default_content


def _merged_style(element, override: dict) -> dict:
    """Element defaults, then whatever the override is *allowed* to change.

    By the time an override reaches here it has already been validated against
    the element's permission, so this merge cannot widen anyone's rights — it
    is presentation only.
    """
    style = dict(element.style_properties or {})
    for field in (
        "color",
        "background_color",
        "font_size_ratio",
        "font_weight",
        "text_align",
    ):
        if field in override:
            style[field] = override[field]
    return style


def _resolve_color(value: Any, context: dict) -> str:
    """Allow a style value to reference the brand kit, e.g. `@accent_color`."""
    if isinstance(value, str) and value.startswith("@"):
        return context["brand_kit"].get(value[1:], "#000000")
    return value if isinstance(value, str) else "transparent"


def _geometry(element, override: dict) -> dict:
    geometry = dict(element.geometry or {})
    if "geometry" in override:
        geometry.update(override["geometry"])
    return {
        "x": float(geometry.get("x", 0.0)),
        "y": float(geometry.get("y", 0.0)),
        "width": float(geometry.get("width", 1.0)),
        "height": float(geometry.get("height", 0.1)),
    }


def type_scale_reference(dimension: Dimension) -> float:
    """The length that font sizes and spacing scale against.

    The *smaller* side, deliberately. Scaling type with canvas height looked
    right at 1:1 and broke at 9:16: a Story is 1.8x taller than a Post but no
    wider, so height-scaled type grew while the text box did not, and long
    headings wrapped into the element below them. Scaling with width instead
    just moves the problem to the wide formats, where a 1200x630 banner would
    get type taller than its own boxes.

    min(width, height) keeps text inside its box in every supported aspect
    ratio, which is the property that actually matters.
    """
    return float(min(dimension.width, dimension.height))


def _element_html(element, override: dict, context: dict, dimension: Dimension) -> str:
    if override.get("hidden"):
        return ""

    geometry = _geometry(element, override)
    style = _merged_style(element, override)
    scale_ref = type_scale_reference(dimension)

    # Map the fractional coordinate space into the dimension's safe area.
    safe_top = dimension.safe_inset_top
    safe_height = 1.0 - dimension.safe_inset_top - dimension.safe_inset_bottom

    left = geometry["x"] * dimension.width
    top = (safe_top + geometry["y"] * safe_height) * dimension.height
    width = geometry["width"] * dimension.width
    height = geometry["height"] * safe_height * dimension.height

    css = [
        "position:absolute",
        f"left:{left:.2f}px",
        f"top:{top:.2f}px",
        f"width:{width:.2f}px",
        f"height:{height:.2f}px",
        f"z-index:{element.z_index}",
        "box-sizing:border-box",
    ]

    background = style.get("background_color")
    if background:
        css.append(f"background-color:{_resolve_color(background, context)}")
    if style.get("border_radius_ratio"):
        css.append(f"border-radius:{float(style['border_radius_ratio']) * scale_ref:.2f}px")
    if style.get("opacity") is not None:
        css.append(f"opacity:{float(style['opacity'])}")
    if style.get("background_gradient"):
        css.append(f"background-image:{style['background_gradient']}")

    content = resolve_element_content(element, override, context)

    if element.element_type in (ElementType.IMAGE, ElementType.LOGO):
        if not content:
            return ""
        css.append("overflow:hidden")
        fit = style.get("object_fit", "cover")
        inner = (
            f'<img src="{html.escape(str(content), quote=True)}" '
            f'style="width:100%;height:100%;object-fit:{fit};display:block;" />'
        )
        return f'<div style="{";".join(css)}">{inner}</div>'

    if element.element_type in (ElementType.COLOR_BLOCK, ElementType.DIVIDER):
        return f'<div style="{";".join(css)}"></div>'

    # Text and badge.
    text = str(content or "")
    if not text.strip():
        return ""

    font_px = float(style.get("font_size_ratio", 0.04)) * scale_ref
    align = style.get("text_align", "left")
    justify = {"left": "flex-start", "center": "center", "right": "flex-end"}[align]

    css.extend(
        [
            "display:flex",
            "flex-direction:column",
            f"justify-content:{style.get('vertical_align', 'flex-start')}",
            f"align-items:{justify}",
            f"text-align:{align}",
            f"font-size:{font_px:.2f}px",
            f"font-weight:{style.get('font_weight', '400')}",
            f"line-height:{style.get('line_height', 1.2)}",
            f"color:{_resolve_color(style.get('color', '#000000'), context)}",
            f"font-family:{SAFE_FONT_STACK}",
        ]
    )
    if style.get("letter_spacing_em"):
        css.append(f"letter-spacing:{float(style['letter_spacing_em'])}em")
    if style.get("text_transform"):
        css.append(f"text-transform:{style['text_transform']}")
    if style.get("padding_ratio"):
        css.append(f"padding:{float(style['padding_ratio']) * scale_ref:.2f}px")
    # Text that outgrows its box would otherwise sit on top of the element
    # below it, which is worse than a clipped descender.
    css.append("overflow:hidden")

    body = html.escape(text).replace("\n", "<br />")
    return f'<div style="{";".join(css)}">{body}</div>'


def build_html(design, context: dict, dimension: Dimension, image_overrides: dict) -> str:
    """Return a complete HTML document for one design at one dimension.

    ``image_overrides`` maps element key -> data URI, resolved by the caller
    (which owns storage access) so this function stays pure.
    """
    layout = design.template.layout_definition or {}
    background = _resolve_color(layout.get("background_color", "#FFFFFF"), context)

    overrides = design.overrides or {}
    parts = []
    for element in design.template.elements.all():
        override = dict(overrides.get(element.key, {}))
        if element.key in image_overrides:
            override["image_key"] = image_overrides[element.key]
        parts.append(_element_html(element, override, context, dimension))

    body = "".join(part for part in parts if part)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(design.name)}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:{dimension.width}px; height:{dimension.height}px; overflow:hidden; }}
  body {{ background:{background}; font-family:{SAFE_FONT_STACK};
          -webkit-font-smoothing:antialiased; }}
  #canvas {{ position:relative; width:{dimension.width}px; height:{dimension.height}px;
             overflow:hidden; }}
</style></head>
<body><div id="canvas">{body}</div></body></html>"""


def describe_design(design, context: dict, dimension: Dimension) -> dict:
    """A JSON description of the resolved design.

    Used by the editor to show current values and by tests to assert on
    resolution without rendering an image.
    """
    overrides = design.overrides or {}
    elements = []
    for element in design.template.elements.all():
        override = overrides.get(element.key, {})
        elements.append(
            {
                "key": element.key,
                "label": element.label,
                "element_type": element.element_type,
                "permission": element.permission,
                "constraints": element.constraints,
                "geometry": _geometry(element, override),
                "style": _merged_style(element, override),
                "content": resolve_element_content(element, override, context),
                "hidden": bool(override.get("hidden")),
                "overridden_fields": sorted(override.keys()),
            }
        )
    return {
        "dimension": dimension.key,
        "width": dimension.width,
        "height": dimension.height,
        "elements": elements,
    }


def to_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
