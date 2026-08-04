"""Builds the data context a template's elements resolve against."""

from __future__ import annotations

import base64
import logging
import mimetypes
from decimal import Decimal
from typing import Any

from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

#: Images are inlined as data URIs rather than passed to the renderer as URLs.
#: The renderer runs in a separate container with no access to our storage and
#: no credentials, and handing it URLs would mean either exposing media
#: publicly or inventing a signed-URL scheme. Inlining also keeps the render
#: independent of whichever storage backend is configured.
MAX_INLINE_IMAGE_BYTES = 8 * 1024 * 1024


def file_to_data_uri(file_field_or_key) -> str | None:
    """Read a stored file through the storage API and return a data URI."""
    if not file_field_or_key:
        return None

    name = getattr(file_field_or_key, "name", file_field_or_key)
    storage = getattr(file_field_or_key, "storage", default_storage)
    if not name:
        return None

    try:
        if not storage.exists(name):
            return None
        size = storage.size(name)
        if size > MAX_INLINE_IMAGE_BYTES:
            logger.warning("Skipping oversized image %r (%s bytes) in render", name, size)
            return None
        with storage.open(name, "rb") as handle:
            payload = handle.read()
    except Exception:
        logger.warning("Could not read %r for rendering", name, exc_info=True)
        return None

    content_type = mimetypes.guess_type(name)[0] or "image/png"
    return f"data:{content_type};base64,{base64.b64encode(payload).decode('ascii')}"


def _decimal(value) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, (Decimal, int, float)) else None


def build_context(design) -> dict[str, Any]:
    """Assemble ``{listing, agent, brokerage, brand_kit}`` for a design.

    Every value is plain data by the time it leaves here, so the HTML builder
    never touches the ORM and the whole context can be logged or cached.
    """
    agent = design.agent
    brokerage = agent.brokerage
    listing = design.listing

    # An agent's own kit wins; the brokerage kit is the fallback so a design
    # is never unbranded.
    brand_kit = getattr(agent, "brand_kit", None) or (
        getattr(brokerage, "brand_kit", None) if brokerage else None
    )

    context: dict[str, Any] = {
        "agent": {
            "name": agent.name,
            "job_title": agent.job_title,
            "phone": agent.phone,
            "email": agent.email,
            "tagline": agent.tagline,
            "photo": file_to_data_uri(agent.photo),
        },
        "brokerage": {
            "name": brokerage.name if brokerage else "",
            "phone": brokerage.phone if brokerage else "",
            "website": brokerage.website if brokerage else "",
            "required_disclaimer": brokerage.required_disclaimer if brokerage else "",
            "logo": file_to_data_uri(brokerage.logo) if brokerage else None,
        },
        "brand_kit": {
            "primary_color": brand_kit.primary_color if brand_kit else "#1F2937",
            "secondary_color": brand_kit.secondary_color if brand_kit else "#4B5563",
            "accent_color": brand_kit.accent_color if brand_kit else "#2563EB",
            "heading_font": brand_kit.heading_font if brand_kit else "Inter",
            "body_font": brand_kit.body_font if brand_kit else "Inter",
            "design_style": brand_kit.design_style if brand_kit else "modern",
        },
        "listing": {},
    }

    if listing is not None:
        photos = list(listing.photos.all()[:6])
        context["listing"] = {
            "address": listing.address,
            "city": listing.city,
            "state": listing.state,
            "postcode": listing.postcode,
            "country": listing.country,
            "full_address": listing.full_address,
            "location": " ".join(
                part for part in (listing.city, listing.state, listing.postcode) if part
            ),
            "price": _decimal(listing.price),
            "bedrooms": listing.bedrooms,
            "bathrooms": _decimal(listing.bathrooms),
            "square_footage": listing.square_footage,
            "property_type": listing.get_property_type_display() if listing.property_type else "",
            "features": list(listing.features or []),
            "description": listing.description,
            "photo": file_to_data_uri(photos[0].image) if photos else None,
            "photos": [file_to_data_uri(photo.image) for photo in photos],
        }

    return context


def resolve_path(context: dict, path: str):
    """Resolve a dotted ``content_source`` such as ``listing.price``.

    Supports a trailing ``[n]`` index for lists (``listing.photos[1]``).
    Returns None for anything missing — a template referencing a field the
    listing does not have renders empty rather than raising.
    """
    if not path:
        return None

    current: Any = context
    for part in path.split("."):
        index = None
        if part.endswith("]") and "[" in part:
            part, _, raw_index = part[:-1].partition("[")
            try:
                index = int(raw_index)
            except ValueError:
                return None

        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)

        if index is not None:
            if isinstance(current, (list, tuple)) and -len(current) <= index < len(current):
                current = current[index]
            else:
                return None

        if current is None:
            return None

    return current
