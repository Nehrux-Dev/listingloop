"""Save per-stage images and a report so a bad reconstruction can be diagnosed.

Off unless ``TEMPLATE_IMPORT_DEBUG`` is set. When on, an import writes a small
gallery under ``MEDIA_ROOT/import-debug/<job>/`` through the ordinary storage
API — the same path uploads take, so it works locally and against object
storage without a second code path:

    01_original.png        the raster the rest of the import measured against
    02_extracted_boxes.png every element's box as the reader first measured it
    03_aligned_boxes.png   the same boxes after the tidy-up moved them
    04_preview.png         the editable layout rendered back to a raster
    05_difference.png      per-pixel difference of 01 and 04
    06_final.png           04 again, framed as the accepted result
    report.json            counts and the fidelity score

02/03 need no browser — they are drawn on the raster with Pillow. 04/05/06 only
appear when the render-and-compare stage also ran, because they are its output.

None of this changes the template. It is a window onto the pipeline, nothing
the pipeline reads back.
"""

from __future__ import annotations

import io
import json
import logging

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

_DEBUG_ROOT = "import-debug"

#: Box outline colours, so the overlays are legible against most artwork.
_PRE_COLOUR = (220, 40, 40)     # red: as measured
_POST_COLOUR = (40, 140, 220)   # blue: after tidy-up


def _save(job_id, name: str, data: bytes) -> str:
    path = f"{_DEBUG_ROOT}/{job_id}/{name}"
    if default_storage.exists(path):
        default_storage.delete(path)
    return default_storage.save(path, ContentFile(data))


def _draw_boxes(png: bytes, boxes, colour, width_scale: float, height_scale: float) -> bytes:
    """Outline each box on a copy of the raster. Boxes are in ``x,y,w,h``."""
    from PIL import Image, ImageDraw

    with Image.open(io.BytesIO(png)) as base:
        canvas = base.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    for box in boxes:
        left = float(box.get("x", 0.0)) * width_scale
        top = float(box.get("y", 0.0)) * height_scale
        right = left + float(box.get("width", 0.0)) * width_scale
        bottom = top + float(box.get("height", 0.0)) * height_scale
        if right <= left or bottom <= top:
            continue
        draw.rectangle([left, top, right, bottom], outline=colour, width=3)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def _difference(a_png: bytes, b_png: bytes) -> bytes | None:
    """A high-contrast per-pixel difference of two renders."""
    try:
        from PIL import Image, ImageChops

        with Image.open(io.BytesIO(a_png)) as a_img, Image.open(io.BytesIO(b_png)) as b_img:
            a_rgb = a_img.convert("RGB")
            b_rgb = b_img.convert("RGB")
            if a_rgb.size != b_rgb.size:
                b_rgb = b_rgb.resize(a_rgb.size)
            diff = ImageChops.difference(a_rgb, b_rgb)
        buffer = io.BytesIO()
        diff.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:  # pragma: no cover - defensive
        logger.warning("Could not build difference image", exc_info=True)
        return None


def write_debug_gallery(job_id, page, payload, elements, validation=None) -> dict:
    """Write the debug images and report for one import. Returns the report.

    Never raises: a diagnostic aid that broke the thing it is diagnosing would
    be worse than useless, so every step is best-effort and failures are logged.
    """
    report: dict = {
        "canvas": {"width": page.width, "height": page.height},
        "element_count": len(elements),
        "edge_corrections": 0,
        "spacing_corrections": 0,
        "alignment_relationships": 0,
    }
    meta = (payload or {}).get("extraction_meta", {})
    for key in ("edge_corrections", "spacing_corrections", "alignment_relationships"):
        if key in meta:
            report[key] = meta[key]

    try:
        _save(job_id, "01_original.png", page.png)

        pre = meta.get("pre_align_boxes")
        if pre:
            _save(job_id, "02_extracted_boxes.png", _draw_boxes(page.png, pre, _PRE_COLOUR, 1.0, 1.0))

        # Post-tidy boxes come from the normalised elements, whose geometry is a
        # fraction of the page — scaled back up to source pixels to draw.
        aligned = [
            {
                "x": float(e.geometry.get("x", 0.0)),
                "y": float(e.geometry.get("y", 0.0)),
                "width": float(e.geometry.get("width", 0.0)),
                "height": float(e.geometry.get("height", 0.0)),
            }
            for e in elements
        ]
        _save(
            job_id,
            "03_aligned_boxes.png",
            _draw_boxes(page.png, aligned, _POST_COLOUR, page.width, page.height),
        )

        if validation is not None and getattr(validation, "rendered_png", None):
            preview = validation.rendered_png
            _save(job_id, "04_preview.png", preview)
            diff = _difference(page.png, preview)
            if diff:
                _save(job_id, "05_difference.png", diff)
            _save(job_id, "06_final.png", preview)
            report["final_similarity"] = validation.score
            report["issues"] = validation.issues

        report_bytes = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        _save(job_id, "report.json", report_bytes)
    except Exception:  # pragma: no cover - defensive
        logger.warning("Could not write import debug gallery for job %s", job_id, exc_info=True)

    return report
