"""Re-lay a design out for a different output format.

WHY FRACTIONAL GEOMETRY IS NOT ENOUGH ON ITS OWN
=============================================================================
Geometry is stored as fractions of the canvas, so one document renders at
every dimension — but by *stretching*: an element half the width of a square
Instagram post is also half the width of a LinkedIn banner that is twice as
wide as it is tall. Boxes change shape with the canvas while type (scaled by
the shorter side — see ``html_builder.type_scale_reference``) does not, which
is exactly the mismatch that squashes a flyer opened wide.

This module produces a *new* set of transforms for a target format, using the
recipe every magic-resize tool converges on, with no model call — the same
"structural is free and exact" principle as ``pdf_extraction``:

1.  **Uniform CONTAIN scale.** Every box scales by one factor — the smaller
    of the two axis ratios — so shapes keep their proportions AND the scaled
    content is guaranteed to fit both axes. The first version used the
    shorter-side ratio instead, which is only safe when no axis compresses
    harder than that: adapting an A4 flyer (1414x2000) to a square post
    scaled boxes to 76% while the height only had room for 54%, so fifteen
    hundred pixels of layout were stacked into a thousand and the result was
    elements piled on top of each other. ``min`` of the axis ratios is the
    largest scale that cannot overfill anything; the axis with room to spare
    is what anchoring (rule 2) distributes.

    Because boxes may now scale by less than the shorter-side ratio that
    *type* scales by (``type_scale_reference``), the min-side-referenced
    style ratios — ``font_size_ratio`` and friends — are multiplied by the
    same correction, so text keeps exactly the same relationship to its box.
    In the common case where the shorter-side ratio already fits (a square
    post onto a LinkedIn banner), the correction is 1 and style passes
    through untouched.

2.  **Edge anchoring.** A box is re-positioned by which third of the canvas
    its centre sits in: the left/top third keeps its scaled margin to that
    edge, the right/bottom third to the opposite edge, and the middle third
    keeps its fractional centre. A logo snug in a corner stays snug in that
    corner instead of drifting toward the middle of a wider canvas.

3.  **Full-span stretch.** The one thing that *should* stretch is an element
    covering (almost) the whole of an axis — a background, a full-width band.
    Covering is its job; per axis, a spanning element keeps its fractional
    coordinates. A background photo stays full-bleed and its ``object-fit:
    cover`` does the cropping, which is the correct retargeting for photos.

4.  **Clusters move as one.** Elements that overlap or nearly touch (an icon
    and its label, a badge on a photo) are grouped; the group's bounding box
    is anchored as a unit and members keep their scaled offsets inside it, so
    lockups cannot be torn apart by their members straddling an anchor
    boundary. The exception: when a group's bounding box itself spans an axis
    (a full-width row of feature badges), the members keep their own
    fractional *centres* on that axis — the row spreads out across the wider
    canvas, each badge undistorted.

The output is an ordinary document: same schema, same limits, hand-editable
afterwards. Adaptation runs once, server-side, when a design is copied for a
format — never live in the editor — so the editor, renderer and export all
read the same stored numbers and no fourth parity surface exists.
"""

from __future__ import annotations

import copy

from apps.templates.dimensions import Dimension
from apps.templates.document import (
    MAX_COORD,
    MAX_SIZE,
    MIN_COORD,
    MIN_SIZE,
    NUMERIC_STYLE_RANGES,
)

#: Fraction of an axis a box must cover to count as "spanning" it — full-bleed
#: backgrounds and edge-to-edge bands, with room for a bleed margin either way.
SPAN_FRACTION = 0.90

#: How close (as a fraction of the canvas's shorter side) two boxes may be and
#: still cluster. Zero would split an icon from a label drawn 4px away from it;
#: anything much bigger glues the whole design into one group.
CLUSTER_GAP_FRACTION = 0.015

#: Style ratios measured against the canvas's shorter side (see the
#: ``* scale_ref`` sites in ``html_builder``). When the contain scale is
#: smaller than the shorter-side ratio, these must shrink with the boxes or
#: the type/borders/dots would outgrow them.
_MIN_SIDE_STYLE_RATIOS = (
    "font_size_ratio",
    "border_radius_ratio",
    "border_width_ratio",
    "padding_ratio",
    "dot_radius_ratio",
    "dot_spacing_x_ratio",
    "dot_spacing_y_ratio",
)


class _Box:
    """A mutable pixel-space box, so the placement math reads as geometry."""

    __slots__ = ("left", "top", "width", "height")

    def __init__(self, left: float, top: float, width: float, height: float):
        self.left = left
        self.top = top
        self.width = width
        self.height = height

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height


def _page_height(dimension: Dimension) -> float:
    """The height elements are actually laid out in: the safe area.

    Document ``y``/``height`` are fractions of the area *between* the safe
    insets (see ``element_html``), so this module anchors against that page,
    not the raw canvas — an element at the top of a square post lands at the
    top of a Story's safe area, not underneath the platform's own chrome.
    """
    return (1.0 - dimension.safe_inset_top - dimension.safe_inset_bottom) * dimension.height


def _pixel_box(transform: dict, dimension: Dimension) -> _Box:
    """Fractions to safe-page pixels — the same axes ``element_html`` lays
    out in, minus the constant inset offset, which anchoring never needs."""
    page_height = _page_height(dimension)
    return _Box(
        left=float(transform.get("x", 0.0)) * dimension.width,
        top=float(transform.get("y", 0.0)) * page_height,
        width=float(transform.get("width", 0.2)) * dimension.width,
        height=float(transform.get("height", 0.1)) * page_height,
    )


def _fractions(box: _Box, dimension: Dimension) -> dict:
    """Pixels back to the document's fractional space, clamped to the same
    limits ``validate_document`` enforces so the output is always saveable."""
    page_height = _page_height(dimension)

    def clamp(value: float, low: float, high: float) -> float:
        return min(max(value, low), high)

    return {
        "x": clamp(box.left / dimension.width, MIN_COORD, MAX_COORD),
        "y": clamp(box.top / page_height, MIN_COORD, MAX_COORD),
        "width": clamp(box.width / dimension.width, MIN_SIZE, MAX_SIZE),
        "height": clamp(box.height / page_height, MIN_SIZE, MAX_SIZE),
    }


def _place_axis(
    left: float,
    size: float,
    source_len: float,
    target_len: float,
    scale: float,
    spans: bool,
) -> tuple[float, float]:
    """One axis of the placement rule: stretch when spanning, otherwise scale
    uniformly and anchor by which third of the axis the centre sits in."""
    if spans:
        return left / source_len * target_len, size / source_len * target_len

    scaled = size * scale
    center = (left + size / 2.0) / source_len
    if center < 1.0 / 3.0:
        new_left = left * scale
    elif center > 2.0 / 3.0:
        new_left = target_len - (source_len - left - size) * scale - scaled
    else:
        new_left = center * target_len - scaled / 2.0
    return new_left, scaled


def _overlaps(a: _Box, b: _Box, gap: float) -> bool:
    """Whether two boxes touch, expanded by ``gap`` px on every side."""
    return (
        a.left - gap < b.right
        and b.left - gap < a.right
        and a.top - gap < b.bottom
        and b.top - gap < a.bottom
    )


def _clusters(indexes: list[int], boxes: dict[int, _Box], gap: float) -> list[list[int]]:
    """Group overlapping/near-touching boxes, via union-find on pairs."""
    parent = {index: index for index in indexes}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for position, first in enumerate(indexes):
        for second in indexes[position + 1 :]:
            if _overlaps(boxes[first], boxes[second], gap):
                parent[find(first)] = find(second)

    groups: dict[int, list[int]] = {}
    for index in indexes:
        groups.setdefault(find(index), []).append(index)
    return list(groups.values())


def adapt_elements(
    elements: list[dict], source: Dimension, target: Dimension
) -> list[dict]:
    """A deep copy of ``elements`` with transforms re-laid-out for ``target``.

    Geometry changes (``x``/``y``/``width``/``height``); rotation, z-order,
    content, bindings and identity pass through untouched. Style passes
    through except the min-side-referenced ratios, which are corrected by the
    same factor the boxes scaled by relative to the type scale — 1, a no-op,
    whenever the shorter-side ratio already fits both axes (see the module
    docstring).
    """
    adapted = copy.deepcopy(elements)
    if source.key == target.key or not adapted:
        return adapted

    source_page_h = _page_height(source)
    target_page_h = _page_height(target)
    # CONTAIN: the largest uniform scale at which the whole layout still fits
    # both axes. Anything larger overfills the tighter axis and the layout
    # piles up on itself — see the module docstring for the flyer-to-square
    # failure that proved it.
    scale = min(target.width / source.width, target_page_h / source_page_h)
    # How far the box scale fell short of the shorter-side ratio type scales
    # by. Applied to font/border/dot ratios below so they track their boxes.
    ratio_correction = scale * min(source.width, source.height) / min(
        target.width, target.height
    )
    boxes = {
        index: _pixel_box(element.get("transform") or {}, source)
        for index, element in enumerate(adapted)
    }
    spans_x = {
        index: box.width >= SPAN_FRACTION * source.width for index, box in boxes.items()
    }
    spans_y = {
        index: box.height >= SPAN_FRACTION * source_page_h
        for index, box in boxes.items()
    }

    # Spanning elements never cluster: a background overlaps everything and
    # would glue the whole document into one group, defeating anchoring.
    free = [index for index in boxes if not spans_x[index] and not spans_y[index]]
    gap = CLUSTER_GAP_FRACTION * min(source.width, source.height)
    groups = _clusters(free, boxes, gap)
    # Elements that span an axis adapt alone, by the per-axis rule.
    groups.extend([index] for index in boxes if index not in free)

    placed: dict[int, _Box] = {}
    for group in groups:
        lefts = [boxes[index].left for index in group]
        tops = [boxes[index].top for index in group]
        bbox = _Box(
            left=min(lefts),
            top=min(tops),
            width=max(boxes[index].right for index in group) - min(lefts),
            height=max(boxes[index].bottom for index in group) - min(tops),
        )
        one = len(group) == 1
        bbox_spans_x = spans_x[group[0]] if one else bbox.width >= SPAN_FRACTION * source.width
        bbox_spans_y = spans_y[group[0]] if one else bbox.height >= SPAN_FRACTION * source_page_h

        new_left, _ = _place_axis(
            bbox.left, bbox.width, source.width, target.width, scale, bbox_spans_x
        )
        new_top, _ = _place_axis(
            bbox.top, bbox.height, source_page_h, target_page_h, scale, bbox_spans_y
        )

        for index in group:
            box = boxes[index]
            if one:
                # A lone element takes the axis rule directly — including the
                # fractional stretch when it spans (backgrounds, bands).
                left, width = _place_axis(
                    box.left, box.width, source.width, target.width, scale, bbox_spans_x
                )
                top, height = _place_axis(
                    box.top, box.height, source_page_h, target_page_h, scale, bbox_spans_y
                )
            else:
                # Cluster members scale uniformly. Normally they keep their
                # scaled offset inside the anchored group box; on an axis the
                # GROUP spans (a full-width row of badges), each member keeps
                # its own fractional centre instead, so the row spreads across
                # the new canvas rather than bunching at one end.
                width, height = box.width * scale, box.height * scale
                if bbox_spans_x:
                    left = (box.left + box.width / 2) / source.width * target.width - width / 2
                else:
                    left = new_left + (box.left - bbox.left) * scale
                if bbox_spans_y:
                    top = (box.top + box.height / 2) / source_page_h * target_page_h - height / 2
                else:
                    top = new_top + (box.top - bbox.top) * scale
            placed[index] = _Box(left=left, top=top, width=width, height=height)

    for index, element in enumerate(adapted):
        transform = element.setdefault("transform", {})
        transform.update(_fractions(placed[index], target))

    # The guard is not an optimisation: in the fits-already case the float
    # correction is 1.0 within an epsilon, and multiplying every ratio by
    # 1.0000000000000002 would dirty values that should pass through exact.
    if abs(ratio_correction - 1.0) > 1e-9:
        for element in adapted:
            style = element.get("style")
            if not isinstance(style, dict):
                continue
            for key in _MIN_SIDE_STYLE_RATIOS:
                value = style.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                low, high = NUMERIC_STYLE_RANGES[key]
                style[key] = min(max(float(value) * ratio_correction, low), high)
    return adapted
