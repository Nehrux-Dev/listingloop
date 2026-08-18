"""Read a PDF's own structure into a layout, without asking a model anything.

WHY THIS EXISTS ALONGSIDE THE VISION EXTRACTOR
------------------------------------------------------------------------------
``importing.extract_layout`` shows a picture of the page to a vision model and
asks it to measure what it sees. That is the only option for a JPG of a flyer,
and it is the wrong one for a PDF that was exported from a design tool — because
such a PDF already contains the answer. Every text run carries its own string,
box, size and colour; every photo carries its own placement rectangle; every
panel is a filled path with a colour. Rasterising that and asking a model to
guess it back is slower, costs money, needs an API key, and is less accurate
than simply reading it.

So: PDFs with real text go through here. Everything else still goes to the
model. The two produce the *same payload shape* — the one
``importing._extraction_schema`` describes — so normalisation, asset baking and
template building downstream cannot tell which one ran.

WHAT IT DELIBERATELY DOES NOT DO
------------------------------------------------------------------------------
It does not guess a semantic role for every element. A vision model can look at
a flyer and say "that is the hero photograph"; a content stream cannot. Bindings
are therefore only attached where the text itself is unambiguous — a currency
amount, a phone number, a URL — and everything else arrives unbound for the
admin to bind in the editor. Inventing bindings from weak signals would put a
listing's price into a decorative caption, which is worse than leaving it plain.

LAYERING
------------------------------------------------------------------------------
A PDF content stream is ordered, but its text, drawings and images come back
from three separate APIs with no shared sequence number that is reliable across
PyMuPDF versions. So the layers are rebuilt from what the shapes are rather than
from the order they were written:

    fills (largest first) -> images -> outlines -> text

which is the stacking every page of this kind actually has. It is a heuristic,
and it is the one place this module guesses.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Bands for the layering described above. Wide enough that no band can run
#: into the next on a page with a few hundred elements.
_Z_FILL, _Z_IMAGE, _Z_STROKE, _Z_TEXT = 0, 200, 400, 600

#: A fill covering this much of the page is the page's ground rather than a
#: panel on it, and is reported as `background` so a flat one becomes a colour
#: block instead of a full-page screenshot.
_PAGE_COVERAGE = 0.92

#: Below this, a fill is a hairline or an artefact of a rounded corner rather
#: than a panel worth carrying into the template. In PDF points.
_MIN_FILL_PT = 6.0

#: Text smaller than this is a legal footer set in agate, or stray marks. Kept
#: low because disclaimers genuinely are tiny.
_MIN_FONT_PT = 3.0

# -- shape and fill classification --------------------------------------------
#
# A bounding box is the right description of a rectangle and a lie about
# anything else, and one hex is the right description of a flat fill and a lie
# about a dotted or graded one. Both lies are the kind you can see on the page,
# so both are classified rather than assumed.

#: How square a curve-only path must be before it is called an ellipse. A
#: circle drawn as béziers has a bounding box within a hair of square; a blob
#: does not.
_ELLIPSE_ASPECT_TOLERANCE = 0.06

#: A rounded rectangle's corner arcs are small relative to the shape. Past this
#: fraction of the shorter side the curve is the shape rather than its corner,
#: which makes it a blob.
_MAX_CORNER_FRACTION = 0.5

#: Dots below this are a printing artefact; above it they are a design element
#: in their own right and should not be swallowed into a pattern. PDF points.
_MAX_DOT_PT = 14.0

#: How many evenly-spaced dots it takes before a scatter is a pattern. Five is
#: comfortably past a row of bullet points and short of a real grid.
_MIN_PATTERN_DOTS = 5

#: Mirrors importing._MIN_MASK_POINTS / _MAX_MASK_POINTS, which cap the outline
#: a blob may carry. Traced here so the thinning keeps the shape rather than
#: letting the cap lop off one whole side of it.
_MIN_MASK_POINTS, _MAX_MASK_POINTS = 3, 64

#: How far apart two dot spacings may be and still count as the same grid.
_SPACING_TOLERANCE_PT = 1.5

# -- binding detection --------------------------------------------------------
# Only patterns that cannot plausibly be anything else. See the docstring.
_PRICE_RE = re.compile(r"^[^\w]{0,3}[$£€₹]\s?\d[\d,.\s]*$")
_PHONE_RE = re.compile(r"^\+?[\d][\d\s\-().]{6,20}$")
_URL_RE = re.compile(r"^(?:https?://|www\.)\S+$", re.I)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_ADDRESS_RE = re.compile(
    r"\d+\s+\w.*\b(st|street|ave|avenue|rd|road|blvd|lane|ln|drive|dr|terrace|way|court|ct)\b",
    re.I,
)

#: PyMuPDF span flag bits. Only the three that change how type is set.
_FLAG_ITALIC, _FLAG_SERIF, _FLAG_BOLD = 1 << 1, 1 << 2, 1 << 4


@dataclass
class _Box:
    x: float
    y: float
    w: float
    h: float


def _blank_style() -> dict:
    """Every style key the strict schema requires, all unset."""
    return {
        "color": "",
        "background_color": "",
        "font_size_px": 0,
        "font_weight": "",
        "font_family": "",
        "text_align": "",
        "text_transform": "none",
        "line_height": 0,
        "opacity": 1,
        "border_radius_px": 0,
        "border_width_px": 0,
        "border_color": "",
        "gradient": "",
    }


def _element(eid: str, kind: str, role: str, box: _Box, z: int, **over) -> dict:
    element = {
        "id": eid,
        "type": kind,
        "role": role,
        "binding": "",
        "text": "",
        "mask": [],
        "transform": {
            "x": round(box.x, 2),
            "y": round(box.y, 2),
            "width": round(box.w, 2),
            "height": round(box.h, 2),
            "rotation": 0,
            "z_index": z,
        },
        "style": _blank_style(),
    }
    style = over.pop("style", None)
    element.update(over)
    if style:
        element["style"].update(style)
    return element


def _hex_from_floats(fill) -> str:
    """PyMuPDF gives fills as (r, g, b) floats in 0..1."""
    if not fill:
        return ""
    try:
        red, green, blue = (max(0, min(255, round(float(c) * 255))) for c in fill[:3])
    except (TypeError, ValueError):
        return ""
    return f"#{red:02X}{green:02X}{blue:02X}"


def _hex_from_int(value) -> str:
    """PyMuPDF gives text colour as a packed 0xRRGGBB integer."""
    try:
        packed = int(value)
    except (TypeError, ValueError):
        return ""
    return f"#{(packed >> 16) & 255:02X}{(packed >> 8) & 255:02X}{packed & 255:02X}"


def classify_shape(drawing) -> tuple[str, float]:
    """What this path actually is, and its corner radius in PDF points.

    Read from the path's own operators rather than guessed from its box:

      ``re`` only            a rectangle
      ``c`` only, square     an ellipse — a circle is a rounded rect whose
                             radius is half its side, which is exactly how it
                             is then rendered
      ``re`` with ``c``      a rounded rectangle; the arcs are its corners
      anything else          a blob, whose outline the caller traces

    The radius is derived from the corner arc's own extent, not assumed: two
    templates with visibly different corner softness should not come back
    identical.
    """
    ops = {item[0] for item in drawing.get("items", [])}
    rect = drawing["rect"]
    short_side = min(rect.width, rect.height)

    if ops <= {"re"}:
        return "rectangle", 0.0

    if ops <= {"c"} and short_side > 0:
        aspect = abs(rect.width - rect.height) / max(rect.width, rect.height)
        if aspect <= _ELLIPSE_ASPECT_TOLERANCE:
            return "ellipse", short_side / 2
        return "blob", 0.0

    if "re" in ops and "c" in ops:
        return "rounded_rect", _corner_radius(drawing, short_side)

    # Straight segments joined by arcs: a rounded rectangle drawn without the
    # `re` operator, which is how most design tools emit one.
    if ops <= {"c", "l"} and short_side > 0:
        radius = _corner_radius(drawing, short_side)
        if 0 < radius <= short_side * _MAX_CORNER_FRACTION:
            return "rounded_rect", radius

    return "blob", 0.0


def _corner_radius(drawing, short_side: float) -> float:
    """The extent of the shape's largest corner arc, in points.

    Each `c` item is a cubic segment given as (op, p1, p2, p3, p4). The span of
    its endpoints is how far the curve travels, which for a corner arc is the
    radius. The largest is taken because a shape may mix a tight corner with a
    long flat edge expressed as a curve.
    """
    spans = []
    for item in drawing.get("items", []):
        if item[0] != "c" or len(item) < 5:
            continue
        start, end = item[1], item[4]
        spans.append(max(abs(end.x - start.x), abs(end.y - start.y)))
    if not spans:
        return 0.0
    return min(max(spans), short_side * _MAX_CORNER_FRACTION)


def _trace_outline(drawing, rect) -> list[float]:
    """A blob's visible edge, as a flat ``[x1, y1, x2, y2, ...]`` list.

    Page points, which ``normalise_elements`` converts to percentages of the
    element's own box — the same route the vision extractor's masks take, so a
    blob from either reader clips identically.

    Deliberately a polygon of numbers and not an SVG path. ``clip-path`` takes
    a function and a function is a place a ``url(...)`` could reach the
    renderer; that hole is closed by never accepting a string. The cost is that
    a curve becomes a many-sided polygon, which at render size is a difference
    nobody can see.
    """
    points: list[float] = []
    for item in drawing.get("items", []):
        op = item[0]
        if op == "l" and len(item) >= 3:
            points.extend([item[1].x, item[1].y, item[2].x, item[2].y])
        elif op == "c" and len(item) >= 5:
            # Endpoints and control points both: the controls pull the curve
            # away from the chord, so including them keeps the traced shape
            # close to the drawn one without evaluating any béziers.
            for point in item[1:5]:
                points.extend([point.x, point.y])
        elif op == "re" and len(item) >= 2:
            box = item[1]
            points.extend(
                [box.x0, box.y0, box.x1, box.y0, box.x1, box.y1, box.x0, box.y1]
            )
    if len(points) < _MIN_MASK_POINTS * 2:
        return []
    # `_mask_points` caps the vertex count; thinning here keeps the shape's
    # overall form rather than letting it keep the first N points and lose one
    # whole side of the blob.
    pairs = list(zip(points[0::2], points[1::2]))
    if len(pairs) > _MAX_MASK_POINTS:
        step = len(pairs) / _MAX_MASK_POINTS
        pairs = [pairs[min(int(i * step), len(pairs) - 1)] for i in range(_MAX_MASK_POINTS)]
    return [value for pair in pairs for value in pair]


def find_dot_pattern(candidates: list) -> dict | None:
    """A regular grid of dots, described so it can be redrawn as a pattern.

    Returns the dot's colour, its radius and the grid's spacing, or None when
    the shapes are not a grid.

    This exists because the alternative is worse in both directions. Flattening
    a dotted ground into one solid rectangle changes the design; leaving the
    dots as hundreds of individual elements gives the agent a canvas they
    cannot select anything on. A pattern is what the artwork actually is.

    Spacing is read as the smallest gap between neighbours on each axis, which
    is the grid pitch even when the dots are not in perfect rows.
    """
    if len(candidates) < _MIN_PATTERN_DOTS:
        return None

    xs = sorted({round(item["rect"].x0, 1) for item in candidates})
    ys = sorted({round(item["rect"].y0, 1) for item in candidates})
    if len(xs) < 2 and len(ys) < 2:
        return None

    def pitch(values: list[float]) -> float:
        gaps = [b - a for a, b in zip(values, values[1:]) if b - a > 0.5]
        if not gaps:
            return 0.0
        smallest = min(gaps)
        # Every gap must be a whole multiple of the smallest, or this is a
        # scatter of shapes that merely happen to be the same size.
        for gap in gaps:
            if abs(round(gap / smallest) * smallest - gap) > _SPACING_TOLERANCE_PT:
                return 0.0
        return smallest

    spacing_x = pitch(xs) if len(xs) > 1 else 0.0
    spacing_y = pitch(ys) if len(ys) > 1 else 0.0
    if spacing_x <= 0 and spacing_y <= 0:
        return None

    widths = [item["rect"].width for item in candidates]
    radius = sum(widths) / len(widths) / 2
    return {
        "dot_color": candidates[0]["colour"],
        "dot_radius_pt": radius,
        # A single row or column still tiles: the missing axis takes the dot's
        # own size, so the pattern repeats without inventing a second gap.
        "spacing_x_pt": spacing_x or radius * 2,
        "spacing_y_pt": spacing_y or radius * 2,
        "grid_cols": len(xs),
        "grid_rows": len(ys),
    }


def _binding_for(text: str) -> str:
    """A binding only where the string can be nothing else."""
    stripped = text.strip()
    if _PRICE_RE.match(stripped):
        return "price"
    if _URL_RE.match(stripped):
        return "brokerage_website"
    if _EMAIL_RE.match(stripped):
        return "agent_email"
    if _PHONE_RE.match(stripped) and sum(c.isdigit() for c in stripped) >= 7:
        return "brokerage_phone"
    if _ADDRESS_RE.search(stripped):
        return "address"
    return ""


def _family_for(flags: int) -> str:
    """What the PDF says about the face, in the vocabulary a template speaks.

    A content stream cannot tell us "this is calligraphy" — Type3 subset fonts,
    which is what design tools emit, carry no usable family name at all. So a
    serif flag becomes `serif` and everything else becomes `body`, and a script
    headline is one thing the admin re-picks in the editor.
    """
    return "serif" if flags & _FLAG_SERIF else "body"


def is_text_pdf(data: bytes) -> bool:
    """True when the first page carries real text rather than being a scan.

    The deciding question for which extractor to use. A PDF that is one big
    photograph of a flyer has nothing to read and must go to the model.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - depends on the installed wheel
        try:
            import fitz as pymupdf
        except ImportError:
            return False
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.page_count == 0:
                return False
            return bool(document.load_page(0).get_text("text").strip())
    except Exception:
        logger.warning("Could not inspect PDF for text", exc_info=True)
        return False


def extract_pdf_layout(data: bytes, page_width: int, page_height: int) -> dict:
    """The first page's own structure, in the extractor payload shape.

    ``page_width``/``page_height`` are the *raster* dimensions the rest of the
    import works in, so everything here is scaled into that space and the
    geometry lines up with the crops baked from that same raster.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as document:
        page = document.load_page(0)
        rect = page.rect
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError("The first page has no size.")

        scale_x = page_width / rect.width
        scale_y = page_height / rect.height
        page_area = rect.width * rect.height

        def box_of(raw) -> _Box:
            left, top, right, bottom = raw
            return _Box(
                x=left * scale_x,
                y=top * scale_y,
                w=(right - left) * scale_x,
                h=(bottom - top) * scale_y,
            )

        elements: list[dict] = []
        background = "#FFFFFF"

        # -- filled panels ---------------------------------------------------
        fills = []
        dots: list[dict] = []
        for order, drawing in enumerate(page.get_drawings()):
            shape = drawing.get("rect")
            if shape is None:
                continue
            width, height = shape.width, shape.height
            colour = _hex_from_floats(drawing.get("fill"))

            # Small, filled, same-sized shapes are set aside before the size
            # filter below can discard them: individually they are beneath
            # notice, and together they may be the page's ground.
            if (
                colour
                and drawing.get("type") == "f"
                and width <= _MAX_DOT_PT
                and height <= _MAX_DOT_PT
                and abs(width - height) <= 1.0
            ):
                dots.append({"rect": shape, "colour": colour})
                continue

            if width < _MIN_FILL_PT or height < _MIN_FILL_PT:
                continue
            fills.append((width * height, order, drawing))

        # Grouped by colour: two different dotted grounds on one page are two
        # patterns, and merging them would average a colour that is on neither.
        by_colour: dict[str, list[dict]] = defaultdict(list)
        for dot in dots:
            by_colour[dot["colour"]].append(dot)

        pattern_index = 0
        for colour, group in by_colour.items():
            pattern = find_dot_pattern(group)
            if pattern is None:
                # Not a grid. Put them back as ordinary shapes rather than
                # dropping them — a handful of small marks is still artwork.
                for dot in group:
                    box = box_of(dot["rect"])
                    if box.w >= 1 and box.h >= 1:
                        elements.append(
                            _element(
                                f"mark_{len(elements)}",
                                "shape",
                                "mark",
                                box,
                                _Z_FILL + 1,
                                style={
                                    "background_color": colour,
                                    "fill_type": "solid_color",
                                    "shape_type": "ellipse",
                                    "border_radius_px": min(box.w, box.h) / 2,
                                },
                            )
                        )
                continue

            left = min(item["rect"].x0 for item in group)
            top = min(item["rect"].y0 for item in group)
            right = max(item["rect"].x1 for item in group)
            bottom = max(item["rect"].y1 for item in group)
            elements.append(
                _element(
                    f"dots_{pattern_index}",
                    "shape",
                    "dot_pattern",
                    box_of((left, top, right, bottom)),
                    _Z_FILL + 1,
                    style={
                        "fill_type": "dot_pattern",
                        "dot_color": pattern["dot_color"],
                        "dot_radius_px": pattern["dot_radius_pt"] * scale_y,
                        "dot_spacing_x_px": pattern["spacing_x_pt"] * scale_x,
                        "dot_spacing_y_px": pattern["spacing_y_pt"] * scale_y,
                    },
                )
            )
            pattern_index += 1

        # A page-covering fill is the ground, and there is often more than one:
        # design tools lay a white sheet down and paint the real colour over it.
        # Size cannot separate those — they are both the whole page — so the
        # ground is the LAST one in paint order, which is the one you can see.
        # The sheets underneath are dropped; nothing ever shows them.
        covering = [item for item in fills if item[0] >= page_area * _PAGE_COVERAGE]
        ground_order = max((order for _, order, _ in covering), default=None)

        # Largest first, so a panel drawn on top of a bigger panel lands above
        # it. Ties broken by position to keep the output stable across runs.
        fills.sort(key=lambda item: (-item[0], item[2]["rect"].y0, item[2]["rect"].x0))

        stroke_index = 0
        for index, (area, order, drawing) in enumerate(fills):
            shape = drawing["rect"]
            colour = _hex_from_floats(drawing.get("fill"))
            covers_page = area >= page_area * _PAGE_COVERAGE
            if covers_page and order != ground_order:
                # A sheet underneath the visible ground. See above.
                continue

            if drawing.get("type") == "s" or not colour:
                # An outline with no fill: a photo frame or a rule box. Carried
                # as a bordered shape, because dropping it loses the frame and
                # filling it would paint over whatever it surrounds.
                edge = _hex_from_floats(drawing.get("color"))
                if not edge:
                    # Filled, but with neither a flat colour nor a stroke — a
                    # shading or a tiling pattern, which this reader cannot
                    # describe.
                    #
                    # It used to be dropped here, and that was the worst of the
                    # three options: the shape simply vanished from the template
                    # with nothing to say it ever existed, so the first anyone
                    # knew was noticing the flyer looked wrong. Guessing a flat
                    # colour is the second worst. Keeping the box and marking it
                    # unclassified is the honest one — it survives as something
                    # to fix, and the import reports it for review.
                    unknown_shape, unknown_radius = classify_shape(drawing)
                    unknown_style = {
                        "fill_type": "unsupported_pattern",
                        "shape_type": unknown_shape,
                    }
                    if unknown_radius > 0:
                        unknown_style["border_radius_px"] = unknown_radius * scale_y
                    elements.append(
                        _element(
                            f"unclassified_{stroke_index}",
                            "shape",
                            "unclassified_fill",
                            box_of(shape),
                            min(_Z_FILL + 1 + index, _Z_IMAGE - 1),
                            style=unknown_style,
                        )
                    )
                    stroke_index += 1
                    continue
                width_pt = drawing.get("width") or 1.0
                outline_shape, outline_radius = classify_shape(drawing)
                outline_style = {
                    "border_width_px": max(1.0, float(width_pt) * scale_x),
                    "border_color": edge,
                    # No interior at all — an outline is the whole element. Said
                    # explicitly so nothing downstream reads a missing fill as
                    # "solid, colour unknown" and paints a slab.
                    "fill_type": "solid_color",
                    "shape_type": outline_shape,
                }
                if outline_radius > 0:
                    outline_style["border_radius_px"] = outline_radius * scale_y
                elements.append(
                    _element(
                        f"outline_{stroke_index}",
                        "shape",
                        "outline",
                        box_of(shape),
                        _Z_STROKE + stroke_index,
                        style=outline_style,
                    )
                )
                stroke_index += 1
                continue

            if covers_page:
                # The page's ground. Reported as `background` so a flat colour
                # becomes a colour block rather than a crop of the whole page.
                background = colour
                elements.append(
                    _element(
                        f"ground_{index}",
                        "background",
                        "page_background",
                        box_of(shape),
                        _Z_FILL,
                        style={
                            "background_color": colour,
                            "fill_type": "solid_color",
                            "shape_type": "rectangle",
                        },
                    )
                )
                continue

            # What the path is, not what its box is. A rounded tab squared off
            # at the corners is a different shape to anyone looking at it.
            shape_type, radius_pt = classify_shape(drawing)
            style = {
                "background_color": colour,
                "fill_type": "solid_color",
                "shape_type": shape_type,
            }
            if radius_pt > 0:
                style["border_radius_px"] = radius_pt * scale_y
            if shape_type == "blob":
                # Traced as an outline of plain numbers, never as an SVG path
                # string: `clip-path` takes a function, and a function is where
                # a `url(...)` could be smuggled into the renderer. The polygon
                # says the same thing and cannot express one.
                outline = _trace_outline(drawing, shape)
                if outline:
                    style["mask_points"] = outline

            elements.append(
                _element(
                    f"panel_{index}",
                    "shape",
                    # Stays "panel": `role` is what the element is *for*, and
                    # the shape it happens to be is a style property. Putting
                    # the geometry here instead would leave nothing describing
                    # the element's purpose.
                    "panel",
                    box_of(shape),
                    min(_Z_FILL + 1 + index, _Z_IMAGE - 1),
                    mask=style.pop("mask_points", []),
                    style=style,
                )
            )

        # -- placed images ---------------------------------------------------
        # In document order: an overlay wash sits directly on the photograph it
        # fades, and reordering them by size would put it underneath.
        photos = list(page.get_image_info())
        ranked = sorted(
            range(len(photos)),
            key=lambda i: -(
                (photos[i]["bbox"][2] - photos[i]["bbox"][0])
                * (photos[i]["bbox"][3] - photos[i]["bbox"][1])
            ),
        )
        # The largest picture is the hero; the rest take photo_2.. in reading
        # order. Only five slots exist, and anything past them stays unbound.
        slot_of: dict[int, str] = {}
        for slot, image_index in enumerate(ranked[:5], start=1):
            slot_of[image_index] = f"photo_{slot}"

        for index, info in enumerate(photos):
            elements.append(
                _element(
                    f"image_{index}",
                    "image",
                    "photo",
                    box_of(info["bbox"]),
                    _Z_IMAGE + index,
                    binding=slot_of.get(index, ""),
                )
            )

        # -- text ------------------------------------------------------------
        text_index = 0
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans") or []
                # Design tools split one visual line into a span per glyph run,
                # so "ECO", "-", "CONSCIOUS DESIGN" arrive separately. Joining
                # per line is what turns them back into the words on the page.
                text = "".join(span.get("text", "") for span in spans)
                if not text.strip():
                    continue
                lead = max(spans, key=lambda s: s.get("size", 0))
                size_pt = float(lead.get("size", 0))
                if size_pt < _MIN_FONT_PT:
                    continue

                flags = int(lead.get("flags", 0))
                style = {
                    "color": _hex_from_int(lead.get("color")) or "#000000",
                    "font_size_px": size_pt * scale_y,
                    "font_weight": "700" if flags & _FLAG_BOLD else "400",
                    "font_family": _family_for(flags),
                    "text_align": "left",
                    "line_height": 1.2,
                }
                elements.append(
                    _element(
                        f"text_{text_index}",
                        "text",
                        "text",
                        box_of(line["bbox"]),
                        _Z_TEXT + text_index,
                        text=text.strip(),
                        binding=_binding_for(text),
                        style=style,
                    )
                )
                text_index += 1

    if not elements:
        raise ValueError("Nothing could be read from that PDF's first page.")

    return {
        "page": {
            "background_color": background,
            "suggested_name": _suggested_name(elements),
            # The coordinate space every number above is measured in. Carried
            # with them because geometry measured against one size and applied
            # against another is wrong in a way no validation catches.
            "width": page_width,
            "height": page_height,
        },
        "elements": elements,
    }


def _suggested_name(elements: list[dict]) -> str:
    """The biggest piece of type on the page, which is its headline."""
    headings = [
        element
        for element in elements
        if element["type"] == "text" and element["text"].strip()
    ]
    if not headings:
        return "Imported template"
    biggest = max(headings, key=lambda e: e["style"].get("font_size_px", 0))
    return " ".join(biggest["text"].split())[:80] or "Imported template"
