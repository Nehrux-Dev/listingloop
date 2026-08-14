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

from dataclasses import dataclass, field

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
from apps.templates.document import FONT_FAMILIES, HEX_COLOR, PROPERTY_FIELDS_BY_NAME
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
                "required": ["background_color", "suggested_name"],
                "properties": {
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
                                    "enum": ["body", "display", "serif", "mono", ""],
                                    "description": (
                                        "'display' for a narrow/condensed headline face, "
                                        "'body' for normal-width text, 'serif' for a "
                                        "serif face, 'mono' for monospaced. '' for "
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

        crop_box = _crop_box(x_px, y_px, w_px, h_px, page) if kind in _CROPPED_TYPES else None

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

    return style


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
    result = extract_layout(page)

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
