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
    # Thin wrapper: a Design is just an (agent, property) pair with overrides,
    # so it unwraps to the shared resolver rather than duplicating it. Two
    # implementations of "what data does a template get" would drift.
    return build_template_context(design.agent, design.listing)


def build_template_context(agent, listing=None) -> dict[str, Any]:
    """Assemble template data from an agent and (optionally) a property.

    The reusable entry point: templates never query the database themselves,
    they are handed this. Callers are ``build_context`` (which has a Design and
    unwraps it) and anything else that needs the same data without one.

    Shape::

        {"agent": {...}, "brokerage": {...}, "brand": {...}, "property": {...}}

    ``brand`` falls back from the agent's own kit to their brokerage's, which
    is what makes onboarding worth doing once: an agent who never sets personal
    colours still gets branded material.

    ``property`` is ``{}`` when no listing is given — seasonal and agent-led
    templates have none, and every consumer already treats a missing key as
    "not available" rather than an error.
    """
    brokerage = agent.brokerage
    brand_kit = getattr(agent, "brand_kit", None) or (
        getattr(brokerage, "brand_kit", None) if brokerage else None
    )

    context: dict[str, Any] = {
        "agent": {
            # full_name is the spec's placeholder name; `name` is what the
            # existing templates already use. Both point at the same value
            # rather than one becoming subtly stale.
            "full_name": agent.name or agent.user.full_name,
            "name": agent.name or agent.user.full_name,
            "first_name": agent.user.first_name,
            "last_name": agent.user.last_name,
            "job_title": agent.job_title,
            "phone": agent.phone,
            "email": agent.email or agent.user.email,
            "tagline": agent.tagline,
            "licence_number": agent.licence_number,
            "photo": file_to_data_uri(agent.photo),
        },
        "brokerage": {
            "name": brokerage.name if brokerage else "",
            "phone": brokerage.phone if brokerage else "",
            "website": brokerage.website if brokerage else "",
            "licence_number": brokerage.licence_number if brokerage else "",
            # Both spellings: `disclaimer` is the spec's placeholder,
            # `required_disclaimer` is the existing field name.
            "disclaimer": brokerage.required_disclaimer if brokerage else "",
            "required_disclaimer": brokerage.required_disclaimer if brokerage else "",
            "logo": file_to_data_uri(brokerage.logo) if brokerage else None,
        },
        "brand": {
            "primary_color": brand_kit.primary_color if brand_kit else "#1F2937",
            "secondary_color": brand_kit.secondary_color if brand_kit else "#4B5563",
            "accent_color": brand_kit.accent_color if brand_kit else "#2563EB",
            # `font` is the spec's single placeholder; the model distinguishes
            # heading from body, and the heading face is the brand signature.
            "font": brand_kit.heading_font if brand_kit else "Inter",
            "heading_font": brand_kit.heading_font if brand_kit else "Inter",
            "body_font": brand_kit.body_font if brand_kit else "Inter",
            "design_style": brand_kit.design_style if brand_kit else "modern",
        },
        "property": {},
    }

    if listing is not None:
        photos = list(listing.photos.all()[:6])
        context["property"] = {
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
            "property_type": (
                listing.get_property_type_display() if listing.property_type else ""
            ),
            "features": list(listing.features or []),
            "description": listing.description,
            "main_photo": file_to_data_uri(photos[0].image) if photos else None,
            "photo": file_to_data_uri(photos[0].image) if photos else None,
            "photos": [file_to_data_uri(photo.image) for photo in photos],
        }

    # `brand_kit` and `listing` are kept as aliases so templates authored
    # against the original key names keep resolving. One dict, two names — not
    # two dicts that can drift apart.
    context["brand_kit"] = context["brand"]
    context["listing"] = context["property"]
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
