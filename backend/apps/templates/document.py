"""The design document: the element list a Design owns and an agent edits.

WHAT CHANGED, AND WHY
=============================================================================
A design used to be a *diff*. The template owned the elements; the design
owned ``overrides`` (a sparse ``{key: {field: value}}`` map) plus
``extra_elements`` (additions). Whether an agent could change a thing was a
property of the *template element* — one of four permission tiers — so most
of a template was simply not editable, and the UI said "FIXED BY TEMPLATE".

Now a design owns its elements outright. Opening a template deep-copies its
elements into ``Design.elements``; every edit after that mutates the design's
own copy and the template is never touched again. There is no permission tier
and no template-level lock. The only thing that restricts editing is
``locked`` — a per-element boolean, default ``False``, set by the *user*.

WHAT THIS MODULE IS RESPONSIBLE FOR
-----------------------------------
Three things, and they are not the same thing:

  1. **Shape** — building an element from a template element, or from
     scratch, so every element in the system has one schema.
  2. **Safety** — ``validate_document`` is the server-side enforcement point.
     It is NOT about permissions any more; it is about the fact that every
     style value here is interpolated into a ``style="..."`` attribute by
     ``html_builder``, and that the renderer is a browser. An unvalidated
     colour is a CSS injection; an unvalidated ``image_key`` is an outbound
     request to a host the user picked. Those checks stay, and they stay
     strict, because they were never permission checks in the first place.
  3. **Bindings** — which property/agent field feeds an element's content, so
     opening a template auto-populates price, beds, location and agent
     details, and changing the underlying data re-populates them.

WHAT ``locked`` IS AND IS NOT
-----------------------------
It is an interaction guard, the same one Figma and Canva have: it stops you
dragging the background out from under yourself. It is not a security
boundary — the person it restricts is the person who set it and who can
unset it in one click. So it is enforced in the editor (locked elements do
not hit-test, do not drag, do not resize) and recorded faithfully here, but
this module does not refuse a write to a locked element: the editor saves the
whole document at once, so "unlock it and move it" is a single save, and
refusing that would break the obvious flow to enforce nothing.

Compare ``_validate_color`` below, which *does* refuse — because that one is
protecting the renderer, not the user's own intent.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Iterable

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.templates.models import ElementType

# ---------------------------------------------------------------------------
# Element types
# ---------------------------------------------------------------------------

#: The document's own type vocabulary. Wider than the template's because a
#: design is a canvas now, not a form: ``line``, ``icon``, ``button`` and
#: ``background`` are all things an agent can add, and none of them existed as
#: authorable concepts before.
TEXT_TYPE = "text"
IMAGE_TYPE = "image"
SHAPE_TYPE = "shape"
LINE_TYPE = "line"
ICON_TYPE = "icon"
LOGO_TYPE = "logo"
BUTTON_TYPE = "button"
BACKGROUND_TYPE = "background"

ELEMENT_TYPES = frozenset(
    {
        TEXT_TYPE,
        IMAGE_TYPE,
        SHAPE_TYPE,
        LINE_TYPE,
        ICON_TYPE,
        LOGO_TYPE,
        BUTTON_TYPE,
        BACKGROUND_TYPE,
    }
)

#: Types that render an ``<img>``. ``background`` is here conditionally — it
#: draws a photo when it has one and a colour fill when it does not — so it is
#: checked with ``carries_image`` rather than by membership.
IMAGE_TYPES = frozenset({IMAGE_TYPE, LOGO_TYPE, ICON_TYPE})

#: Types that render type. ``button`` is a shape with a label inside it, which
#: is exactly what the old ``badge`` was.
TEXT_TYPES = frozenset({TEXT_TYPE, BUTTON_TYPE})

#: How a template element's type maps onto the document's vocabulary.
#:
#: ``static_graphic`` collapses into ``image``: the distinction only existed
#: because a template's decorative artwork lived in a ``static_asset``
#: ImageField that no override could reach, whereas an ``image``'s content came
#: from listing data. Once the design owns its elements, both are just "an
#: image whose content is a storage key", and the copy step writes the asset's
#: key into ``content``. One less special case in the renderer.
TYPE_FROM_TEMPLATE: dict[str, str] = {
    ElementType.TEXT: TEXT_TYPE,
    ElementType.IMAGE: IMAGE_TYPE,
    ElementType.LOGO: LOGO_TYPE,
    ElementType.COLOR_BLOCK: SHAPE_TYPE,
    ElementType.DIVIDER: LINE_TYPE,
    ElementType.BADGE: BUTTON_TYPE,
    ElementType.STATIC_GRAPHIC: IMAGE_TYPE,
}


def carries_image(element_type: str, content: Any) -> bool:
    """Whether this element draws an ``<img>`` rather than a filled box."""
    if element_type in IMAGE_TYPES:
        return True
    return element_type == BACKGROUND_TYPE and bool(content)


def carries_text(element_type: str) -> bool:
    return element_type in TEXT_TYPES


# ---------------------------------------------------------------------------
# Property data bindings
# ---------------------------------------------------------------------------


class PropertyField:
    """One bindable business fact: a name, where it lives, how it reads."""

    __slots__ = ("name", "label", "path", "format", "group", "is_image")

    def __init__(self, name, label, path, group, fmt=None, is_image=False):
        self.name = name
        self.label = label
        self.path = path
        self.format = fmt
        self.group = group
        self.is_image = is_image

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": str(self.label),
            "group": self.group,
            "format": self.format or "",
            "is_image": self.is_image,
        }


#: The bindable fields, in the order the data panel shows them.
#:
#: Names are snake_case like every other field this API returns. The spec drafted
#: them as ``agentName``; using camelCase here would make these the only
#: camelCase keys in the entire payload, which is a worse cost than the rename.
#:
#: ``path`` is the same dotted ``content_source`` syntax templates already use,
#: resolved by ``render_context.resolve_path`` — so a binding is a *named*
#: content source, not a second mechanism alongside it.
PROPERTY_FIELDS: tuple[PropertyField, ...] = (
    # -- the property ------------------------------------------------------
    PropertyField("price", _("Price"), "property.price", "property", fmt="currency"),
    PropertyField("bedrooms", _("Bedrooms"), "property.bedrooms", "property"),
    PropertyField("bathrooms", _("Bathrooms"), "property.bathrooms", "property"),
    PropertyField("area", _("Area"), "property.square_footage", "property", fmt="number"),
    PropertyField("location", _("Location"), "property.location", "property"),
    PropertyField("address", _("Full address"), "property.full_address", "property"),
    PropertyField("property_type", _("Property type"), "property.property_type", "property"),
    PropertyField("description", _("Description"), "property.description", "property"),
    PropertyField("photo_1", _("Photo 1"), "property.photos[0]", "property", is_image=True),
    PropertyField("photo_2", _("Photo 2"), "property.photos[1]", "property", is_image=True),
    PropertyField("photo_3", _("Photo 3"), "property.photos[2]", "property", is_image=True),
    PropertyField("photo_4", _("Photo 4"), "property.photos[3]", "property", is_image=True),
    PropertyField("photo_5", _("Photo 5"), "property.photos[4]", "property", is_image=True),
    # -- the agent ---------------------------------------------------------
    PropertyField("agent_name", _("Agent name"), "agent.full_name", "agent"),
    PropertyField("agent_phone", _("Agent phone"), "agent.phone", "agent"),
    PropertyField("agent_email", _("Agent email"), "agent.email", "agent"),
    PropertyField("agent_title", _("Agent job title"), "agent.job_title", "agent"),
    PropertyField("agent_licence", _("Agent licence"), "agent.licence_number", "agent"),
    PropertyField("agent_photo", _("Agent photo"), "agent.photo", "agent", is_image=True),
    # -- the brokerage -----------------------------------------------------
    PropertyField("brokerage_name", _("Brokerage"), "brokerage.name", "brokerage"),
    PropertyField("brokerage_phone", _("Brokerage phone"), "brokerage.phone", "brokerage"),
    PropertyField("brokerage_website", _("Website"), "brokerage.website", "brokerage"),
    PropertyField("brokerage_logo", _("Brokerage logo"), "brokerage.logo", "brokerage", is_image=True),
    PropertyField("disclaimer", _("Disclaimer"), "brokerage.disclaimer", "brokerage"),
)

PROPERTY_FIELDS_BY_NAME: dict[str, PropertyField] = {
    field.name: field for field in PROPERTY_FIELDS
}

#: Reverse lookup, used once — when copying a template element whose
#: ``content_source`` happens to be a path we have a friendly name for.
#:
#: ``listing.*`` and ``brand_kit.*`` are registered as aliases because
#: ``render_context`` exposes the same dicts under both names, and templates in
#: the library were authored against either spelling. Without the aliases, half
#: the existing templates would copy across with no binding at all and the data
#: panel would show nothing for them.
def _binding_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for field in PROPERTY_FIELDS:
        index[field.path] = field.name
        if field.path.startswith("property."):
            index["listing." + field.path[len("property.") :]] = field.name
    # Paths the library uses that mean the same thing as a registered field.
    index.setdefault("property.main_photo", "photo_1")
    index.setdefault("listing.main_photo", "photo_1")
    index.setdefault("property.photo", "photo_1")
    index.setdefault("listing.photo", "photo_1")
    index.setdefault("agent.name", "agent_name")
    index.setdefault("brokerage.required_disclaimer", "disclaimer")
    return index


BINDING_BY_PATH: dict[str, str] = _binding_index()


def binding_for_source(content_source: str) -> str | None:
    """The property field a template's ``content_source`` corresponds to.

    ``None`` for a path with no friendly name — those keep working, they just
    do not appear as a named field in the data panel. Losing the binding is
    not the same as losing the content.
    """
    if not content_source:
        return None
    return BINDING_BY_PATH.get(content_source)


def source_for_binding(name: str) -> str:
    field = PROPERTY_FIELDS_BY_NAME.get(name)
    return field.path if field else ""


# ---------------------------------------------------------------------------
# Safety limits
#
# None of these are permissions. Each is here because the renderer is a real
# browser being handed values an end user chose.
# ---------------------------------------------------------------------------

#: A design is a poster, not a document. Well past any real layout, well short
#: of what would make the renderer chew through a request slot.
MAX_ELEMENTS = 300

MAX_TEXT_LENGTH = 5000
MAX_NAME_LENGTH = 120

#: Elements may hang off the edge of the canvas — cropping a photo against the
#: bleed is a normal thing to do in a design tool, and the old 0..1 clamp made
#: it impossible. Bounded anyway so a stray drag cannot place an element ten
#: thousand canvases away, where it is invisible and unrecoverable.
MIN_COORD, MAX_COORD = -2.0, 3.0
MIN_SIZE, MAX_SIZE = 0.001, 4.0
MIN_ROTATION, MAX_ROTATION = -360.0, 360.0
MAX_Z_INDEX = 1000

HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

#: Brand-kit colours an element may reference instead of a literal hex.
#: Resolved at render time by ``html_builder._resolve_color``.
BRAND_COLOR_TOKENS = frozenset({"@primary_color", "@secondary_color", "@accent_color"})

#: Gradients go into ``background-image``, which is the one CSS property that
#: can make an outbound request (``url(...)``). So the value is not merely
#: checked for plausibility — it is matched whole against a grammar that has no
#: way to express a URL, and anything unrecognised is dropped.
GRADIENT_RE = re.compile(
    r"^(?:linear|radial)-gradient\("
    r"[#\w\s,.%()-]{0,240}"
    r"\)$"
)

FONT_WEIGHTS = {"300", "400", "500", "600", "700", "800", "900"}

#: Type *roles*, not family names. A template says "this is display type" and
#: ``html_builder.FONT_STACKS`` decides which installed family that is.
#:
#: Naming families directly was the alternative and is worse in both
#: directions: a family the renderer does not have falls back to whatever
#: fontconfig picks, so the export silently disagrees with the editor; and an
#: arbitrary string is one more value being interpolated into a ``style``
#: attribute.
#:
#: ``script`` was the fifth, added because luxury property artwork routinely
#: sets its headline in flowing calligraphy — "Dream House" across a hero shot
#: — and rendering that in a serif is the single most obvious way an imported
#: template stops looking like the flyer it came from.
FONT_FAMILIES = {"body", "display", "serif", "mono", "script"}
TEXT_ALIGNMENTS = {"left", "center", "right"}
VERTICAL_ALIGNMENTS = {"flex-start", "center", "flex-end"}
FONT_STYLES = {"normal", "italic"}
TEXT_TRANSFORMS = {"none", "uppercase", "lowercase", "capitalize"}
TEXT_DECORATIONS = {"none", "underline", "line-through"}
OBJECT_FITS = {"cover", "contain", "fill"}
OBJECT_POSITIONS = {
    "left top", "center top", "right top",
    "left center", "center center", "right center",
    "left bottom", "center bottom", "right bottom",
}
BORDER_STYLES = {"solid", "dashed", "dotted"}

#: How a shape's interior is filled.
#:
#: Recorded rather than inferred, because "what colour is this panel" has no
#: single answer for three of these five. A dotted ground flattened to one hex
#: is a different design; a gradient sampled at its midpoint is a colour that
#: appears nowhere on the page. `unsupported_pattern` is the honest outcome
#: when a fill is none of the others — it says "a human should look at this"
#: instead of quietly picking a plausible wrong colour.
FILL_TYPES = {
    "solid_color",
    "dot_pattern",
    "gradient",
    "image_texture",
    "unsupported_pattern",
}

#: What an element's outline actually is. A bounding box is the right answer
#: for a rectangle and a lie for anything else: a rounded tab squared off at
#: the corners, or a blob rendered as the box around it, is a different shape
#: in a way anybody looking at the page can see.
SHAPE_TYPES = {"rectangle", "rounded_rect", "ellipse", "blob"}

#: Numeric style fields and the range each is allowed. Both ends of every range
#: are still a design somebody might want; outside them the result is either
#: illegible or indistinguishable from a bug the agent then reports as
#: "my element disappeared".
NUMERIC_STYLE_RANGES: dict[str, tuple[float, float]] = {
    "font_size_ratio": (0.002, 0.6),
    "line_height": (0.5, 4.0),
    "letter_spacing_em": (-0.2, 2.0),
    "opacity": (0.0, 1.0),
    "border_radius_ratio": (0.0, 0.5),
    "border_width_ratio": (0.0, 0.1),
    "padding_ratio": (0.0, 0.25),
    #: Image framing: how far the picture is scaled up inside its box, and
    #: where it sits. Together these are the "crop" controls — CSS can express
    #: the result without the image ever being re-encoded.
    "image_scale": (1.0, 4.0),
    "image_offset_x": (-1.0, 1.0),
    "image_offset_y": (-1.0, 1.0),
    #: A dotted ground, kept as a pattern rather than flattened into one solid
    #: rectangle. Every measure is a fraction of the canvas's smaller side, the
    #: same scale font sizes use, so the pattern survives a change of output
    #: size instead of turning into specks or dinner plates.
    "dot_radius_ratio": (0.0002, 0.1),
    "dot_spacing_x_ratio": (0.001, 0.5),
    "dot_spacing_y_ratio": (0.001, 0.5),
}

STRING_STYLE_CHOICES: dict[str, set[str]] = {
    "font_weight": FONT_WEIGHTS,
    "font_family": FONT_FAMILIES,
    "text_align": TEXT_ALIGNMENTS,
    "vertical_align": VERTICAL_ALIGNMENTS,
    "font_style": FONT_STYLES,
    "text_transform": TEXT_TRANSFORMS,
    "text_decoration": TEXT_DECORATIONS,
    "object_fit": OBJECT_FITS,
    "object_position": OBJECT_POSITIONS,
    "border_style": BORDER_STYLES,
    "fill_type": FILL_TYPES,
    "shape_type": SHAPE_TYPES,
}

COLOR_STYLE_FIELDS = frozenset(
    {"color", "background_color", "border_color", "tint_color", "dot_color"}
)

#: A polygon needs at least a triangle; past a few dozen vertices it is
#: tracing noise rather than describing a cut edge, and every vertex is more
#: CSS for the renderer to parse.
MIN_CLIP_POINTS, MAX_CLIP_POINTS = 3, 64

#: Everything an element's ``style`` may contain. A key not listed is dropped
#: rather than rejected — see ``_validate_style``.
STYLE_FIELDS = (
    frozenset(NUMERIC_STYLE_RANGES)
    | frozenset(STRING_STYLE_CHOICES)
    | COLOR_STYLE_FIELDS
    | frozenset({"background_gradient", "format", "clip_polygon", "group_id"})
)


class DocumentValidationError(serializers.ValidationError):
    """Raised with an error map keyed by element id (or ``elements``)."""


def _fail(key: str, message) -> None:
    raise DocumentValidationError({key: [message]})


# ---------------------------------------------------------------------------
# Field validators
# ---------------------------------------------------------------------------


def _validate_color(key: str, field: str, value: Any) -> str:
    """A colour is a hex literal or a brand token. Nothing else, ever.

    This value lands inside a ``style="...:{value}"`` attribute in HTML that a
    browser then executes. ``red;background-image:url(https://elsewhere/x)`` is
    a valid-looking string and a data exfiltration path out of the renderer.
    Whitelisting the two shapes we actually support is the only check that
    holds.
    """
    if isinstance(value, str) and value.lower() in BRAND_COLOR_TOKENS:
        return value.lower()
    if not isinstance(value, str) or not HEX_COLOR.match(value.strip()):
        _fail(
            key,
            _("%(field)s must be a hex colour such as #1F2937, or a brand colour.")
            % {"field": field},
        )
    return value.strip()


def _validate_number(key: str, field: str, value: Any, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(key, _("%(field)s must be a number.") % {"field": field})
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        _fail(key, _("%(field)s must be a real number.") % {"field": field})
    if not (low <= number <= high):
        _fail(
            key,
            _("%(field)s must be between %(low)s and %(high)s.")
            % {"field": field, "low": low, "high": high},
        )
    return number


def _validate_image_key(key: str, value: Any) -> str:
    """Image content names a file in our own storage, never a URL.

    A URL here would be fetched by the renderer — our container, our egress,
    a destination the end user chose. Keys are resolved against storage.
    """
    if not isinstance(value, str):
        _fail(key, _("Image content must be a stored file key."))
    value = value.strip()
    if "://" in value or value.startswith("//"):
        _fail(key, _("Image content must be a stored file key, not a URL."))
    if ".." in value:
        _fail(key, _("Image content must not contain '..'."))
    return value


#: A group label is a plain slug the extractor invented — "group_3". Bounded
#: and character-restricted because it is the one style value that is neither a
#: colour, a number nor a fixed choice, and an unbounded string on an element is
#: how a document grows a payload nobody validates.
GROUP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def _validate_group_id(key: str, value: Any) -> str:
    """Which visual group this element belongs to, if any.

    Stored on the style rather than as its own column so a group survives the
    template-to-design copy without a migration — `style_properties` is already
    the bag that travels intact, and grouping is a property of the element in
    exactly the way a colour is.
    """
    text = str(value).strip().lower()
    if not GROUP_ID_RE.match(text):
        _fail(key, _("group_id must be a short slug."))
    return text


def _validate_style(key: str, raw: Any) -> dict:
    """Clean one element's style.

    Unknown keys are **dropped, not rejected**. This runs on every autosave of
    a whole document, and a client that learns a new style key before the
    server does should not have its entire save refused — the unknown key
    simply does not survive the round trip, which is visible and recoverable.
    A *known* key with a bad value is a different matter and does fail: that is
    the injection surface.
    """
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        _fail(key, _("style must be an object."))

    clean: dict[str, Any] = {}
    for field, value in raw.items():
        if field not in STYLE_FIELDS:
            continue
        if value is None:
            continue

        if field in COLOR_STYLE_FIELDS:
            clean[field] = _validate_color(key, field, value)
        elif field in NUMERIC_STYLE_RANGES:
            low, high = NUMERIC_STYLE_RANGES[field]
            clean[field] = _validate_number(key, field, value, low, high)
        elif field in STRING_STYLE_CHOICES:
            options = STRING_STYLE_CHOICES[field]
            if str(value) not in options:
                _fail(
                    key,
                    _("%(field)s must be one of: %(options)s.")
                    % {"field": field, "options": ", ".join(sorted(options))},
                )
            clean[field] = str(value)
        elif field == "group_id":
            clean[field] = _validate_group_id(key, value)
        elif field == "clip_polygon":
            clean[field] = _validate_clip_polygon(key, value)
        elif field == "background_gradient":
            text = str(value).strip()
            if not GRADIENT_RE.match(text):
                _fail(key, _("background_gradient must be a linear or radial gradient."))
            clean[field] = text
        elif field == "format":
            # Presentation hint for a bound numeric value; the same vocabulary
            # html_builder._format_value understands.
            if str(value) not in {"currency", "number", "upper", "list", ""}:
                _fail(key, _("format is not one this renderer understands."))
            clean[field] = str(value)

    return clean


def _validate_clip_polygon(key: str, raw: Any) -> list[float]:
    """A cut edge, as percentages of the element's own box.

    Stored as a flat ``[x1, y1, x2, y2, ...]`` list of plain numbers and
    *never* as a CSS string. That is the whole point: ``clip-path`` takes a
    function, and a function is a place a string could smuggle a ``url(...)``
    into the renderer — the same hole ``background_gradient`` is matched whole
    against a grammar to close. Numbers cannot express a URL, so
    ``html_builder`` formats the polygon itself and there is nothing to
    sanitise.

    Percentages rather than pixels because everything else about an element's
    geometry is a fraction of its box, and a shape measured in pixels would
    stop matching its element the moment the canvas changed size.
    """
    if not isinstance(raw, (list, tuple)):
        _fail(key, _("clip_polygon must be a list of numbers."))
    if len(raw) % 2:
        _fail(key, _("clip_polygon needs an x and a y for every point."))
    if not (MIN_CLIP_POINTS * 2 <= len(raw) <= MAX_CLIP_POINTS * 2):
        _fail(
            key,
            _("clip_polygon must have between %(low)s and %(high)s points.")
            % {"low": MIN_CLIP_POINTS, "high": MAX_CLIP_POINTS},
        )

    points: list[float] = []
    for value in raw:
        # Generously bounded rather than clamped to 0..100: a cut edge may run
        # outside the element's box, and CSS handles that fine.
        points.append(_validate_number(key, "clip_polygon", value, -1000.0, 1000.0))
    return points


def _validate_transform(key: str, raw: Any) -> dict:
    if not isinstance(raw, dict):
        _fail(key, _("transform must be an object with x, y, width and height."))

    transform = {
        "x": _validate_number(key, "transform.x", raw.get("x", 0.0), MIN_COORD, MAX_COORD),
        "y": _validate_number(key, "transform.y", raw.get("y", 0.0), MIN_COORD, MAX_COORD),
        "width": _validate_number(
            key, "transform.width", raw.get("width", 0.2), MIN_SIZE, MAX_SIZE
        ),
        "height": _validate_number(
            key, "transform.height", raw.get("height", 0.1), MIN_SIZE, MAX_SIZE
        ),
        "rotation": _validate_number(
            key, "transform.rotation", raw.get("rotation", 0.0), MIN_ROTATION, MAX_ROTATION
        ),
    }

    z_index = raw.get("z_index", 0)
    if isinstance(z_index, bool) or not isinstance(z_index, (int, float)):
        _fail(key, _("transform.z_index must be a whole number."))
    transform["z_index"] = max(0, min(MAX_Z_INDEX, int(z_index)))
    return transform


# ---------------------------------------------------------------------------
# Building elements
# ---------------------------------------------------------------------------


def new_element_id() -> str:
    return f"el-{uuid.uuid4().hex[:12]}"


#: Style keys a template element may carry that mean the same thing in the
#: document. Anything else on the template is dropped at copy time — better a
#: missing decoration than a value the new validator would reject on the very
#: first save the agent makes.
def _style_from_template(element) -> dict:
    raw = dict(element.style_properties or {})
    clean: dict[str, Any] = {}
    for field, value in raw.items():
        if field not in STYLE_FIELDS or value is None:
            continue
        try:
            cleaned = _validate_style("template", {field: value})
        except DocumentValidationError:
            # A template authored before these ranges existed is not an error
            # for the agent to see; it just does not carry that one value over.
            continue
        clean.update(cleaned)
    return clean


def element_from_template(element, index: int = 0) -> dict:
    """One template element, deep-copied into a design's own element.

    ``original_element_id`` is what makes "reset this element" possible later:
    it points back at the template element this was copied from, and survives
    reordering, renaming and duplication (a duplicate carries the same
    original, so resetting either copy restores the same source).
    """
    element_type = TYPE_FROM_TEMPLATE.get(element.element_type, TEXT_TYPE)
    geometry = dict(element.geometry or {})

    # Static graphics stop being a special type here: the template's own asset
    # is copied in as ordinary image content, so nothing downstream needs a
    # branch for it. See TYPE_FROM_TEMPLATE.
    #
    # Any image-carrying element may bring an asset across, not only a static
    # graphic. That is what an imported template needs: the photo region cut
    # out of the source artwork is copied in as content, so a design opens
    # looking like the flyer it came from — while `content_source` still points
    # at listing.photos[n], so attaching a property replaces it. The asset is
    # the floor, not the ceiling; see html_builder.resolve_content for which
    # of the two wins.
    content = ""
    if carries_image(element_type, None) or element.element_type == ElementType.STATIC_GRAPHIC:
        content = element.static_asset.name if element.static_asset else ""
    else:
        content = element.default_content or ""

    return {
        "id": new_element_id(),
        "original_element_id": element.key,
        "type": element_type,
        "name": element.label or element.key.replace("_", " ").title(),
        # The whole point of this rewrite: nothing arrives locked. What the
        # template used to call `permission` is not consulted, not copied and
        # not represented.
        "locked": False,
        "visible": True,
        "transform": {
            "x": float(geometry.get("x", 0.0)),
            "y": float(geometry.get("y", 0.0)),
            "width": float(geometry.get("width", 0.2)),
            "height": float(geometry.get("height", 0.1)),
            "rotation": float(geometry.get("rotation", 0.0)),
            "z_index": int(element.z_index or index),
        },
        "content": content,
        "content_source": element.content_source or "",
        "bound_to": binding_for_source(element.content_source),
        "manually_overridden": False,
        "style": _style_from_template(element),
    }


def elements_from_template(template) -> list[dict]:
    """The full element list a new design starts from."""
    return [
        element_from_template(element, index)
        for index, element in enumerate(template.elements.all())
    ]


#: Sensible starting geometry and style for each kind of element an agent can
#: add from the left panel. Centred horizontally so a new element lands
#: somewhere visible rather than in a corner.
BLANK_ELEMENTS: dict[str, dict] = {
    TEXT_TYPE: {
        "name": "Text",
        "transform": {"x": 0.15, "y": 0.42, "width": 0.7, "height": 0.1},
        "content": "Your text",
        "style": {"color": "#1F2937", "font_size_ratio": 0.05, "text_align": "center",
                  "vertical_align": "center", "font_weight": "600", "line_height": 1.2},
    },
    IMAGE_TYPE: {
        "name": "Image",
        "transform": {"x": 0.25, "y": 0.3, "width": 0.5, "height": 0.35},
        "style": {"object_fit": "cover", "object_position": "center center"},
    },
    SHAPE_TYPE: {
        "name": "Rectangle",
        "transform": {"x": 0.3, "y": 0.38, "width": 0.4, "height": 0.22},
        "style": {"background_color": "#8B4F24", "opacity": 1.0},
    },
    LINE_TYPE: {
        "name": "Line",
        "transform": {"x": 0.2, "y": 0.5, "width": 0.6, "height": 0.004},
        "style": {"background_color": "#1F2937"},
    },
    ICON_TYPE: {
        "name": "Icon",
        "transform": {"x": 0.44, "y": 0.44, "width": 0.12, "height": 0.12},
        "style": {"object_fit": "contain", "object_position": "center center"},
    },
    LOGO_TYPE: {
        "name": "Logo",
        "transform": {"x": 0.38, "y": 0.08, "width": 0.24, "height": 0.1},
        "content_source": "brokerage.logo",
        "style": {"object_fit": "contain", "object_position": "center center"},
    },
    BUTTON_TYPE: {
        "name": "Button",
        "transform": {"x": 0.32, "y": 0.72, "width": 0.36, "height": 0.08},
        "content": "Learn more",
        "style": {"background_color": "#8B4F24", "color": "#FFFFFF",
                  "font_size_ratio": 0.032, "font_weight": "700",
                  "text_align": "center", "vertical_align": "center",
                  "border_radius_ratio": 0.02},
    },
    BACKGROUND_TYPE: {
        "name": "Background",
        "transform": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "z_index": 0},
        "style": {"background_color": "#F7F3EC", "object_fit": "cover",
                  "object_position": "center center"},
    },
}


def new_element(kind: str, *, z_index: int = 0) -> dict:
    """A blank element of one type, ready to drop on the canvas."""
    if kind not in BLANK_ELEMENTS:
        raise DocumentValidationError(
            {"kind": [_("'%(kind)s' is not an element type.") % {"kind": kind}]}
        )
    blueprint = BLANK_ELEMENTS[kind]
    transform = {"rotation": 0.0, "z_index": z_index, **blueprint["transform"]}
    return {
        "id": new_element_id(),
        "original_element_id": None,
        "type": kind,
        "name": blueprint["name"],
        "locked": False,
        "visible": True,
        "transform": {
            "x": 0.0, "y": 0.0, "width": 0.2, "height": 0.1,
            "rotation": 0.0, "z_index": z_index,
            **transform,
        },
        "content": blueprint.get("content", ""),
        "content_source": blueprint.get("content_source", ""),
        "bound_to": binding_for_source(blueprint.get("content_source", "")),
        "manually_overridden": False,
        "style": dict(blueprint.get("style", {})),
    }


def duplicate_element(element: dict, *, offset: float = 0.02) -> dict:
    """A copy of one element, nudged so it does not hide under the original.

    Keeps ``original_element_id``: the copy came from the same template
    element, so "reset to template" is still a meaningful thing to do to it.
    """
    copy = {
        **element,
        "id": new_element_id(),
        "name": f"{element.get('name') or 'Element'} copy",
        "transform": dict(element.get("transform") or {}),
        "style": dict(element.get("style") or {}),
    }
    copy["transform"]["x"] = min(MAX_COORD, float(copy["transform"].get("x", 0.0)) + offset)
    copy["transform"]["y"] = min(MAX_COORD, float(copy["transform"].get("y", 0.0)) + offset)
    copy["transform"]["z_index"] = min(
        MAX_Z_INDEX, int(copy["transform"].get("z_index", 0)) + 1
    )
    return copy


# ---------------------------------------------------------------------------
# Document validation
# ---------------------------------------------------------------------------


def validate_element(raw: Any, *, seen_ids: set[str]) -> dict:
    """Clean one element. Raises on anything the renderer must not be handed."""
    if not isinstance(raw, dict):
        _fail("elements", _("Each element must be an object."))

    element_id = str(raw.get("id") or "").strip() or new_element_id()
    if len(element_id) > 64 or not re.match(r"^[\w-]+$", element_id):
        _fail("elements", _("Element ids must be short and alphanumeric."))
    if element_id in seen_ids:
        _fail(element_id, _("Two elements share the id '%(id)s'.") % {"id": element_id})
    seen_ids.add(element_id)

    element_type = str(raw.get("type") or "").strip()
    if element_type not in ELEMENT_TYPES:
        _fail(
            element_id,
            _("'%(type)s' is not an element type.") % {"type": element_type},
        )

    name = str(raw.get("name") or "").strip()[:MAX_NAME_LENGTH]

    content = raw.get("content", "")
    if content is None:
        content = ""
    if carries_image(element_type, content):
        content = _validate_image_key(element_id, content) if content else ""
    else:
        if not isinstance(content, str):
            content = str(content)
        if len(content) > MAX_TEXT_LENGTH:
            _fail(
                element_id,
                _("Text must be %(n)s characters or fewer.") % {"n": MAX_TEXT_LENGTH},
            )

    bound_to = raw.get("bound_to") or None
    if bound_to is not None:
        bound_to = str(bound_to)
        if bound_to not in PROPERTY_FIELDS_BY_NAME:
            _fail(
                element_id,
                _("'%(field)s' is not a property field.") % {"field": bound_to},
            )

    # A binding IS the content source. Deriving it rather than trusting the
    # client keeps the two from disagreeing — a payload claiming
    # bound_to=price with content_source=agent.phone would otherwise render one
    # thing and label itself another.
    if bound_to:
        content_source = source_for_binding(bound_to)
    else:
        content_source = str(raw.get("content_source") or "").strip()
        if content_source and not re.match(r"^[a-zA-Z_][\w.]*(?:\[\d+\])?$", content_source):
            _fail(element_id, _("content_source is not a valid data path."))

    return {
        "id": element_id,
        "original_element_id": (
            str(raw["original_element_id"])[:80]
            if raw.get("original_element_id")
            else None
        ),
        "type": element_type,
        "name": name,
        "locked": bool(raw.get("locked", False)),
        "visible": bool(raw.get("visible", True)),
        "transform": _validate_transform(element_id, raw.get("transform")),
        "content": content,
        "content_source": content_source,
        "bound_to": bound_to,
        "manually_overridden": bool(raw.get("manually_overridden", False)),
        "style": _validate_style(element_id, raw.get("style")),
    }


def validate_document(elements: Any) -> list[dict]:
    """Validate and normalise a whole element list.

    The server-side enforcement point. Note what it does *not* check: whether
    the caller was "allowed" to move, restyle or retype an element. That
    question no longer exists — the design is theirs. What it does check is
    that every value can be safely interpolated into HTML and handed to a
    browser, which was always the real reason those checks were there.
    """
    if elements in (None, ""):
        return []
    if not isinstance(elements, list):
        raise DocumentValidationError(
            {"elements": [_("elements must be a list.")]}
        )
    if len(elements) > MAX_ELEMENTS:
        raise DocumentValidationError(
            {
                "elements": [
                    _("A design cannot have more than %(n)s elements.")
                    % {"n": MAX_ELEMENTS}
                ]
            }
        )

    seen_ids: set[str] = set()
    return [validate_element(raw, seen_ids=seen_ids) for raw in elements]


# ---------------------------------------------------------------------------
# Ordering helpers — one implementation, used by canvas and layers alike
# ---------------------------------------------------------------------------


def sorted_for_render(elements: Iterable[dict]) -> list[dict]:
    """Back to front: index 0 paints first, so it sits at the bottom.

    Ties break on list order rather than id so that reordering is stable and
    predictable — two elements at the same z_index stay in the order the
    document lists them, rather than swapping around on each save.
    """
    return [
        element
        for _index, element in sorted(
            enumerate(elements),
            key=lambda pair: (
                int((pair[1].get("transform") or {}).get("z_index", 0)),
                pair[0],
            ),
        )
    ]


def normalise_z_order(elements: list[dict]) -> list[dict]:
    """Renumber z_index to 0..n-1 in current stacking order.

    Called after any reorder so the numbers stay dense and comparable. Without
    it, repeated "bring to front" walks the top element's z_index up towards
    the cap and eventually pins several elements together at it.
    """
    ordered = sorted_for_render(elements)
    for index, element in enumerate(ordered):
        element.setdefault("transform", {})["z_index"] = index
    return ordered
