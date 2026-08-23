"""Compose the HTML for one design at one dimension.

Django owns this, not the renderer service. The renderer stays a dumb
"HTML in, image out" box, which means it can be swapped, scaled or replaced
without any template logic moving with it — and it can be tested here, in
Python, without a browser.

Geometry is fractional, so mapping a design onto Instagram Post, Story,
Facebook or LinkedIn is arithmetic rather than four hand-built layouts. Element
coordinates are mapped into the *safe area* of the target dimension so nothing
important lands under platform chrome.

WHAT IT RENDERS FROM
--------------------
``design.elements`` — the design's own document (see ``document.py``). Not the
template, and not a diff against it. A design was deep-copied from its
template when it was created and has owned its elements ever since, so there
is one list to walk and no permission tier to consult.

HOW A BOUND ELEMENT RESOLVES
----------------------------
An element with ``bound_to`` (price, agent_phone, photo_1, ...) renders the
*current* value of that field, so correcting a listing's price fixes every
design that shows it. Once the agent types over it, ``manually_overridden``
goes true and their words win from then on — clearing that flag is the "sync
to current data" action, and is why the binding is flagged rather than
deleted.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from apps.templates.dimensions import Dimension
from apps.templates.document import (
    BACKGROUND_TYPE,
    LINE_TYPE,
    SHAPE_TYPE,
    carries_image,
    carries_text,
    sorted_for_render,
)
from apps.templates.render_context import resolve_path

#: Only families we know are installed in the renderer image. A brand kit can
#: name anything; unknown families fall back rather than silently rendering in
#: whatever the browser picks, which would differ between environments.
SAFE_FONT_STACK = (
    "'DejaVu Sans', 'Liberation Sans', 'Noto Sans', 'Helvetica Neue', Arial, sans-serif"
)

#: What each ``font_family`` role resolves to. The roles are the vocabulary a
#: template speaks (see ``document.FONT_FAMILIES``); these stacks are the only
#: place a real family name appears, and every family named here is installed
#: by renderer/Dockerfile.
#:
#: ``display`` is condensed on purpose. Artwork imported from a real flyer is
#: almost always set in a narrow display face, and laying that headline out in
#: a normal-width family reflows it onto an extra line or two — which reads as
#: broken geometry rather than as a missing font.
FONT_STACKS: dict[str, str] = {
    "body": SAFE_FONT_STACK,
    "display": (
        "'Roboto Condensed', 'Liberation Sans Narrow', 'DejaVu Sans Condensed', "
        + SAFE_FONT_STACK
    ),
    "serif": "'Liberation Serif', 'DejaVu Serif', Georgia, serif",
    "mono": "'Liberation Mono', 'DejaVu Sans Mono', monospace",
    # Calligraphic headlines. Dancing Script is the closest formal script in
    # Debian; the copperplate faces this kind of artwork actually uses are all
    # proprietary, so this is an approximation and a deliberate one — a script
    # that is nearly right reads as the same design, where a serif does not.
    "script": "'Dancing Script', 'Kaushan Script', 'Lobster Two', cursive",
    # The authoring palette — roles an agent chooses in the editor's font
    # picker, all resolved to families the renderer image installs from
    # Debian's own archive (renderer/Dockerfile). Fallbacks are the closest
    # metric neighbours already in the stacks above, so a missing family
    # degrades to a same-shaped face rather than to fontconfig's guess.
    "elegant": "'EB Garamond', 'Liberation Serif', Georgia, serif",
    "modern": "'Lato', " + SAFE_FONT_STACK,
    "rounded": "'Quicksand', 'Trebuchet MS', " + SAFE_FONT_STACK,
    "slab": "'Roboto Slab', 'Liberation Serif', Georgia, serif",
    "retro": "'Lobster Two', 'Dancing Script', cursive",
    "soft": "'Comfortaa', 'Quicksand', " + SAFE_FONT_STACK,
}


def font_stack(style: dict) -> str:
    """The CSS font stack for one element. Unknown roles fall back to body."""
    return FONT_STACKS.get(str(style.get("font_family") or "body"), SAFE_FONT_STACK)


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


#: `{{ agent.full_name }}` — with optional whitespace and an optional filter,
#: e.g. `{{ property.price | currency }}`.
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w.]*(?:\[\d+\])?)\s*(?:\|\s*(\w+)\s*)?\}\}")


def interpolate(text: str, context: dict) -> str:
    """Substitute ``{{ path }}`` placeholders from the template context.

    Runs over literal element text, so a designer — or an agent — can write

        "Presented by {{ agent.full_name }} at {{ brokerage.name }}"

    instead of needing one element per field.

    An unresolved placeholder becomes an empty string rather than being left on
    the canvas: a rendered image reading "Presented by {{ agent.full_name }}"
    is worse than one reading "Presented by" — and the profile-completion gate
    is what stops that second case reaching a render at all.
    """
    if not text or "{{" not in text:
        return text

    def replace(match: re.Match[str]) -> str:
        value = resolve_path(context, match.group(1))
        if value is None:
            return ""
        return _format_value(value, match.group(2))

    return PLACEHOLDER_RE.sub(replace, text)


def unresolved_placeholders(text: str, context: dict) -> list[str]:
    """Which placeholders in ``text`` have no value. Used by the readiness check."""
    if not text or "{{" not in text:
        return []
    return [
        match.group(1)
        for match in PLACEHOLDER_RE.finditer(text)
        if resolve_path(context, match.group(1)) in (None, "", [])
    ]


def resolve_content(element: dict, context: dict, images: dict) -> Any:
    """What this element actually displays.

    Order of precedence, and the reasoning for it:

      1. The element's bound/sourced value, when it has one and the agent has
         not typed over it. This is what makes a price correction reach every
         design that shows the price.
      2. A resolved image for this element id — the caller turned a storage key
         into a data URI, because only it has storage access.
      3. The element's own stored content, interpolated — the agent's words,
         or the template's default text where they never changed it.

    IMAGES: WHY THE BINDING OUTRANKS THE STORED KEY
    ---------------------------------------------------------------------
    An imported template carries a crop of the source artwork in every photo
    slot, *and* a binding to ``listing.photos[n]``. The crop is there so the
    design opens looking like the flyer it came from instead of showing empty
    boxes; the binding is there so attaching a property fills it with that
    property's own photographs. Only one of them can be right at a time, and
    it is the binding — a marketing asset that keeps showing stock artwork
    after a real listing was attached is the failure that actually reaches a
    client.

    The agent's own choice still wins over both: replacing an image sets
    ``manually_overridden``, which takes the binding out of the running and
    leaves their pick as the stored key.
    """
    element_type = element.get("type", "")
    stored = element.get("content") or ""

    if carries_image(element_type, stored):
        if element.get("content_source") and not element.get("manually_overridden"):
            bound = resolve_path(context, element["content_source"])
            if bound not in (None, "", []):
                return bound
            # No listing attached, or that slot is empty: fall through to the
            # template's baked artwork rather than rendering a hole.
        if element["id"] in images:
            return images[element["id"]]
        return None

    if element.get("content_source") and not element.get("manually_overridden"):
        value = resolve_path(context, element["content_source"])
        if value not in (None, "", []):
            return _format_value(value, (element.get("style") or {}).get("format"))
        # A bound field with nothing in it falls through to whatever text the
        # element carries, so a template's placeholder wording still shows
        # rather than the element vanishing mid-layout.

    return interpolate(str(stored), context)


def _resolve_color(value: Any, context: dict) -> str:
    """Allow a style value to reference the brand kit, e.g. `@accent_color`."""
    if isinstance(value, str) and value.startswith("@"):
        return context["brand_kit"].get(value[1:], "#000000")
    return value if isinstance(value, str) else "transparent"


def _transform(element: dict) -> dict:
    raw = element.get("transform") or {}
    return {
        "x": float(raw.get("x", 0.0)),
        "y": float(raw.get("y", 0.0)),
        "width": float(raw.get("width", 1.0)),
        "height": float(raw.get("height", 0.1)),
        "rotation": float(raw.get("rotation", 0.0)),
        "z_index": int(raw.get("z_index", 0)),
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


def _dot_pattern(style: dict, scale_ref: float, context: dict) -> list[str]:
    """A dotted ground, rebuilt as a tiling pattern rather than a flat fill.

    A repeating grid of dots is a *pattern*, and flattening it to the average
    colour of the area — or to the colour of one dot — produces something that
    looks nothing like the artwork. So the extractor records the dot's colour,
    its radius and the grid spacing, and this rebuilds it: one tile containing
    one dot, repeated.

    Built out of numbers, never out of a string the extractor supplied. This is
    the same rule ``clip_polygon`` follows and for the same reason:
    ``background-image`` takes a ``url(...)``, so a pass-through string here
    would be a way to make the renderer fetch something. Numbers cannot express
    a URL.
    """
    if style.get("fill_type") != "dot_pattern":
        return []
    radius = float(style.get("dot_radius_ratio") or 0) * scale_ref
    spacing_x = float(style.get("dot_spacing_x_ratio") or 0) * scale_ref
    spacing_y = float(style.get("dot_spacing_y_ratio") or 0) * scale_ref
    if radius <= 0 or spacing_x <= 0 or spacing_y <= 0:
        return []
    colour = _resolve_color(style.get("dot_color", "#000000"), context)
    # `radius` twice: the colour stop ends exactly where the dot's edge is, so
    # the gradient draws a hard-edged circle rather than a soft blob.
    return [
        f"background-image:radial-gradient(circle at 50% 50%, "
        f"{colour} 0 {radius:.2f}px, transparent {radius:.2f}px)",
        f"background-size:{spacing_x:.2f}px {spacing_y:.2f}px",
        "background-repeat:repeat",
    ]


def _clip_path(points: Any) -> str:
    """``clip-path`` for an element whose visible edge is not its box.

    Angled and chevron photo edges are ordinary in property flyers, and this is
    what lets an imported one keep its shape — including after the agent drops
    a different photograph into the slot, which a shape baked into the image's
    own alpha channel could never survive.

    The CSS is assembled here from numbers that ``document._validate_clip_polygon``
    has already proved are numbers. Nothing string-shaped from an element ever
    reaches this property: ``clip-path`` takes a function, and a function is
    somewhere a crafted string could hide a ``url(...)`` and make the renderer
    fetch from a host the user chose.
    """
    if not isinstance(points, (list, tuple)) or len(points) < 6 or len(points) % 2:
        return ""
    pairs = [
        f"{float(points[index]):.3f}% {float(points[index + 1]):.3f}%"
        for index in range(0, len(points), 2)
    ]
    return f"clip-path:polygon({','.join(pairs)})"


def _image_framing(style: dict) -> str:
    """The CSS that expresses zoom-and-pan inside an image's frame.

    A crop, without ever re-encoding the file. ``image_scale`` blows the
    picture up inside its box and ``image_offset_x/y`` slide it around; the
    box keeps ``overflow:hidden``, so the result is exactly the visible
    rectangle the agent dragged out. Doing it in CSS means the editor and the
    export agree by construction — both are laying out the same box.
    """
    scale = float(style.get("image_scale", 1.0) or 1.0)
    offset_x = float(style.get("image_offset_x", 0.0) or 0.0)
    offset_y = float(style.get("image_offset_y", 0.0) or 0.0)
    if scale == 1.0 and not offset_x and not offset_y:
        return ""
    return (
        f"transform:translate({offset_x * 100:.2f}%,{offset_y * 100:.2f}%) "
        f"scale({scale:.3f});transform-origin:center center;"
    )


def element_html(element: dict, context: dict, dimension: Dimension, images: dict) -> str:
    """One document element as absolutely-positioned HTML."""
    if not element.get("visible", True):
        return ""

    transform = _transform(element)
    style = element.get("style") or {}
    element_type = element.get("type", "")
    scale_ref = type_scale_reference(dimension)

    # Map the fractional coordinate space into the dimension's safe area.
    safe_top = dimension.safe_inset_top
    safe_height = 1.0 - dimension.safe_inset_top - dimension.safe_inset_bottom

    left = transform["x"] * dimension.width
    top = (safe_top + transform["y"] * safe_height) * dimension.height
    width = transform["width"] * dimension.width
    height = transform["height"] * safe_height * dimension.height

    css = [
        "position:absolute",
        f"left:{left:.2f}px",
        f"top:{top:.2f}px",
        f"width:{width:.2f}px",
        f"height:{height:.2f}px",
        f"z-index:{transform['z_index']}",
        "box-sizing:border-box",
    ]

    # Rotating around the box's own centre, not the canvas origin, is what
    # makes the rendered result match what the rotate handle showed.
    if transform["rotation"]:
        css.append(f"transform:rotate({transform['rotation']:.2f}deg)")
        css.append("transform-origin:center center")

    background = style.get("background_color")
    if background:
        css.append(f"background-color:{_resolve_color(background, context)}")
    if style.get("border_radius_ratio"):
        css.append(f"border-radius:{float(style['border_radius_ratio']) * scale_ref:.2f}px")
    if style.get("opacity") is not None:
        css.append(f"opacity:{float(style['opacity'])}")
    if style.get("background_gradient"):
        css.append(f"background-image:{style['background_gradient']}")
    dots = _dot_pattern(style, scale_ref, context)
    if dots:
        css.extend(dots)
    clip = _clip_path(style.get("clip_polygon"))
    if clip:
        css.append(clip)
    # A border is only drawn when it has a real width — a colour on its own
    # would silently do nothing, and `border-style:solid` with width 0 is a
    # no-op that still costs a CSS declaration. Width scales with the canvas
    # like every other ratio here, so a border looks the same relative to the
    # design at 1080px as it does at 1920px.
    if style.get("border_width_ratio"):
        border_px = float(style["border_width_ratio"]) * scale_ref
        border_color = _resolve_color(style.get("border_color", "#000000"), context)
        border_style = style.get("border_style", "solid")
        css.append(f"border:{border_px:.2f}px {border_style} {border_color}")

    content = resolve_content(element, context, images)

    if carries_image(element_type, content):
        if not content:
            # A background with no picture is still a filled box; every other
            # image type with nothing in it has nothing to draw.
            if element_type == BACKGROUND_TYPE:
                return f'<div style="{";".join(css)}"></div>'
            return ""
        css.append("overflow:hidden")
        fit = style.get("object_fit", "cover")
        position = style.get("object_position", "center center")
        framing = _image_framing(style)
        # An icon is usually a single-colour glyph, so a tint is expressed as a
        # CSS filter over the image rather than by editing the file.
        tint = ""
        if style.get("tint_color"):
            colour = _resolve_color(style["tint_color"], context)
            tint = f"background-color:{colour};-webkit-mask-image:url({content});"
            tint += "-webkit-mask-size:contain;-webkit-mask-repeat:no-repeat;"
            tint += "-webkit-mask-position:center;"
            return f'<div style="{";".join(css)}"><div style="width:100%;height:100%;{tint}"></div></div>'
        inner = (
            f'<img src="{html.escape(str(content), quote=True)}" '
            f'style="width:100%;height:100%;object-fit:{fit};'
            f'object-position:{position};display:block;{framing}" />'
        )
        return f'<div style="{";".join(css)}">{inner}</div>'

    if not carries_text(element_type):
        # shape, line, and a background with no photo: a filled box.
        return f'<div style="{";".join(css)}"></div>'

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
            f"font-style:{style.get('font_style', 'normal')}",
            f"line-height:{style.get('line_height', 1.2)}",
            f"color:{_resolve_color(style.get('color', '#000000'), context)}",
            f"font-family:{font_stack(style)}",
        ]
    )
    if style.get("letter_spacing_em"):
        css.append(f"letter-spacing:{float(style['letter_spacing_em'])}em")
    if style.get("text_transform"):
        css.append(f"text-transform:{style['text_transform']}")
    if style.get("text_decoration"):
        css.append(f"text-decoration:{style['text_decoration']}")
    if style.get("padding_ratio"):
        css.append(f"padding:{float(style['padding_ratio']) * scale_ref:.2f}px")
    # Text that outgrows its box would otherwise sit on top of the element
    # below it, which is worse than a clipped descender. This stays as the
    # backstop; `data-fit` is what normally prevents it being reached.
    css.append("overflow:hidden")

    body = html.escape(text).replace("\n", "<br />")
    # Marks this box for the renderer's shrink-to-fit pass — see FIT_ATTRIBUTE
    # above for why the pass is not in this document. Placed after the style
    # attribute so the parity tests' `<div style="...">` match still holds.
    return f'<div style="{";".join(css)}" {FIT_ATTRIBUTE}="1">{body}</div>'


#: The shrink-to-fit contract, documented here because this is where the boxes
#: and font sizes are decided — but deliberately NOT executed here.
#:
#: WHY THE PASS EXISTS
#: ---------------------------------------------------------------------------
#: A template's font size is a ratio of the page, measured off artwork set in
#: some other typeface. The families installed in the renderer are not that
#: typeface, so a headline measured at 96px on the original can render wider
#: here and outgrow the box it was measured into. The answer used to be
#: `overflow:hidden` alone, which cut "$700,000" down to "$700,0" — a silent,
#: entirely plausible wrong number on a page about to go to a client.
#:
#: WHY IT IS NOT A <script> IN THIS DOCUMENT
#: ---------------------------------------------------------------------------
#: The renderer runs every page with `javaScriptEnabled: false`, on the
#: grounds that a template is static HTML and nothing in one needs scripting.
#: That is worth keeping: this markup carries user-influenced content. So the
#: pass lives in the renderer's own `page.evaluate` (see renderer/src/server.js),
#: which still runs, and all this file does is mark which boxes it applies to.
#:
#: Three places therefore have to agree — this marker, the renderer's loop, and
#: the editor canvas's copy of it in ElementLayer.tsx.
FIT_ATTRIBUTE = "data-fit"

#: Mirrored by FIT_MIN_SCALE / FIT_STEPS in renderer/src/server.js and
#: ElementLayer.tsx. Asserted by the parity tests so a change in one place
#: without the others fails loudly rather than splitting canvas from export.
FIT_MIN_SCALE = 0.5
FIT_STEPS = 8


def build_html(design, context: dict, dimension: Dimension, images: dict) -> str:
    """Return a complete HTML document for one design at one dimension.

    ``images`` maps element id -> data URI, resolved by the caller (which owns
    storage access) so this function stays pure.
    """
    layout = design.template.layout_definition or {}
    background = _resolve_color(layout.get("background_color", "#FFFFFF"), context)

    parts = [
        element_html(element, context, dimension, images)
        for element in sorted_for_render(design.ensure_document())
    ]
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


def describe_design(
    design, context: dict, dimension: Dimension, images: dict | None = None
) -> dict:
    """A JSON description of the resolved design — what the editor binds to.

    Every element is returned exactly as stored, plus two derived fields the
    canvas needs and cannot work out for itself:

      ``resolved_content``  what this element currently displays, after the
                            binding and image resolution above. The canvas
                            draws this; ``content`` is what the properties
                            panel edits.
      ``bound_value``       the live value behind the binding, so the panel can
                            offer "sync to current data" and show what syncing
                            would put there.
    """
    images = images or {}
    elements = []
    for element in sorted_for_render(design.ensure_document()):
        bound_value = None
        if element.get("content_source"):
            bound_value = resolve_path(context, element["content_source"])
            if bound_value is not None and not carries_image(
                element.get("type", ""), element.get("content")
            ):
                bound_value = _format_value(
                    bound_value, (element.get("style") or {}).get("format")
                )
        elements.append(
            {
                **element,
                "resolved_content": resolve_content(element, context, images),
                "bound_value": bound_value,
            }
        )

    return {
        "dimension": dimension.key,
        "width": dimension.width,
        "height": dimension.height,
        # Safe-area insets, alongside width/height for the same reason: a
        # client mapping fractional geometry to pixels needs the full picture,
        # not just the raw canvas size. See render_dimensions() in views.py.
        "safe_inset_top": dimension.safe_inset_top,
        "safe_inset_bottom": dimension.safe_inset_bottom,
        "background_color": _resolve_color(
            (design.template.layout_definition or {}).get("background_color", "#FFFFFF"),
            context,
        ),
        "elements": elements,
    }


def to_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


# Kept as an alias: `SHAPE_TYPE`/`LINE_TYPE` are imported here for the
# type checks above, and re-exported so callers that reason about what renders
# as a filled box have one place to ask.
FILLED_BOX_TYPES = frozenset({SHAPE_TYPE, LINE_TYPE})
