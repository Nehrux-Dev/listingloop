"""Validation of design overrides against template element permissions.

=============================================================================
THIS IS THE ENFORCEMENT POINT. THE FRONTEND IS NOT TRUSTED.
=============================================================================

The editing UI greys out controls an agent may not use, but that is styling —
anyone can open devtools, or skip the UI entirely and POST to the API. So the
rules are re-derived here, from the template, on every write. Nothing about the
request is taken on faith:

  * The set of element keys must exist on the template. An unknown key is
    rejected rather than stored and quietly ignored — silently accepting junk
    is how a client ends up believing an edit worked.
  * Each field is checked against what the element's PERMISSION allows.
    A locked element rejects everything, including a no-op.
  * Each value is checked against the element's CONSTRAINTS: colour
    allowlists, font-size bounds, movement bounds, text length.

Errors come back keyed by element so the UI can point at the offending
control, and each says which rule was broken.

Fail closed throughout: an unrecognised permission grants nothing, and a field
not explicitly allowed is refused.
"""

from __future__ import annotations

import re
from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.templates.models import ElementPermission, ElementType

HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

#: Content fields — what an element *says*.
CONTENT_FIELDS = frozenset({"text", "image_key", "hidden"})

#: Styling fields — how it looks, but not where it is.
STYLE_FIELDS = frozenset(
    {"color", "background_color", "font_size_ratio", "font_weight", "text_align"}
)

#: Geometry fields — where it is and how big.
GEOMETRY_FIELDS = frozenset({"geometry"})

#: The whole contract, in one table. Anything not listed is refused.
ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    ElementPermission.LOCKED: frozenset(),
    ElementPermission.CONTENT_ONLY: CONTENT_FIELDS,
    ElementPermission.STYLED: CONTENT_FIELDS | STYLE_FIELDS,
    ElementPermission.FREE: CONTENT_FIELDS | STYLE_FIELDS | GEOMETRY_FIELDS,
}

FONT_WEIGHTS = {"300", "400", "500", "600", "700", "800", "900"}
TEXT_ALIGNMENTS = {"left", "center", "right"}

DEFAULT_MAX_TEXT_LENGTH = 400
DEFAULT_MIN_FONT_RATIO = 0.01
DEFAULT_MAX_FONT_RATIO = 0.25


class OverrideValidationError(serializers.ValidationError):
    """Raised with a per-element error map."""


def _fail(element_key: str, message) -> None:
    raise OverrideValidationError({element_key: [message]})


def _validate_color(element, key: str, field: str, value: Any) -> str:
    if not isinstance(value, str) or not HEX_COLOR.match(value):
        _fail(key, _("%(field)s must be a hex colour such as #1F2937.") % {"field": field})

    allowed = element.constraints.get("allowed_colors")
    if allowed:
        # Case-insensitive: the UI may send #ffffff where the template says
        # #FFFFFF, and that is the same colour.
        if value.lower() not in {str(option).lower() for option in allowed}:
            _fail(
                key,
                _(
                    "%(field)s must be one of the colours this template allows: "
                    "%(allowed)s."
                )
                % {"field": field, "allowed": ", ".join(allowed)},
            )
    return value


def _validate_font_size_ratio(element, key: str, value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _fail(key, _("font_size_ratio must be a number."))

    minimum = element.constraints.get("min_font_size_ratio", DEFAULT_MIN_FONT_RATIO)
    maximum = element.constraints.get("max_font_size_ratio", DEFAULT_MAX_FONT_RATIO)

    if not (minimum <= float(value) <= maximum):
        _fail(
            key,
            _("font_size_ratio must be between %(min)s and %(max)s for this element.")
            % {"min": minimum, "max": maximum},
        )
    return float(value)


def _validate_geometry(element, key: str, value: Any) -> dict:
    if not isinstance(value, dict):
        _fail(key, _("geometry must be an object with x, y, width and height."))

    result = {}
    for field in ("x", "y", "width", "height"):
        if field not in value:
            _fail(key, _("geometry is missing '%(field)s'.") % {"field": field})
        raw = value[field]
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            _fail(key, _("geometry.%(field)s must be a number.") % {"field": field})
        raw = float(raw)
        # Fractions of the canvas, so 0..1 is the whole coordinate space.
        if not (0.0 <= raw <= 1.0):
            _fail(
                key,
                _("geometry.%(field)s must be between 0 and 1 (a fraction of the canvas).")
                % {"field": field},
            )
        result[field] = raw

    if result["width"] <= 0 or result["height"] <= 0:
        _fail(key, _("geometry width and height must be greater than zero."))

    # Movement bounds: a 'free' element is free *within a region*, not anywhere.
    bounds = element.constraints.get("bounds")
    if bounds:
        min_x = float(bounds.get("x", 0.0))
        min_y = float(bounds.get("y", 0.0))
        max_x = min_x + float(bounds.get("width", 1.0))
        max_y = min_y + float(bounds.get("height", 1.0))

        if (
            result["x"] < min_x - 1e-9
            or result["y"] < min_y - 1e-9
            or result["x"] + result["width"] > max_x + 1e-9
            or result["y"] + result["height"] > max_y + 1e-9
        ):
            _fail(
                key,
                _(
                    "This element must stay inside the area the template allows "
                    "(x %(x)s–%(mx)s, y %(y)s–%(my)s)."
                )
                % {"x": min_x, "mx": max_x, "y": min_y, "my": max_y},
            )

    max_scale = element.constraints.get("max_scale")
    if max_scale and element.geometry:
        base_w = float(element.geometry.get("width") or 0) or None
        base_h = float(element.geometry.get("height") or 0) or None
        if base_w and result["width"] > base_w * float(max_scale) + 1e-9:
            _fail(key, _("This element cannot be scaled beyond %(n)sx its width.") % {"n": max_scale})
        if base_h and result["height"] > base_h * float(max_scale) + 1e-9:
            _fail(key, _("This element cannot be scaled beyond %(n)sx its height.") % {"n": max_scale})

    return result


def _validate_text(element, key: str, value: Any) -> str:
    if not isinstance(value, str):
        _fail(key, _("text must be a string."))

    max_length = int(element.constraints.get("max_length", DEFAULT_MAX_TEXT_LENGTH))
    if len(value) > max_length:
        _fail(
            key,
            _("text must be %(n)s characters or fewer for this element.")
            % {"n": max_length},
        )
    return value


def _validate_image_key(element, key: str, value: Any) -> str:
    """An image override names a storage key, never a URL.

    Accepting an arbitrary URL here would let a design pull in remote content
    at render time — a request made by our renderer, to a destination the user
    chose. Keys are resolved against our own storage instead.
    """
    if not isinstance(value, str) or not value.strip():
        _fail(key, _("image_key must be a non-empty string."))
    if "://" in value or value.startswith("//"):
        _fail(
            key,
            _("image_key must be a stored file key, not a URL."),
        )
    if ".." in value:
        _fail(key, _("image_key must not contain '..'."))
    return value.strip()


def validate_overrides(template, overrides: Any) -> dict:
    """Validate and normalise ``overrides`` against ``template``.

    Returns the cleaned mapping. Raises ``OverrideValidationError`` keyed by
    element on the first violation for that element.
    """
    if overrides in (None, ""):
        return {}
    if not isinstance(overrides, dict):
        raise OverrideValidationError(
            {"overrides": [_("Overrides must be an object keyed by element.")]}
        )

    elements = {element.key: element for element in template.elements.all()}
    cleaned: dict[str, dict] = {}

    for element_key, payload in overrides.items():
        element = elements.get(element_key)
        if element is None:
            raise OverrideValidationError(
                {
                    element_key: [
                        _("This template has no element called '%(key)s'.")
                        % {"key": element_key}
                    ]
                }
            )

        if not isinstance(payload, dict):
            _fail(element_key, _("Each override must be an object of fields."))

        # An empty override is a no-op, but on a locked element it still
        # signals a client that thinks it can edit — reject it and say why.
        allowed = ALLOWED_FIELDS.get(element.permission, frozenset())

        if element.permission == ElementPermission.LOCKED:
            _fail(
                element_key,
                _("'%(label)s' is locked by this template and cannot be changed.")
                % {"label": element.label or element_key},
            )

        clean_payload: dict[str, Any] = {}
        for field, value in payload.items():
            if field not in allowed:
                _fail(
                    element_key,
                    _(
                        "'%(field)s' cannot be changed on this element "
                        "(permission: %(permission)s)."
                    )
                    % {"field": field, "permission": element.permission},
                )

            if field == "text":
                if element.element_type not in (
                    ElementType.TEXT,
                    ElementType.BADGE,
                ):
                    _fail(element_key, _("This element does not display text."))
                clean_payload["text"] = _validate_text(element, element_key, value)

            elif field == "image_key":
                if element.element_type not in (ElementType.IMAGE, ElementType.LOGO):
                    _fail(element_key, _("This element does not display an image."))
                clean_payload["image_key"] = _validate_image_key(
                    element, element_key, value
                )

            elif field == "hidden":
                if not isinstance(value, bool):
                    _fail(element_key, _("hidden must be true or false."))
                if value and element.constraints.get("required", False):
                    _fail(
                        element_key,
                        _("'%(label)s' is required and cannot be hidden.")
                        % {"label": element.label or element_key},
                    )
                clean_payload["hidden"] = value

            elif field in ("color", "background_color"):
                clean_payload[field] = _validate_color(
                    element, element_key, field, value
                )

            elif field == "font_size_ratio":
                clean_payload[field] = _validate_font_size_ratio(
                    element, element_key, value
                )

            elif field == "font_weight":
                if str(value) not in FONT_WEIGHTS:
                    _fail(
                        element_key,
                        _("font_weight must be one of: %(options)s.")
                        % {"options": ", ".join(sorted(FONT_WEIGHTS))},
                    )
                clean_payload[field] = str(value)

            elif field == "text_align":
                if value not in TEXT_ALIGNMENTS:
                    _fail(
                        element_key,
                        _("text_align must be one of: %(options)s.")
                        % {"options": ", ".join(sorted(TEXT_ALIGNMENTS))},
                    )
                clean_payload[field] = value

            elif field == "geometry":
                clean_payload[field] = _validate_geometry(element, element_key, value)

            else:  # pragma: no cover - unreachable while ALLOWED_FIELDS is the gate
                _fail(element_key, _("Unsupported field '%(field)s'.") % {"field": field})

        if clean_payload:
            cleaned[element_key] = clean_payload

    return cleaned
