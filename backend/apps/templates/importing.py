"""Turn uploaded artwork (a PDF page or an image) into an editable template.

=============================================================================
THE SHAPE OF THE PROBLEM
=============================================================================
A flyer arrives as pixels. A template is a list of elements with fractional
geometry, bindings and styles. Nothing in the file says where one element ends
and the next begins — that judgement is what the vision model is for.

The pipeline is four steps, and they are separated because they fail
differently:

  1. ``rasterise``      — one page of artwork -> one PNG at a known size.
                          Fails on a corrupt or empty file. No network, no cost.
  2. ``extract_layout`` — that PNG -> a list of measured elements.
                          Fails on a provider outage, and costs money each time.
  3. ``bake_assets``    — crop each photo region out of the raster and store it.
                          Fails on storage. Local, cheap, repeatable.
  4. ``build_template`` — elements -> Template + TemplateElement rows.
                          Fails on nothing, by design: everything the model
                          returned has already been clamped into range.

Step 4 refusing to fail is deliberate. A model's answer is *untrusted input*
that happens to be well-formed; strict JSON schema guarantees the shape, not
that the numbers are sane. So every value here is clamped, dropped or
defaulted rather than rejected — an import that produces a slightly wrong
element the user can drag into place is worth far more than one that produces
nothing because element 34 had a negative width.

=============================================================================
WHAT THE MODEL IS AND IS NOT ASKED TO DO
=============================================================================
It is asked for geometry, literal text, colours, and which business field each
element should bind to.

It is NOT asked to describe the content of any photograph. For an image region
it returns a box and a role, and that is all — the pixels come from cropping
the raster, never from a description. Asking a language model to characterise
a photo of somebody's house and then storing that as product content is how a
marketing tool starts confidently asserting things about property it has never
seen.
"""

from __future__ import annotations

import io
import logging
import re
import uuid

from collections import defaultdict
from dataclasses import dataclass, field, replace

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.text import slugify

from apps.ai_content.client import (
    AIConfigurationError,
    AIGenerationError,
    CompletionResult,
    complete_json,
    image_part,
)
from apps.templates.dimensions import SOCIAL_DIMENSIONS
from apps.templates.document import (
    FILL_TYPES,
    FONT_FAMILIES,
    HEX_COLOR,
    PROPERTY_FIELDS_BY_NAME,
    SHAPE_TYPES,
)
from apps.templates.pdf_extraction import extract_pdf_layout, is_text_pdf
from apps.templates.models import (
    ElementType,
    Template,
    TemplateCategory,
    TemplateElement,
    TemplateStyle,
)

logger = logging.getLogger(__name__)


class TemplateImportError(RuntimeError):
    """Extraction failed. The message is shown to the user verbatim."""


# ---------------------------------------------------------------------------
# Step 1 — rasterise
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RasterPage:
    """One page of artwork as PNG bytes, and the size it was rendered at.

    ``width``/``height`` are the coordinate space every number from the model
    is interpreted in. They travel together with the bytes because a geometry
    measured against one size and applied against another is silently wrong in
    a way no validation catches.
    """

    png: bytes
    width: int
    height: int


#: PDFs start with this. Sniffed from the bytes rather than trusted from the
#: filename or the browser's Content-Type, both of which the client chooses.
_PDF_MAGIC = b"%PDF"


def rasterise(data: bytes, filename: str = "") -> RasterPage:
    """Render the first page of an upload to a PNG of bounded size."""
    if not data:
        raise TemplateImportError("That file is empty.")

    if data[:4] == _PDF_MAGIC:
        return _rasterise_pdf(data)
    return _rasterise_image(data, filename)


def _max_edge() -> int:
    return max(512, int(settings.TEMPLATE_IMPORT_RASTER_MAX_EDGE))


def _rasterise_pdf(data: bytes) -> RasterPage:
    """First page of a PDF, rendered at up to the configured longest edge.

    Only the first page. A template is one composition; a multi-page PDF is
    several, and quietly extracting page 1 of 12 while calling the result "the
    template" would be worse than saying so — which the caller does.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - depends on the installed wheel
        try:
            import fitz as pymupdf  # PyMuPDF < 1.24.3 only exposes this name.
        except ImportError as exc:
            logger.error("PyMuPDF is not installed; PDF import is unavailable.")
            raise TemplateImportError(
                "PDF import is not available on this server. Upload a PNG or "
                "JPG of the design instead."
            ) from exc

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise TemplateImportError("That PDF could not be opened.") from exc

    with document:
        if document.page_count == 0:
            raise TemplateImportError("That PDF has no pages.")

        page = document.load_page(0)
        box = page.rect
        if box.width <= 0 or box.height <= 0:
            raise TemplateImportError("That PDF's first page has no size.")

        # PDF units are points (72/inch). Scale so the longest edge lands on
        # the configured maximum: big enough that small type stays legible to
        # the model, bounded so a poster-sized page does not become a 200MB
        # bitmap.
        scale = _max_edge() / max(box.width, box.height)
        try:
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            png = pixmap.tobytes("png")
        except Exception as exc:
            raise TemplateImportError("That PDF's first page could not be rendered.") from exc

        return RasterPage(png=png, width=pixmap.width, height=pixmap.height)


def _rasterise_image(data: bytes, filename: str) -> RasterPage:
    """Normalise an uploaded image to RGB PNG, downscaled if oversized.

    Re-encoded rather than passed through. The upload may be a CMYK JPEG, a
    palette PNG or carry an EXIF orientation flag, and each of those reaches
    the cropper as a different coordinate space than the one the model
    measured against.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except UnidentifiedImageError as exc:
        raise TemplateImportError(
            "That file is not a PDF or an image this server can read. "
            "Upload a PDF, PNG, JPG or WebP."
        ) from exc
    except Exception as exc:
        raise TemplateImportError("That image could not be read.") from exc

    # Honour EXIF rotation before measuring anything: a phone photo of a flyer
    # reports portrait dimensions while storing landscape pixels.
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")

    limit = _max_edge()
    if max(image.size) > limit:
        image.thumbnail((limit, limit), Image.LANCZOS)

    if min(image.size) < 64:
        raise TemplateImportError(
            f"That image is too small to extract a layout from "
            f"({image.width}x{image.height}). Upload the design at full size."
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return RasterPage(png=buffer.getvalue(), width=image.width, height=image.height)


# ---------------------------------------------------------------------------
# Step 2 — extract
# ---------------------------------------------------------------------------

#: The document vocabulary the model may answer in. Deliberately the *design
#: editor's* element types rather than the template model's, because these are
#: the words that describe artwork ("this is a line", "this is a button").
#: ``_TEMPLATE_TYPE`` maps them onto storage below.
EXTRACTED_TYPES = (
    "text",
    "image",
    "shape",
    "line",
    "icon",
    "logo",
    "button",
    "background",
)

#: The bindable fields, offered to the model as a closed list. Asking for the
#: binding directly is far more reliable than inferring one from a free-text
#: role afterwards — "Starts at $895,000" is obviously the price to a model
#: reading the page, and is a regex guessing game to us.
BINDING_CHOICES = ("",) + tuple(PROPERTY_FIELDS_BY_NAME)

SYSTEM_PROMPT = (
    "You extract design templates from artwork into a structured element list "
    "for a canvas editor. You measure; you do not invent. Every number you "
    "return is a measurement against the image you were given."
)

USER_PROMPT = """\
Extract every visual element on this page into the required JSON structure.

COORDINATES
- The page is exactly {width} x {height} pixels. Report x, y, width and height
  in those pixels, measured from the top-left corner.
- Bounding boxes must be tight to the element's actual visible edges, not a
  rough estimate.
- z_index is the stacking order: 0 is the bottom-most element (usually the
  page background), higher numbers paint on top.

IMAGE ELEMENTS — READ THIS CAREFULLY
- Do NOT describe, summarise or recreate the visual content of any photograph.
  Leave "text" empty for them. Your only job for an image is its exact
  geometry and a short semantic "role".
- If a photo sits partly behind something else (a dark bar with text over it,
  an overlapping panel), report the photo's OWN full bounding box, and report
  the overlay and its text as separate elements on top.

TEXT ELEMENTS
- "text" is the literal wording on the page, transcribed exactly, with a
  newline between visual lines.
- font_size_px is the cap height to baseline-to-baseline size in page pixels.

BINDING — what this element should be filled from
- Set "binding" when an element holds a piece of property, agent or brokerage
  data that a different property would change: the price, the address, the bed
  or bath count, the agent's phone, the brokerage logo, a property photograph.
- The largest / most prominent photo is normally photo_1, with the remaining
  photos numbered in reading order.
- Leave "binding" empty ("") for anything that is part of the design rather
  than the data: headings like "Features:", decorative shapes, icons, rules,
  and background panels.

STYLE
- Colours are hex, like "#1F2937". Use "" where a colour does not apply.
- Report the colour you actually see, sampled from the artwork.

FILL TYPE — do NOT default to solid_color
- solid_color: one flat fill. Take the hex from the LARGEST continuous area of
  that colour, sampled at its CENTRE — never from an edge, a shadow, or a spot
  where something overlaps it.
- dot_pattern: a repeating grid of dots. Give dot_color, dot_radius_px,
  dot_spacing_x_px and dot_spacing_y_px so the grid can be redrawn. Do not
  flatten it into one solid rectangle, and do not report the dots as hundreds
  of separate elements.
- gradient: a fade. Set "gradient" to to_bottom or to_top and give
  background_color as the solid end of the fade.
- image_texture: a photographic or noisy fill.
- unsupported_pattern: anything you cannot describe with the above. Use it.

COLOUR SAMPLING
- Sample where nothing sits on top: no overlapping element, no shadow, no
  translucent layer above it. A panel that darkens towards its edges must be
  sampled from the flattest part of its middle, not from the top or bottom.
- If you are not confident of a colour, do NOT fall back to black or to any
  placeholder. Report your best hex, and note the uncertainty by choosing
  "unsupported_pattern" for the fill so a person reviews it.

SHAPE
- Do not assume everything is a rectangle. Set shape_type: "rounded_rect" with
  a border_radius_px, "ellipse" for circles and ovals, "blob" for organic or
  irregular edges — and for a blob, trace its outline into "mask".

Return every element you can see, including background panels and decorative
shapes. Do not merge two separate text blocks into one element.
"""


def _extraction_schema() -> dict:
    """The strict JSON schema the response must satisfy.

    Every property is listed in ``required`` and ``additionalProperties`` is
    false throughout, because the provider's strict mode demands it. The cost
    is that the model must emit "" and 0 for fields that do not apply, which
    the converters below treat as absent.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["page", "elements"],
        "properties": {
            "page": {
                "type": "object",
                "additionalProperties": False,
                "required": ["background_color", "suggested_name", "width", "height"],
                "properties": {
                    "width": {
                        "type": "number",
                        "description": "Canvas width in pixels — echo the size you were given.",
                    },
                    "height": {
                        "type": "number",
                        "description": "Canvas height in pixels — echo the size you were given.",
                    },
                    "background_color": {
                        "type": "string",
                        "description": "Hex colour of the page beneath everything.",
                    },
                    "suggested_name": {
                        "type": "string",
                        "description": "A short name for this template, from its headline.",
                    },
                },
            },
            "elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "id", "type", "role", "binding", "text", "mask", "transform", "style",
                    ],
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string", "enum": list(EXTRACTED_TYPES)},
                        "mask": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": (
                                "Only for a photo or shape whose visible edge is not "
                                "the full rectangle — an angled or chevron cut. The "
                                "outline of the visible shape as a flat list of page "
                                "pixel coordinates: x1, y1, x2, y2, ... Empty for "
                                "anything rectangular."
                            ),
                        },
                        "role": {
                            "type": "string",
                            "description": "Semantic label, e.g. hero_property_photo, price.",
                        },
                        "binding": {"type": "string", "enum": list(BINDING_CHOICES)},
                        "text": {
                            "type": "string",
                            "description": "Literal wording. Empty for non-text elements.",
                        },
                        "transform": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["x", "y", "width", "height", "rotation", "z_index"],
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "width": {"type": "number"},
                                "height": {"type": "number"},
                                "rotation": {"type": "number"},
                                "z_index": {"type": "integer"},
                            },
                        },
                        "style": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "color",
                                "background_color",
                                "font_size_px",
                                "font_weight",
                                "font_family",
                                "text_align",
                                "text_transform",
                                "line_height",
                                "opacity",
                                "border_radius_px",
                            ],
                            "properties": {
                                "color": {"type": "string"},
                                "background_color": {"type": "string"},
                                "font_size_px": {"type": "number"},
                                "font_weight": {
                                    "type": "string",
                                    "enum": ["300", "400", "500", "600", "700", "800", "900", ""],
                                },
                                "font_family": {
                                    "type": "string",
                                    "enum": ["body", "display", "serif", "mono", "script", ""],
                                    "description": (
                                        "'display' for a narrow/condensed headline face, "
                                        "'body' for normal-width text, 'serif' for a "
                                        "serif face, 'script' for flowing calligraphy or "
                                        "handwriting, 'mono' for monospaced. '' for "
                                        "non-text elements."
                                    ),
                                },
                                "text_align": {
                                    "type": "string",
                                    "enum": ["left", "center", "right", ""],
                                },
                                "text_transform": {
                                    "type": "string",
                                    "enum": ["none", "uppercase", "lowercase", "capitalize", ""],
                                },
                                "line_height": {"type": "number"},
                                "opacity": {"type": "number"},
                                "border_radius_px": {"type": "number"},
                                "border_width_px": {
                                    "type": "number",
                                    "description": (
                                        "Outline thickness in page pixels. A rule box "
                                        "around a strapline is an outline, not a filled "
                                        "shape — report 0 when there is no border."
                                    ),
                                },
                                "border_color": {"type": "string"},
                                "fill_type": {
                                    "type": "string",
                                    "enum": sorted(FILL_TYPES) + [""],
                                    "description": (
                                        "How the interior is filled. Do NOT default to "
                                        "solid_color. 'dot_pattern' for a repeating grid "
                                        "of dots, 'gradient' for a fade, 'image_texture' "
                                        "for photographic or noisy fill, and "
                                        "'unsupported_pattern' when it is none of these "
                                        "— guessing a flat colour for a patterned area "
                                        "is worse than saying you could not tell."
                                    ),
                                },
                                "shape_type": {
                                    "type": "string",
                                    "enum": sorted(SHAPE_TYPES) + [""],
                                    "description": (
                                        "Do not assume rectangle. 'rounded_rect' with a "
                                        "border_radius_px, 'ellipse' for a circle or "
                                        "oval, 'blob' for organic or irregular edges "
                                        "(give its outline in `mask`)."
                                    ),
                                },
                                "dot_color": {"type": "string"},
                                "dot_radius_px": {"type": "number"},
                                "dot_spacing_x_px": {
                                    "type": "number",
                                    "description": "Centre-to-centre gap between columns of dots.",
                                },
                                "dot_spacing_y_px": {
                                    "type": "number",
                                    "description": "Centre-to-centre gap between rows of dots.",
                                },
                                "gradient": {
                                    "type": "string",
                                    "enum": ["", "to_bottom", "to_top"],
                                    "description": (
                                        "Set on a panel that fades from transparent into "
                                        "its background_color rather than being flat — "
                                        "the wash a hero photo dissolves into. "
                                        "'to_bottom' means opaque at the bottom."
                                    ),
                                },
                            },
                        },
                    },
                },
            },
        },
    }


def extract_layout(page: RasterPage) -> CompletionResult:
    """Ask the vision model to measure the page. Costs money; may fail."""
    try:
        return complete_json(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": USER_PROMPT.format(
                                width=page.width, height=page.height
                            ),
                        },
                        image_part(page.png),
                    ],
                },
            ],
            schema=_extraction_schema(),
            schema_name="template_layout",
            model=settings.OPENAI_VISION_MODEL,
            # Measurement, not composition. Sampling variety here just means
            # the same flyer extracts to different geometry each attempt.
            temperature=0.0,
            max_output_tokens=settings.TEMPLATE_IMPORT_MAX_OUTPUT_TOKENS,
            timeout=settings.TEMPLATE_IMPORT_TIMEOUT_SECONDS,
        )
    except AIConfigurationError as exc:
        raise TemplateImportError(str(exc)) from exc
    except AIGenerationError as exc:
        raise TemplateImportError(
            "The design could not be analysed just now. Try importing it again."
        ) from exc


# ---------------------------------------------------------------------------
# Step 2b — tidy what came back
# ---------------------------------------------------------------------------
#
# Both readers measure each element on its own, and neither can see intent. A
# designer aligned two panels; the extractor reports them four pixels apart.
# That difference is invisible at source scale and obvious once the template is
# re-rendered at another size, because the error scales with everything else.

#: How far apart two edges may be and still be called the same edge, as a
#: fraction of the page's shorter side. Half a percent: a designer working with
#: snapping produces exact matches, so anything under this is manual-placement
#: slop rather than a decision. A floor keeps it sane on tiny canvases.
_SNAP_RATIO, _SNAP_FLOOR_PX = 0.005, 3.0

#: A gap smaller than this, as a fraction of the shorter side, reads as "these
#: belong together" — an icon and its label, a logo and its tagline.
_GROUP_GAP_RATIO = 0.02

#: How much two boxes must overlap on the perpendicular axis before adjacency
#: means anything. Two things side by side are related; two things at opposite
#: ends of the page that happen to be close in one axis are not.
_GROUP_OVERLAP = 0.5

#: What can be *in* a group. Panels, grounds and rules are deliberately absent.
#:
#: They are containers: a panel touches everything sitting on it, so including
#: them chains every neighbour to every other neighbour through the thing they
#: happen to sit on. The first version of this did include them and produced
#: one group of forty-two elements — technically a connected component, and a
#: useless answer. A group is an icon and its label, a logo and its tagline:
#: content that reads as one thing.
_GROUPABLE_TYPES = frozenset({"text", "image", "icon", "logo"})

#: Past this a "group" is a region of the page, not a thing you would move
#: together. Oversized components are dropped rather than labelled, because a
#: wrong group is worse than no group — it makes the editor move elements the
#: user did not mean to touch.
_GROUP_MAX_MEMBERS = 6


def _snap_axis(elements: list[dict], pos: str, size: str, tolerance: float) -> None:
    """Pull near-identical edges and centres onto one value, in place.

    Three anchors per axis — leading edge, centre, trailing edge — because a
    row of centred captions under photos is as deliberate an alignment as a
    column of left-aligned text, and only one of those shows up in `x`.

    Anchors are applied in priority order and an element is settled by the
    first one that has anything to say about it. That ordering is what makes
    the guarantee hold: two boxes whose leading edges are within tolerance are
    *both* settled by the leading edge, so they come out identical. Letting
    each element pick whichever anchor moved it least felt more careful and
    was worse — the two would choose different anchors and land a pixel apart,
    which is the exact thing this is here to remove.

    Leading edge first because a column of left-aligned text is the commonest
    alignment there is; centres next, for a row of captions under photos;
    trailing edges last. Boxes of different widths cannot satisfy two of those
    at once, so one has to win.
    """

    def anchors(element: dict) -> dict[str, float]:
        start = float(element["transform"][pos])
        extent = float(element["transform"][size])
        return {"start": start, "center": start + extent / 2, "end": start + extent}

    original = {id(element): anchors(element) for element in elements}
    settled: set[int] = set()

    for anchor in ("start", "center", "end"):
        # Cluster this anchor's values. Only runs of two or more mean anything:
        # a lone value has nothing to be aligned *with*.
        values = sorted((original[id(e)][anchor], id(e)) for e in elements)
        clusters: list[list[tuple[float, int]]] = []
        for value, marker in values:
            if clusters and value - clusters[-1][0][0] <= tolerance:
                clusters[-1].append((value, marker))
            else:
                clusters.append([(value, marker)])

        for cluster in clusters:
            if len(cluster) < 2:
                continue
            shared = sum(value for value, _ in cluster) / len(cluster)
            for value, marker in cluster:
                if marker in settled:
                    continue
                element = next(e for e in elements if id(e) == marker)
                shift = shared - value
                if shift:
                    element["transform"][pos] = round(
                        float(element["transform"][pos]) + shift, 2
                    )
                settled.add(marker)


def align_and_group(payload: dict, width: int, height: int) -> dict:
    """Snap near-alignments and label visual groups. Returns the payload.

    Runs on whatever either reader produced, so the vision model and the PDF
    reader are tidied by the same rules rather than each having its own idea of
    what "aligned" means.
    """
    elements = [
        element
        for element in payload.get("elements", [])
        if isinstance(element.get("transform"), dict)
    ]
    if len(elements) < 2:
        return payload

    short_side = max(1.0, min(width, height))
    tolerance = max(_SNAP_FLOOR_PX, short_side * _SNAP_RATIO)

    _snap_axis(elements, "x", "width", tolerance)
    _snap_axis(elements, "y", "height", tolerance)

    _assign_groups(elements, short_side, width * height)
    return payload


def _assign_groups(elements: list[dict], short_side: float, page_area: float) -> None:
    """Label elements that read as one thing, in place.

    Adjacency plus overlap: two boxes are related when the gap between them is
    small *and* they line up on the other axis. That is what separates an icon
    from its label — side by side, sharing a middle — from two unrelated things
    that happen to be near each other in one direction only.

    Backgrounds and large panels are excluded. They touch everything, so
    including them would collapse the whole page into a single group and make
    the label useless.
    """

    def box(element: dict) -> tuple[float, float, float, float]:
        transform = element["transform"]
        x, y = float(transform["x"]), float(transform["y"])
        return x, y, x + float(transform["width"]), y + float(transform["height"])

    joinable = [
        element for element in elements if element.get("type") in _GROUPABLE_TYPES
    ]
    if len(joinable) < 2:
        return

    gap = short_side * _GROUP_GAP_RATIO
    parent = {id(element): id(element) for element in joinable}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[a] = b

    def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
        shared = min(a1, b1) - max(a0, b0)
        shortest = max(1e-6, min(a1 - a0, b1 - b0))
        return shared / shortest

    for index, first in enumerate(joinable):
        fx0, fy0, fx1, fy1 = box(first)
        for second in joinable[index + 1 :]:
            sx0, sy0, sx1, sy1 = box(second)
            side_by_side = (
                max(sx0 - fx1, fx0 - sx1) <= gap
                and overlap(fy0, fy1, sy0, sy1) >= _GROUP_OVERLAP
            )
            stacked = (
                max(sy0 - fy1, fy0 - sy1) <= gap
                and overlap(fx0, fx1, sx0, sx1) >= _GROUP_OVERLAP
            )
            if side_by_side or stacked:
                union(id(first), id(second))

    members: dict[int, list[dict]] = defaultdict(list)
    for element in joinable:
        members[find(id(element))].append(element)

    label = 0
    for group in members.values():
        # A group of one is just an element; a group of twenty is a region of
        # the page. Neither is worth a label, and the large one is actively
        # harmful — the editor would move things the user never selected.
        if not 2 <= len(group) <= _GROUP_MAX_MEMBERS:
            continue
        label += 1
        for element in group:
            element.setdefault("style", {})["group_id"] = f"group_{label}"


def extract_page(data: bytes, page: RasterPage) -> CompletionResult:
    """Read the page's layout, the cheapest accurate way available.

    A PDF exported from a design tool already contains its own layout: the
    strings, boxes, sizes and colours are all in the content stream. Reading
    them is exact, instant, free, and needs no API key — so that is tried
    first, and the vision model is what handles a scan, a JPG, or a PDF whose
    text has been converted to outlines.

    Both paths return the same payload shape, so nothing downstream changes.
    A structural read reports no tokens because none were spent.
    """
    if data[:4] == _PDF_MAGIC and is_text_pdf(data):
        try:
            payload = extract_pdf_layout(data, page.width, page.height)
        except Exception:
            # Never fatal: a PDF this cannot parse is exactly what the model is
            # for, and falling through costs an API call rather than the import.
            logger.warning("Structural PDF read failed; falling back to vision", exc_info=True)
        else:
            return CompletionResult(
                payload=align_and_group(payload, page.width, page.height),
                raw_text="",
                model="pdf-structure",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                duration_ms=0,
            )

    result = extract_layout(page)
    # The model measures each element independently too, so it gets the same
    # tidy-up rather than a second, differently-behaved one.
    return replace(result, payload=align_and_group(result.payload, page.width, page.height))


# ---------------------------------------------------------------------------
# Step 3 — normalise what came back
# ---------------------------------------------------------------------------

#: Extracted type -> how the template stores it.
#:
#: ``icon`` becomes a STATIC_GRAPHIC rather than an IMAGE because an icon is
#: part of the design, not a slot for somebody's photo — it is baked from the
#: crop and nothing ever rebinds it. ``background`` is decided per element:
#: a photographic background is an image, a flat one is a colour block.
_TEMPLATE_TYPE: dict[str, str] = {
    "text": ElementType.TEXT,
    "image": ElementType.IMAGE,
    "shape": ElementType.COLOR_BLOCK,
    "line": ElementType.DIVIDER,
    "icon": ElementType.STATIC_GRAPHIC,
    "logo": ElementType.LOGO,
    "button": ElementType.BADGE,
    "background": ElementType.COLOR_BLOCK,
}

#: Extracted types whose pixels are worth cutting out of the raster. Everything
#: else is reproduced from geometry and style, which is both sharper and
#: editable — baking a crop of a text block would give the user a picture of
#: words they cannot retype.
#:
#: ``logo`` is deliberately absent, and it is the one exclusion that is not
#: about fidelity. Every other baked crop is a cosmetic stand-in that a real
#: listing replaces; a logo is an assertion about *who published this*. Baking
#: one would mean an imported design exports carrying whatever brand was on the
#: source artwork — and, because readiness treats a stored image as present,
#: it would sail past the very gate that exists to stop an asset going out
#: without the agent's own brokerage on it. So the slot stays empty, the
#: binding to `brokerage.logo` fills it, and readiness says so until it does.
_CROPPED_TYPES = frozenset({"image", "icon", "background"})

#: Below this, a crop is a smudge rather than an asset. Icons in a feature row
#: are routinely 40-60px, so the floor is low.
_MIN_CROP_PX = 12

#: Crops are capped well under MAX_IMAGE_UPLOAD_BYTES so the stored asset never
#: trips the validator that guards every other image in the system.
_MAX_CROP_EDGE = 1400


@dataclass
class ExtractedElement:
    """One element, converted into the template's own coordinate space."""

    key: str
    label: str
    element_type: str
    geometry: dict
    style_properties: dict
    content_source: str
    default_content: str
    z_index: int
    #: Pixel box on the raster, kept so the asset can be cropped after the fact.
    crop_box: tuple[int, int, int, int] | None = None
    #: Outline of the element's *visible* shape, in page pixels, when it is not
    #: the whole rectangle. Empty means rectangular.
    #:
    #: Magazine-style property layouts routinely cut photos to angled or
    #: chevron edges, and neighbouring photos interlock along them. A bounding
    #: box therefore captures wedges of whatever sits beside it, and the
    #: extracted "photo" arrives with a slice of its neighbour in the corner.
    #:
    #: This is converted into a ``clip_polygon`` style — CSS on the element —
    #: rather than burned into the crop's alpha channel. The crop keeps the
    #: stray wedges and the clip hides them, which composes identically *and*
    #: keeps the shape when the agent drops their own photograph into the slot.
    #: An alpha mask would be thrown away with the pixels it was painted on.
    mask: list[tuple[float, float]] = field(default_factory=list)
    asset: ContentFile | None = field(default=None, repr=False)


def _clamp(value, low: float, high: float, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return max(low, min(high, number))


def _colour(value) -> str:
    """A hex colour, or "" if the model returned anything else.

    Dropped rather than defaulted. A wrong colour is invisible in a diff and
    obvious only once the design is exported; an absent one shows the
    element's own default, which is at least a state the user can recognise
    and fix.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text if HEX_COLOR.match(text) else ""


def _slug_key(role: str, index: int) -> str:
    """A stable, unique element key from the model's role label."""
    base = slugify(role or "").replace("-", "_")[:60] or "element"
    return f"{base}_{index}"


def normalise_elements(payload: dict, page: RasterPage) -> list[ExtractedElement]:
    """Convert the model's pixel measurements into template elements.

    Nothing here raises on a bad element: it is skipped. One unusable object
    in a response of forty is not a reason to throw away the other thirty-nine
    and charge the user for another attempt.
    """
    raw_elements = payload.get("elements")
    if not isinstance(raw_elements, list) or not raw_elements:
        raise TemplateImportError(
            "No elements could be found on that page. If it is a scan or a "
            "photograph, try a higher-resolution version."
        )

    scale_reference = float(min(page.width, page.height))
    elements: list[ExtractedElement] = []
    used_keys: set[str] = set()

    for index, raw in enumerate(raw_elements):
        if not isinstance(raw, dict):
            continue

        kind = raw.get("type")
        if kind not in EXTRACTED_TYPES:
            continue

        transform = raw.get("transform")
        if not isinstance(transform, dict):
            continue

        # Pixels first, because the crop box needs them, then fractions.
        x_px = _clamp(transform.get("x"), -page.width, page.width * 2)
        y_px = _clamp(transform.get("y"), -page.height, page.height * 2)
        w_px = _clamp(transform.get("width"), 0, page.width * 2)
        h_px = _clamp(transform.get("height"), 0, page.height * 2)
        if w_px <= 0 or h_px <= 0:
            continue

        role = str(raw.get("role") or "").strip()
        key = _slug_key(role, index)
        if key in used_keys:  # pragma: no cover - _slug_key suffixes with index
            key = f"{key}_{len(used_keys)}"
        used_keys.add(key)

        raw_style = raw.get("style") if isinstance(raw.get("style"), dict) else {}
        binding = raw.get("binding") if raw.get("binding") in BINDING_CHOICES else ""

        # A background is only an image if the model called it one by giving it
        # a photo binding; otherwise it is the page's flat colour.
        element_type = _TEMPLATE_TYPE[kind]
        if kind == "background" and binding:
            element_type = ElementType.IMAGE

        style = _style_for(kind, raw_style, scale_reference)
        content_source = ""
        field_spec = PROPERTY_FIELDS_BY_NAME.get(binding) if binding else None
        if field_spec is not None:
            content_source = field_spec.path
            if field_spec.format:
                style["format"] = field_spec.format

        # A logo with no explicit binding still means the brokerage's logo —
        # that is what the word denotes on a property flyer.
        if kind == "logo" and not content_source:
            content_source = PROPERTY_FIELDS_BY_NAME["brokerage_logo"].path

        # The outline is read for every type, not only the cropped ones: an
        # angled colour panel is as common in these layouts as an angled photo,
        # and it needs the clip without needing any pixels.
        mask = _mask_points(raw.get("mask"))
        clip = _clip_polygon(mask, x_px, y_px, w_px, h_px)
        if clip:
            style["clip_polygon"] = clip

        # Crop from what the element *became*, not what it was called.
        #
        # A flat page background resolves to a COLOR_BLOCK a dozen lines up,
        # and cropping one anyway bakes a picture of the entire flyer — every
        # heading, price and photo on it — and parks it behind the editable
        # layout. The canvas then shows each text twice: once as pixels nobody
        # can retype, once as the real element. The prompt asks the model to
        # report background panels, so this is the common case on any artwork
        # with a plain ground, not an edge case.
        crop_box = (
            _crop_box(x_px, y_px, w_px, h_px, page)
            if kind in _CROPPED_TYPES and element_type != ElementType.COLOR_BLOCK
            else None
        )

        elements.append(
            ExtractedElement(
                key=key,
                label=(role.replace("_", " ").strip().title() or f"Element {index + 1}")[:120],
                element_type=element_type,
                geometry={
                    "x": round(x_px / page.width, 4),
                    "y": round(y_px / page.height, 4),
                    "width": round(w_px / page.width, 4),
                    "height": round(h_px / page.height, 4),
                    "rotation": round(_clamp(transform.get("rotation"), -360, 360), 2),
                },
                style_properties=style,
                content_source=content_source,
                # Images carry no literal content — see the module docstring.
                default_content=(
                    _text_of(raw) if element_type in _TEXT_ELEMENT_TYPES else ""
                ),
                z_index=int(_clamp(transform.get("z_index"), 0, 999, default=index)),
                crop_box=crop_box,
                mask=mask,
            )
        )

    if not elements:
        raise TemplateImportError(
            "Nothing usable could be extracted from that page. Try a "
            "higher-resolution version, or a PNG export of the design."
        )
    return elements


#: Template types that display words. A BADGE is a filled shape with a label
#: inside it, so it carries text too.
_TEXT_ELEMENT_TYPES = frozenset({ElementType.TEXT, ElementType.BADGE})

#: The longest literal string worth keeping as default content. Well past a
#: flyer's description paragraph; short of a model that has started
#: hallucinating the page's entire contents into one element.
_MAX_DEFAULT_CONTENT = 2000


def _text_of(raw: dict) -> str:
    text = raw.get("text")
    if not isinstance(text, str):
        return ""
    return text.strip()[:_MAX_DEFAULT_CONTENT]


def _style_for(kind: str, raw: dict, scale_reference: float) -> dict:
    """Style properties, converted out of pixels and into ratios.

    Font size is stored as a fraction of the canvas's *smaller* side, matching
    ``html_builder``'s type scale — which is what keeps type inside its box
    when the same template is rendered square, tall and wide.
    """
    style: dict = {}

    colour = _colour(raw.get("color"))
    background = _colour(raw.get("background_color"))

    if kind in ("text", "button"):
        if colour:
            style["color"] = colour
        font_px = _clamp(raw.get("font_size_px"), 0, scale_reference)
        if font_px > 0:
            # The same bounds document.NUMERIC_STYLE_RANGES enforces, applied
            # here so a template element cannot be authored into a state the
            # design validator would later refuse.
            style["font_size_ratio"] = round(
                _clamp(font_px / scale_reference, 0.002, 0.6, default=0.03), 4
            )
        weight = str(raw.get("font_weight") or "")
        if weight in {"300", "400", "500", "600", "700", "800", "900"}:
            style["font_weight"] = weight
        family = str(raw.get("font_family") or "")
        if family in FONT_FAMILIES:
            style["font_family"] = family
        align = str(raw.get("text_align") or "")
        if align in {"left", "center", "right"}:
            style["text_align"] = align
        transform_case = str(raw.get("text_transform") or "")
        if transform_case in {"none", "uppercase", "lowercase", "capitalize"}:
            style["text_transform"] = transform_case
        line_height = _clamp(raw.get("line_height"), 0, 4)
        if line_height >= 0.5:
            style["line_height"] = round(line_height, 2)
        # Text is measured from its own visible edges, so vertical centring is
        # what puts it back where it was seen.
        style["vertical_align"] = "center"

    if kind in ("shape", "line", "button", "background") and background:
        style["background_color"] = background

    if kind in ("image", "icon", "logo", "background"):
        # Icons and logos are shapes with air around them and must not be
        # cropped to fill; photographs are placed to fill their frame.
        style["object_fit"] = "contain" if kind in ("icon", "logo") else "cover"
        style["object_position"] = "center center"

    opacity = _clamp(raw.get("opacity"), 0, 1, default=1.0)
    if opacity < 1.0:
        style["opacity"] = round(opacity, 2)

    radius_px = _clamp(raw.get("border_radius_px"), 0, scale_reference)
    if radius_px > 0:
        style["border_radius_ratio"] = round(
            _clamp(radius_px / scale_reference, 0.0, 0.5), 4
        )

    # An outlined box — a rule around a strapline — is a shape whose whole
    # visual identity is its border. Extracted as a filled shape it arrives as
    # a solid slab; extracted with no border at all it arrives as bare text
    # floating where a framed line used to be.
    border_px = _clamp(raw.get("border_width_px"), 0, scale_reference)
    if border_px > 0:
        style["border_width_ratio"] = round(
            _clamp(border_px / scale_reference, 0.0, 0.1), 4
        )
        style["border_style"] = "solid"
        border_colour = _colour(raw.get("border_color")) or colour
        if border_colour:
            style["border_color"] = border_colour

    # WHAT KIND OF FILL THIS IS, recorded rather than assumed.
    #
    # Defaulting everything to a solid colour is the failure this guards
    # against: a dotted ground flattened to one hex, or a gradient sampled at
    # its midpoint, comes back as a colour that appears nowhere on the page.
    # An unrecognised fill is reported as `unsupported_pattern` — an honest
    # "a human should look at this" rather than a plausible wrong answer.
    fill_type = str(raw.get("fill_type") or "")
    if fill_type in FILL_TYPES:
        style["fill_type"] = fill_type

    shape_type = str(raw.get("shape_type") or "")
    if shape_type in SHAPE_TYPES:
        style["shape_type"] = shape_type

    if fill_type == "dot_pattern":
        dot_colour = _colour(raw.get("dot_color"))
        radius_px = _clamp(raw.get("dot_radius_px"), 0, scale_reference)
        gap_x = _clamp(raw.get("dot_spacing_x_px"), 0, scale_reference)
        gap_y = _clamp(raw.get("dot_spacing_y_px"), 0, scale_reference)
        if dot_colour and radius_px > 0 and gap_x > 0 and gap_y > 0:
            style["dot_color"] = dot_colour
            style["dot_radius_ratio"] = round(
                _clamp(radius_px / scale_reference, 0.0002, 0.1), 5
            )
            style["dot_spacing_x_ratio"] = round(
                _clamp(gap_x / scale_reference, 0.001, 0.5), 5
            )
            style["dot_spacing_y_ratio"] = round(
                _clamp(gap_y / scale_reference, 0.001, 0.5), 5
            )
            # The dots are the fill. A flat colour underneath them would be the
            # very flattening this branch exists to avoid.
            style.pop("background_color", None)
        else:
            # Told it was a pattern but not given enough to rebuild one. Saying
            # so beats drawing a solid rectangle and calling it the design.
            style["fill_type"] = "unsupported_pattern"

    # A wash, not a fill: the band where a hero photograph dissolves into the
    # panel below it. Built here from a direction and the element's own colour
    # rather than accepting a CSS string, for the same reason clip_polygon is
    # built from numbers — `background-image` is a place a `url(...)` could be
    # smuggled into the renderer. document.GRADIENT_RE re-checks the result.
    direction = str(raw.get("gradient") or "")
    if direction in ("to_bottom", "to_top") and background:
        stops = _rgb_stops(background)
        style["background_gradient"] = (
            f"linear-gradient({'180deg' if direction == 'to_bottom' else '0deg'}, "
            f"{stops[0]} 0%, {stops[1]} 100%)"
        )
        # The gradient supplies the colour; leaving the flat fill underneath
        # would make the transparent end opaque anyway.
        style.pop("background_color", None)

    return style


def _rgb_stops(hex_colour: str) -> tuple[str, str]:
    """``#784E2A`` -> a transparent and an opaque stop of the same colour."""
    value = hex_colour.lstrip("#")
    red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({red},{green},{blue},0)", f"rgba({red},{green},{blue},1)"


#: A shape needs at least a triangle, and past a few dozen vertices it is
#: tracing noise rather than describing a cut edge.
_MIN_MASK_POINTS, _MAX_MASK_POINTS = 3, 64


def _mask_points(raw) -> list[tuple[float, float]]:
    """A flat ``[x1, y1, x2, y2, ...]`` list as usable (x, y) pairs.

    Flat because the strict schema expresses "array of numbers" cleanly and
    "array of two-element arrays" badly. Anything malformed yields no mask at
    all rather than a partial one: half an outline would punch a hole through
    the middle of a photo, which is far worse than the square edge it replaces.
    """
    if not isinstance(raw, list) or len(raw) < _MIN_MASK_POINTS * 2:
        return []
    if len(raw) % 2:
        return []

    points: list[tuple[float, float]] = []
    for index in range(0, min(len(raw), _MAX_MASK_POINTS * 2), 2):
        x, y = raw[index], raw[index + 1]
        if isinstance(x, bool) or isinstance(y, bool):
            return []
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return []
        points.append((float(x), float(y)))
    return points if len(points) >= _MIN_MASK_POINTS else []


def _crop_box(x, y, w, h, page: RasterPage) -> tuple[int, int, int, int] | None:
    """The element's box, clipped to the page. None if too small to be useful.

    Clipped rather than rejected: a hero photo that bleeds off the edge is a
    normal composition, and the visible part of it is exactly what should be
    stored.
    """
    left = max(0, int(round(x)))
    top = max(0, int(round(y)))
    right = min(page.width, int(round(x + w)))
    bottom = min(page.height, int(round(y + h)))
    if right - left < _MIN_CROP_PX or bottom - top < _MIN_CROP_PX:
        return None
    return (left, top, right, bottom)


# ---------------------------------------------------------------------------
# Step 3b — bake the crops
# ---------------------------------------------------------------------------


def bake_assets(elements: list[ExtractedElement], page: RasterPage) -> int:
    """Cut each image element's own pixels out of the raster.

    This is what makes an imported template *look* like the artwork it came
    from rather than a wireframe of labelled boxes. For elements that also
    carry a binding, the crop is a fallback: attaching a listing replaces it
    with the agent's real photo (see ``html_builder.resolve_content``).

    Failures are per-element and non-fatal. One unreadable region should cost
    that element its picture, not cost the user the whole import.
    """
    from PIL import Image

    with Image.open(io.BytesIO(page.png)) as source:
        source.load()
        baked = 0
        for element in elements:
            if element.crop_box is None:
                continue
            try:
                crop = source.crop(element.crop_box).convert("RGB")
                if max(crop.size) > _MAX_CROP_EDGE:
                    crop.thumbnail((_MAX_CROP_EDGE, _MAX_CROP_EDGE), Image.LANCZOS)
                buffer = io.BytesIO()
                crop.save(buffer, format="PNG", optimize=True)
            except Exception:
                logger.warning(
                    "Could not crop %r from the source page", element.key, exc_info=True
                )
                continue
            element.asset = ContentFile(buffer.getvalue(), name=f"{element.key}.png")
            baked += 1
    return baked


def _clip_polygon(
    mask: list[tuple[float, float]], x: float, y: float, w: float, h: float
) -> list[float]:
    """An outline in page pixels -> percentages of this element's own box.

    The outline is measured against the page; the style is applied to the
    element. Everything else about an element's geometry is a fraction of its
    box, and a shape left in page pixels would stop matching its element the
    moment the design was rendered at another size.

    Returned flat (``x1, y1, x2, y2, ...``) because that is the shape
    ``document._validate_clip_polygon`` accepts and the only one that survives
    the strict response schema cleanly.
    """
    if not mask or w <= 0 or h <= 0:
        return []
    flat: list[float] = []
    for point_x, point_y in mask:
        flat.append(round((point_x - x) / w * 100.0, 3))
        flat.append(round((point_y - y) / h * 100.0, 3))
    return flat


# ---------------------------------------------------------------------------
# Step 4 — build the template
# ---------------------------------------------------------------------------

#: How far apart two aspect ratios may be before the match is not worth making.
#: 0.12 puts a 3:4 flyer nearer the A4 format than the square one, and leaves
#: genuinely odd shapes falling back to the default rather than being forced
#: into a format that would crop them.
_ASPECT_TOLERANCE = 0.12


def closest_dimension(width: int, height: int) -> str:
    """The supported format whose shape is nearest this page's.

    A layout drawn tall and opened square reads as a crop, so the format a
    template opens at is part of extracting it correctly — not a detail to
    default and let the user discover.
    """
    aspect = width / height if height else 1.0
    best_key, best_gap = "instagram_post", float("inf")
    for key, dimension in SOCIAL_DIMENSIONS.items():
        gap = abs(dimension.aspect - aspect)
        if gap < best_gap:
            best_key, best_gap = key, gap
    return best_key if best_gap <= _ASPECT_TOLERANCE else "instagram_post"


def _unique_slug(name: str) -> str:
    """A slug that is unique across the table.

    Suffixed with random hex rather than a counter: two agents importing
    "Modern Flyer" at the same moment would both read the same highest counter
    and one of them would lose to the unique constraint.
    """
    base = slugify(name)[:140] or "imported-template"
    for _ in range(5):
        candidate = f"{base}-{uuid.uuid4().hex[:6]}"
        if not Template.objects.filter(slug=candidate).exists():
            return candidate
    return f"imported-{uuid.uuid4().hex[:12]}"  # pragma: no cover - vanishingly rare


_WHITESPACE = re.compile(r"\s+")


def _template_name(requested: str, payload: dict, fallback: str) -> str:
    for candidate in (requested, payload.get("page", {}).get("suggested_name"), fallback):
        if isinstance(candidate, str) and candidate.strip():
            return _WHITESPACE.sub(" ", candidate.strip())[:160]
    return "Imported template"


@transaction.atomic
def build_template(
    *,
    owner,
    name: str,
    category: str,
    style: str,
    page: RasterPage,
    elements: list[ExtractedElement],
    payload: dict,
    description: str = "",
) -> Template:
    """Persist the extraction as a Template the editor can open.

    One transaction: a template that exists with half its elements would show
    up in the gallery as a usable design and open as a broken one.
    """
    background = _colour(payload.get("page", {}).get("background_color")) or "#FFFFFF"

    template = Template.objects.create(
        owner=owner,
        name=name,
        slug=_unique_slug(name),
        description=description,
        category=category,
        style=style,
        layout_definition={
            "background_color": background,
            # Kept so a later re-extraction, or anyone debugging geometry, knows
            # the coordinate space these fractions were measured in.
            "source_width": page.width,
            "source_height": page.height,
        },
        default_dimension=closest_dimension(page.width, page.height),
        allows_added_elements=True,
        is_active=True,
    )
    template.source_image.save(
        f"{template.slug}.png", ContentFile(page.png), save=True
    )

    for element in elements:
        row = TemplateElement(
            template=template,
            key=element.key,
            label=element.label,
            element_type=element.element_type,
            geometry=element.geometry,
            style_properties=element.style_properties,
            content_source=element.content_source,
            default_content=element.default_content,
            z_index=element.z_index,
        )
        if element.asset is not None:
            row.static_asset.save(element.asset.name, element.asset, save=False)
        row.save()

    return template


# ---------------------------------------------------------------------------
# The orchestrator
# ---------------------------------------------------------------------------


def run_import(job) -> Template:
    """Run one ``TemplateImport`` end to end.

    Mirrors ``ai_content.services.run_generation``: it records its own
    outcome onto the job row and raises ``TemplateImportError`` with a message
    written to be read by the user. The Celery task around it adds queueing
    and nothing else.
    """
    from django.utils import timezone

    from apps.templates.models import ImportStatus

    job.status = ImportStatus.RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at", "updated_at"])

    try:
        with job.source_file.open("rb") as handle:
            data = handle.read()
    except Exception as exc:
        raise TemplateImportError("The uploaded file could not be read back.") from exc

    page = rasterise(data, job.original_filename)
    result = extract_page(data, page)

    elements = normalise_elements(result.payload, page)
    baked = bake_assets(elements, page)

    template = build_template(
        owner=job.agent,
        name=_template_name(job.requested_name, result.payload, job.original_filename),
        category=job.category,
        style=job.style,
        page=page,
        elements=elements,
        payload=result.payload,
        description=(
            f"Imported from {job.original_filename or 'uploaded artwork'}. "
            f"{len(elements)} elements, {baked} with artwork extracted from the "
            f"page. Every element is editable — attach a listing to fill the "
            f"photos and details with a real property."
        ),
    )

    job.template = template
    job.status = ImportStatus.SUCCEEDED
    job.element_count = len(elements)
    job.model_used = result.model
    job.prompt_tokens = result.prompt_tokens
    job.completion_tokens = result.completion_tokens
    job.duration_ms = result.duration_ms
    job.error = ""
    job.finished_at = timezone.now()
    job.save(
        update_fields=[
            "template",
            "status",
            "element_count",
            "model_used",
            "prompt_tokens",
            "completion_tokens",
            "duration_ms",
            "error",
            "finished_at",
            "updated_at",
        ]
    )
    logger.info(
        "Template import %s produced template %s (%s elements, %s baked, %sms)",
        job.pk,
        template.pk,
        len(elements),
        baked,
        result.duration_ms,
    )
    return template
