"""Render an extracted layout back to a raster and score it against the source.

WHY THIS EXISTS
------------------------------------------------------------------------------
Extraction measures each element on its own and never checks the whole against
the page it came from. This closes that loop: it rebuilds the editable layout
as HTML, screenshots it through the same renderer an export uses, and compares
the result to the original upload. A low score is surfaced as an import warning
so the person who chose the file can look before publishing it.

WHAT IT DELIBERATELY DOES NOT DO
------------------------------------------------------------------------------
It does not touch geometry. The scoring is diagnostic only — the honest reading
of "does the reconstruction look like the source". The one consumer that *acts*
on a result is ``importing._autocorrect_offsets``, and even that is gated on
this module scoring the corrected layout strictly better than the original:
auto-correcting from a pixel diff can just as easily move a correct element as
fix a wrong one, so a correction only survives when the whole page agrees it
helped. The scoring itself stays a pure measurement either way.

COST
------------------------------------------------------------------------------
It renders through the Chromium service, so it makes the import worker depend on
the renderer being up. That is why it is off by default (``TEMPLATE_IMPORT_VALIDATE``)
and skipped for text PDFs — a structural read is exact and has nothing to check —
and why a renderer outage here is logged and swallowed rather than failing an
import that otherwise succeeded.

The compare itself is pure NumPy/Pillow and has no browser dependency, so the
scoring is unit-tested by handing it two images directly; only the thin
``render_layout`` wrapper needs the service.
"""

from __future__ import annotations

import html as html_lib
import io
import logging
from dataclasses import dataclass, field

import requests
from django.conf import settings

from apps.templates.dimensions import Dimension
from apps.templates.document import TYPE_FROM_TEMPLATE
from apps.templates.html_builder import element_html
from apps.templates.models import ElementType

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """The outcome of one render-and-compare pass."""

    #: 0..1, where 1 is pixel-identical. Rounded for display and storage.
    score: float
    #: Per-element observations, worst first. Diagnostic, never acted on here.
    issues: list[dict] = field(default_factory=list)
    #: The rendered preview, as PNG bytes — kept for the debug overlay. None
    #: when the render failed and the score could not be computed.
    rendered_png: bytes | None = None
    #: True when a score was actually produced; False when the renderer was
    #: unreachable and the caller should carry on as if validation never ran.
    ok: bool = True


#: A per-element region this much worse than pixel-identical (mean absolute
#: difference over 0..1) is worth reporting. Text over a photo never matches
#: perfectly — the fallback font is not the original — so the floor is well
#: above zero to keep the list honest rather than flagging every caption.
_ELEMENT_ISSUE_THRESHOLD = 0.18

#: How far, in source pixels, to search for a whole-element offset when
#: explaining a mismatch. Small: this labels "this box looks shifted", it does
#: not hunt for a new position.
_OFFSET_SEARCH_PX = 6

#: Below this a region already matches; there is no error worth explaining and
#: no reason to spend an offset search on it. Also what keeps the search off
#: the many pixel-identical regions (baked crops) a normal page has.
_MIN_OFFSET_MAD = 0.03

#: A shift only counts as *the* explanation when it at least halves the
#: region's error. A cleanly shifted element drops to near zero under its true
#: offset; substituted type over a photo improves only marginally under any
#: shift, and moving it would be a guess dressed as a measurement.
_OFFSET_GAIN = 0.5


def _document_element(element) -> dict:
    """One ``ExtractedElement`` as the document dict ``element_html`` renders.

    The baked crop is offered as this element's image (via the ``images`` map
    the caller builds), so ``content_source`` is cleared here: the preview must
    show the artwork the import produced, not resolve a listing that is not
    attached.
    """
    doc_type = TYPE_FROM_TEMPLATE.get(element.element_type, "text")
    is_image = element.element_type in (
        ElementType.IMAGE,
        ElementType.LOGO,
        ElementType.STATIC_GRAPHIC,
    )
    return {
        "id": element.key,
        "type": doc_type,
        "visible": True,
        "transform": {
            "x": float(element.geometry.get("x", 0.0)),
            "y": float(element.geometry.get("y", 0.0)),
            "width": float(element.geometry.get("width", 0.1)),
            "height": float(element.geometry.get("height", 0.1)),
            "rotation": float(element.geometry.get("rotation", 0.0)),
            "z_index": int(element.z_index or 0),
        },
        "style": dict(element.style_properties or {}),
        "content": "" if is_image else (element.default_content or ""),
        "content_source": "",
        "manually_overridden": False,
    }


def build_preview_html(elements, page, background: str = "#FFFFFF") -> str:
    """The extracted layout as a standalone HTML document at source size.

    Uses the very same ``element_html`` the editor and every export go through,
    so what is scored is what would actually render — not a second, slightly
    different drawing of the same elements.
    """
    dimension = Dimension(
        key="source",
        label="source",
        width=int(page.width),
        height=int(page.height),
        safe_inset_top=0.0,
        safe_inset_bottom=0.0,
    )
    context = {"brand_kit": {}, "property": {}, "agent": {}, "brokerage": {}}
    images = {
        element.key: _asset_data_uri(element)
        for element in elements
        if _asset_data_uri(element)
    }
    ordered = sorted(elements, key=lambda e: int(e.z_index or 0))
    body = "".join(
        element_html(_document_element(element), context, dimension, images)
        for element in ordered
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>*{margin:0;padding:0;box-sizing:border-box;}"
        f"html,body{{width:{page.width}px;height:{page.height}px;overflow:hidden;}}"
        f"body{{background:{html_lib.escape(background)};}}"
        f"#canvas{{position:relative;width:{page.width}px;height:{page.height}px;overflow:hidden;}}"
        f"</style></head><body><div id='canvas'>{body}</div></body></html>"
    )


def _asset_data_uri(element) -> str:
    """The element's baked crop as a data URI, or "" if it has none."""
    asset = getattr(element, "asset", None)
    if asset is None:
        return ""
    try:
        raw = asset.read()
        asset.seek(0)
    except Exception:  # pragma: no cover - defensive
        return ""
    import base64

    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def render_layout(html: str, width: int, height: int) -> bytes | None:
    """Screenshot the preview HTML through the renderer. None if unreachable.

    A deliberately forgiving wrapper: every failure mode collapses to None so
    the caller treats "could not validate" the same as "validation was off".
    """
    try:
        response = requests.post(
            f"{settings.RENDERER_URL.rstrip('/')}/render",
            json={
                "html": html,
                "width": int(width),
                "height": int(height),
                "format": "png",
                "scale": 1,
            },
            headers={"X-Renderer-Token": settings.RENDERER_TOKEN},
            timeout=getattr(settings, "RENDERER_TIMEOUT_SECONDS", 30),
        )
    except requests.RequestException as exc:
        logger.warning("Validation render unreachable: %s", exc)
        return None
    if response.status_code != 200:
        logger.warning("Validation render returned %s", response.status_code)
        return None
    return response.content


def _to_array(png: bytes, width: int, height: int):
    """PNG bytes -> an (H, W, 3) uint8 array at the given size."""
    import numpy as np
    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        image = image.convert("RGB")
        if image.size != (width, height):
            image = image.resize((width, height), Image.BILINEAR)
        return np.asarray(image, dtype=np.float32)


def _mad(a, b) -> float:
    """Mean absolute difference of two arrays, normalised to 0..1."""
    import numpy as np

    return float(np.abs(a - b).mean() / 255.0)


def score_images(original_png: bytes, rendered_png: bytes, elements=None) -> ValidationResult:
    """Compare two renders and score them. Pure — no browser, no network.

    The global score is one minus the mean absolute pixel difference: robust,
    deterministic, and cheap. Per-element issues crop both images to each
    element's box and report the ones whose region is markedly worse than the
    page as a whole, with a small offset search to say *shifted* rather than
    just *different*.
    """
    # Size is taken from the original so the rendered preview is compared in the
    # source's own coordinate space.
    from PIL import Image

    with Image.open(io.BytesIO(original_png)) as image:
        width, height = image.size

    original = _to_array(original_png, width, height)
    rendered = _to_array(rendered_png, width, height)

    score = 1.0 - _mad(original, rendered)

    issues: list[dict] = []
    for element in elements or []:
        box = _pixel_box(element, width, height)
        if box is None:
            continue
        left, top, right, bottom = box
        base = original[top:bottom, left:right]
        shot = rendered[top:bottom, left:right]
        if base.size == 0 or shot.size == 0:
            continue
        region_mad = _mad(base, shot)
        if region_mad < _MIN_OFFSET_MAD:
            continue
        # The offset search runs on every imperfect region, not only the badly
        # mismatched ones: a cleanly shifted element has a *small* absolute
        # error (a sliver of wrong pixels along two edges) that never reaches
        # the mismatch threshold, and shifts are exactly the finding the
        # import's auto-correction can act on.
        delta, shifted_mad = _best_offset(original, rendered, box)
        explained = delta != (0, 0) and shifted_mad <= region_mad * _OFFSET_GAIN
        if not explained and region_mad < _ELEMENT_ISSUE_THRESHOLD:
            continue
        issues.append(
            {
                "element_id": getattr(element, "key", ""),
                "type": "offset" if explained else "region_mismatch",
                "region_score": round(1.0 - region_mad, 4),
                "delta_x": delta[0] if explained else 0,
                "delta_y": delta[1] if explained else 0,
            }
        )
    issues.sort(key=lambda item: item["region_score"])
    return ValidationResult(score=round(score, 4), issues=issues, rendered_png=rendered_png)


def _pixel_box(element, width: int, height: int):
    """An element's fractional geometry as a clamped integer pixel box."""
    try:
        geo = element.geometry
        left = int(round(float(geo.get("x", 0.0)) * width))
        top = int(round(float(geo.get("y", 0.0)) * height))
        right = int(round((float(geo.get("x", 0.0)) + float(geo.get("width", 0.0))) * width))
        bottom = int(round((float(geo.get("y", 0.0)) + float(geo.get("height", 0.0))) * height))
    except (AttributeError, TypeError, ValueError):
        return None
    left, top = max(0, left), max(0, top)
    right, bottom = min(width, right), min(height, bottom)
    if right - left < 2 or bottom - top < 2:
        return None
    return left, top, right, bottom


def _best_offset(original, rendered, box) -> tuple[tuple[int, int], float]:
    """The small (dx, dy) that best lines this element's region up, if any.

    Slides the *rendered* region against the original within a few pixels and
    keeps the shift that minimises the difference. Returns the shift and the
    difference under it, so the caller can judge whether the shift actually
    *explains* the mismatch or merely nibbles at it. Nothing acts on the
    number here — ``importing._autocorrect_offsets`` is the consumer that
    does, and only under its own score gate.
    """
    left, top, right, bottom = box
    base = original[top:bottom, left:right]
    best = (0, 0)
    best_score = _mad(base, rendered[top:bottom, left:right])
    height, width = original.shape[0], original.shape[1]
    for dy in range(-_OFFSET_SEARCH_PX, _OFFSET_SEARCH_PX + 1):
        for dx in range(-_OFFSET_SEARCH_PX, _OFFSET_SEARCH_PX + 1):
            if dx == 0 and dy == 0:
                continue
            t, b = top + dy, bottom + dy
            l, r = left + dx, right + dx
            if t < 0 or l < 0 or b > height or r > width:
                continue
            candidate = _mad(base, rendered[t:b, l:r])
            if candidate < best_score - 1e-4:
                best_score, best = candidate, (dx, dy)
    return best, best_score


def validate_extraction(elements, page, background: str = "#FFFFFF") -> ValidationResult:
    """Render the extracted layout and score it. Never raises.

    The whole call is wrapped so a validation problem can never turn a
    successful extraction into a failed import — the worst case is a result
    flagged ``ok=False`` that the caller ignores.
    """
    try:
        html = build_preview_html(elements, page, background)
        rendered = render_layout(html, page.width, page.height)
        if rendered is None:
            return ValidationResult(score=0.0, ok=False)
        return score_images(page.png, rendered, elements)
    except Exception:  # pragma: no cover - defensive
        logger.warning("Extraction validation failed", exc_info=True)
        return ValidationResult(score=0.0, ok=False)
