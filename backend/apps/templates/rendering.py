"""Render a design to an image, and save the result.

Django composes the HTML (``html_builder``) and posts it to the renderer
service, which owns the warm Chromium. Keeping the split here means the
renderer can be scaled, restarted or swapped without template logic moving,
and everything up to the screenshot is testable in Python.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from rest_framework.exceptions import APIException

from apps.templates.dimensions import Dimension, get_dimension
from apps.templates.html_builder import build_html
from apps.templates.models import DesignExport, ExportFormat
from apps.templates.render_context import build_context, file_to_data_uri

logger = logging.getLogger(__name__)


class RenderUnavailable(APIException):
    status_code = 503
    default_detail = (
        "The rendering service is unavailable. Your design is saved; try "
        "exporting again shortly."
    )
    default_code = "render_unavailable"


class RenderFailed(APIException):
    status_code = 502
    default_detail = "The design could not be rendered."
    default_code = "render_failed"


@dataclass
class RenderResult:
    content: bytes
    content_type: str
    render_ms: int
    dimension: Dimension
    export_format: str


def _resolve_image_overrides(design) -> dict[str, str]:
    """Turn stored image keys in overrides into inline data URIs.

    Overrides store a storage *key*, never a URL (see ``overrides.py``), so
    resolution happens here, through the storage API — which is what keeps the
    renderer network-isolated and the storage backend swappable.
    """
    resolved = {}
    for element_key, payload in (design.overrides or {}).items():
        image_key = payload.get("image_key")
        if not image_key:
            continue
        data_uri = file_to_data_uri(image_key)
        if data_uri:
            resolved[element_key] = data_uri
        else:
            logger.info("Image key %r for element %r could not be read", image_key, element_key)
    return resolved


def render_design(design, dimension_key: str, export_format: str = ExportFormat.PNG) -> RenderResult:
    """Render one design at one dimension. Does not save anything."""
    dimension = get_dimension(dimension_key)
    context = build_context(design)
    html = build_html(design, context, dimension, _resolve_image_overrides(design))

    payload = {
        "html": html,
        "width": dimension.width,
        "height": dimension.height,
        "format": "png" if export_format == ExportFormat.PNG else "jpg",
        "quality": settings.RENDERER_JPG_QUALITY,
        "scale": settings.RENDERER_SCALE,
    }

    try:
        response = requests.post(
            f"{settings.RENDERER_URL.rstrip('/')}/render",
            json=payload,
            headers={"X-Renderer-Token": settings.RENDERER_TOKEN},
            timeout=settings.RENDERER_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("Renderer unreachable: %s", exc)
        raise RenderUnavailable() from exc

    if response.status_code != 200:
        detail = "unknown error"
        try:
            detail = response.json().get("detail", detail)
        except ValueError:
            pass
        logger.warning("Renderer returned %s: %s", response.status_code, detail)
        raise RenderFailed(f"The design could not be rendered: {detail}")

    return RenderResult(
        content=response.content,
        content_type=response.headers.get("Content-Type", "image/png"),
        render_ms=int(response.headers.get("X-Render-Ms", 0)),
        dimension=dimension,
        export_format=export_format,
    )


def export_design(design, dimension_key: str, export_format: str = ExportFormat.PNG) -> DesignExport:
    """Render and persist an export.

    The file is written through Django's storage API exactly like every user
    upload, so exports follow the same path to object storage when that day
    comes — there is no separate output directory to migrate.
    """
    result = render_design(design, dimension_key, export_format)

    extension = "png" if export_format == ExportFormat.PNG else "jpg"
    filename = f"{design.pk}-{dimension_key}.{extension}"

    export = DesignExport(
        design=design,
        dimension=dimension_key,
        export_format=export_format,
        width=result.dimension.width,
        height=result.dimension.height,
        bytes=len(result.content),
        render_ms=result.render_ms,
    )
    export.image.save(filename, ContentFile(result.content), save=False)
    export.save()
    return export


def export_design_bundle(design, dimension_keys, export_format: str = ExportFormat.PNG):
    """Render one design at several dimensions.

    Renders sequentially and on purpose: the renderer's page pool is bounded
    because Chromium's memory grows with live pages, so firing four concurrent
    requests would just queue inside the service while holding four Django
    workers open.
    """
    exports = []
    for key in dimension_keys:
        exports.append(export_design(design, key, export_format))
    return exports
