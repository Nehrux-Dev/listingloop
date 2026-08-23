/**
 * The shape and frame primitives the Elements panel can place — defined
 * locally, in the document's own vocabulary, so a dropped shape is an
 * ordinary element from the first frame.
 *
 * WHY LOCAL RECIPES WHEN `POST /elements/add/` EXISTS
 * ---------------------------------------------------------------------------
 * The server's BLANK_ELEMENTS knows one recipe per element *type*, and this
 * panel offers dozens of shapes that are all `type: "shape" | "line" |
 * "image"` — a star and a rectangle differ only in style, which the add
 * endpoint cannot carry. More importantly, a drag-and-drop needs the element
 * to exist at the drop position immediately; templates.ts says it outright:
 * "the canvas normally creates elements locally and saves them with the rest
 * of the document". So each primitive carries the exact `style` keys
 * document.py validates and ElementLayer/_element_html render, and the
 * ordinary autosave persists it — no second save path, no second element
 * shape.
 *
 * EVERY NON-RECTANGULAR SHAPE IS A `clip_polygon` OF PLAIN NUMBERS
 * ---------------------------------------------------------------------------
 * Never an SVG path string: `clip-path` accepts `url(...)`, and the whole
 * codebase closes that hole by refusing to interpolate anything but numbers
 * (see document._validate_clip_polygon). The cost is that curves become
 * many-sided polygons — capped at the validator's 64 points — which at
 * render size is a difference nobody can see; the identical trade the PDF
 * extractor makes for imported blobs.
 *
 * SIZES ARE FRACTIONS OF THE SHORTER CANVAS SIDE, NOT OF EACH AXIS
 * ---------------------------------------------------------------------------
 * Stored geometry is per-axis fractions, so "0.3 wide × 0.3 tall" would be a
 * rectangle on a 1080×1920 Story. A circle has to be authored in pixels at
 * placement time — both sides as the same fraction of min(width, height),
 * then converted through `pixelBoxToGeometry` like every other pixel box.
 */

import type { ElementType } from '../../api/templates.ts'

export type ShapePrimitiveKey = string

export type ShapeCategory = 'shapes' | 'lines' | 'frames'

export type ShapePrimitive = {
  key: ShapePrimitiveKey
  /** The layers-panel name the new element starts with. */
  label: string
  /** Search terms for the panel's filter box. */
  keywords: string
  category: ShapeCategory
  /** The document element type this becomes. */
  type: ElementType
  /** Default size, as fractions of the canvas's SHORTER side (see above). */
  width: number
  height: number
  /** Default document style — exactly the keys document.py accepts. */
  style: Record<string, unknown>
}

/** The default fill, matching the server's own shape recipe and the editor's
 *  brand accent, so a fresh shape looks at home before it is restyled. */
const SHAPE_FILL = '#8B4F24'

// -- polygon generators ------------------------------------------------------
// All emit flat [x1, y1, x2, y2, ...] percentage lists, 2dp, ≤64 points.

const round2 = (value: number) => Math.round(value * 100) / 100

/** N points evenly around a circle of radius 50 centred at (50, 50). */
function regularPolygon(sides: number, startDeg = -90): number[] {
  const points: number[] = []
  for (let index = 0; index < sides; index += 1) {
    const angle = ((startDeg + (360 / sides) * index) * Math.PI) / 180
    points.push(round2(50 + 50 * Math.cos(angle)), round2(50 + 50 * Math.sin(angle)))
  }
  return points
}

/** A star: alternating outer (50) and inner (50·ratio) radii. */
function star(spikes: number, innerRatio: number): number[] {
  const points: number[] = []
  for (let index = 0; index < spikes * 2; index += 1) {
    const radius = index % 2 === 0 ? 50 : 50 * innerRatio
    const angle = ((-90 + (180 / spikes) * index) * Math.PI) / 180
    points.push(round2(50 + radius * Math.cos(angle)), round2(50 + radius * Math.sin(angle)))
  }
  return points
}

/** The classic parametric heart, scaled into the 0–100 box. */
function heart(samples = 28): number[] {
  const raw: [number, number][] = []
  for (let index = 0; index < samples; index += 1) {
    const t = (index / samples) * 2 * Math.PI
    raw.push([
      16 * Math.sin(t) ** 3,
      13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t),
    ])
  }
  const xs = raw.map(([x]) => x)
  const ys = raw.map(([, y]) => y)
  const [minX, maxX] = [Math.min(...xs), Math.max(...xs)]
  const [minY, maxY] = [Math.min(...ys), Math.max(...ys)]
  return raw.flatMap(([x, y]) => [
    round2(((x - minX) / (maxX - minX)) * 100),
    // The parametric heart is y-up; the canvas is y-down.
    round2((1 - (y - minY) / (maxY - minY)) * 100),
  ])
}

/** A soft organic blob: a circle with two slow radial wobbles. */
function blob(samples = 24): number[] {
  const points: number[] = []
  for (let index = 0; index < samples; index += 1) {
    const t = (index / samples) * 2 * Math.PI
    const radius = 38 + 7 * Math.sin(2 * t + 0.8) + 5 * Math.sin(3 * t + 2.1)
    points.push(round2(50 + radius * Math.cos(t)), round2(50 + radius * Math.sin(t)))
  }
  return points
}

/** A dome from (0, base) over (50, 0) to (100, base); the caller closes it. */
function arc(base: number, samples: number): number[] {
  const points: number[] = []
  for (let index = 0; index <= samples; index += 1) {
    const angle = Math.PI - (index / samples) * Math.PI
    points.push(round2(50 + 50 * Math.cos(angle)), round2(base - base * Math.sin(angle)))
  }
  return points
}

// -- the library -------------------------------------------------------------

function shape(
  key: string,
  label: string,
  keywords: string,
  width: number,
  height: number,
  style: Record<string, unknown>,
  category: ShapeCategory = 'shapes',
  type: ElementType = 'shape',
): ShapePrimitive {
  return { key, label, keywords, category, type, width, height, style }
}

const fill = (extra: Record<string, unknown> = {}): Record<string, unknown> => ({
  background_color: SHAPE_FILL,
  opacity: 1,
  ...extra,
})

export const SHAPE_PRIMITIVES: ShapePrimitive[] = [
  // -- basic ------------------------------------------------------------
  shape('rectangle', 'Rectangle', 'rectangle square block box', 0.42, 0.28, fill()),
  shape('rounded_rect', 'Rounded rectangle', 'rounded corner soft card', 0.42, 0.28,
    // border_radius_ratio is a fraction of the canvas's shorter side — the
    // same formula ElementLayer and _element_html both apply.
    fill({ border_radius_ratio: 0.035 })),
  shape('circle', 'Circle', 'circle round ellipse dot', 0.3, 0.3,
    // Half the shorter side always exceeds half the box, and CSS clamps
    // border-radius at 50% of the box — a true circle, in the editor and in
    // Chromium's export alike.
    fill({ border_radius_ratio: 0.5 })),
  shape('pill', 'Pill', 'pill capsule lozenge button tag', 0.4, 0.12, fill({ border_radius_ratio: 0.5 })),
  shape('semicircle', 'Semicircle', 'semicircle half dome', 0.36, 0.18,
    fill({ clip_polygon: [...arc(100, 16), 0, 100] })),
  // -- angular ----------------------------------------------------------
  shape('triangle', 'Triangle', 'triangle pyramid delta', 0.32, 0.28,
    fill({ clip_polygon: [50, 0, 100, 100, 0, 100] })),
  shape('right_triangle', 'Right triangle', 'right triangle corner wedge', 0.32, 0.28,
    fill({ clip_polygon: [0, 0, 100, 100, 0, 100] })),
  shape('diamond', 'Diamond', 'diamond rhombus gem', 0.3, 0.3,
    fill({ clip_polygon: [50, 0, 100, 50, 50, 100, 0, 50] })),
  shape('parallelogram', 'Parallelogram', 'parallelogram slant skew', 0.42, 0.24,
    fill({ clip_polygon: [25, 0, 100, 0, 75, 100, 0, 100] })),
  shape('trapezoid', 'Trapezoid', 'trapezoid trapezium', 0.42, 0.24,
    fill({ clip_polygon: [20, 0, 80, 0, 100, 100, 0, 100] })),
  // -- polygons ---------------------------------------------------------
  shape('pentagon', 'Pentagon', 'pentagon five sides', 0.3, 0.3, fill({ clip_polygon: regularPolygon(5) })),
  shape('hexagon', 'Hexagon', 'hexagon six sides honeycomb', 0.3, 0.3, fill({ clip_polygon: regularPolygon(6) })),
  shape('octagon', 'Octagon', 'octagon eight sides stop', 0.3, 0.3, fill({ clip_polygon: regularPolygon(8, -67.5) })),
  // -- stars ------------------------------------------------------------
  shape('star_4', 'Sparkle', 'star four point sparkle twinkle', 0.3, 0.3, fill({ clip_polygon: star(4, 0.4) })),
  shape('star_5', 'Star', 'star five point rating favourite', 0.3, 0.3, fill({ clip_polygon: star(5, 0.38) })),
  shape('star_6', 'Star of six', 'star six point', 0.3, 0.3, fill({ clip_polygon: star(6, 0.52) })),
  shape('burst', 'Burst', 'burst badge seal sticker sale', 0.3, 0.3, fill({ clip_polygon: star(12, 0.78) })),
  // -- arrows & callouts ------------------------------------------------
  shape('arrow_right', 'Arrow right', 'arrow right next point', 0.4, 0.2,
    fill({ clip_polygon: [0, 30, 60, 30, 60, 0, 100, 50, 60, 100, 60, 70, 0, 70] })),
  shape('arrow_left', 'Arrow left', 'arrow left back point', 0.4, 0.2,
    fill({ clip_polygon: [100, 30, 40, 30, 40, 0, 0, 50, 40, 100, 40, 70, 100, 70] })),
  shape('chevron', 'Chevron', 'chevron arrow direction breadcrumb', 0.34, 0.22,
    fill({ clip_polygon: [0, 0, 70, 0, 100, 50, 70, 100, 0, 100, 30, 50] })),
  shape('speech_bubble', 'Speech bubble', 'speech bubble quote callout talk', 0.38, 0.3,
    fill({ clip_polygon: [0, 0, 100, 0, 100, 72, 38, 72, 20, 100, 26, 72, 0, 72] })),
  shape('ribbon', 'Ribbon', 'ribbon banner label sash', 0.5, 0.16,
    fill({ clip_polygon: [0, 0, 100, 0, 92, 50, 100, 100, 0, 100, 8, 50] })),
  shape('cross', 'Cross', 'cross plus add health', 0.3, 0.3,
    fill({ clip_polygon: [35, 0, 65, 0, 65, 35, 100, 35, 100, 65, 65, 65, 65, 100, 35, 100, 35, 65, 0, 65, 0, 35, 35, 35] })),
  // -- organic ----------------------------------------------------------
  shape('heart', 'Heart', 'heart love favourite valentine', 0.3, 0.28, fill({ clip_polygon: heart() })),
  shape('blob', 'Blob', 'blob organic amoeba fluid', 0.32, 0.32, fill({ clip_polygon: blob() })),
  // -- lines ------------------------------------------------------------
  shape('line', 'Line', 'divider line rule separator horizontal', 0.55, 0.006,
    { background_color: '#1F2937' }, 'lines', 'line'),
  shape('thick_line', 'Thick line', 'thick line bar underline accent', 0.4, 0.02,
    { background_color: SHAPE_FILL, border_radius_ratio: 0.02 }, 'lines', 'line'),
  // -- photo frames -----------------------------------------------------
  // An image slot cut to a shape — the mechanism imported flyers already use
  // for angled photo edges, offered as a primitive. The slot starts empty
  // (the canvas shows its placeholder) and fills from Images or Uploads.
  shape('frame_rect', 'Photo frame', 'image photo frame picture placeholder', 0.34, 0.42,
    frameStyle(), 'frames', 'image'),
  shape('frame_rounded', 'Rounded frame', 'image photo frame rounded card', 0.34, 0.42,
    frameStyle({ border_radius_ratio: 0.035 }), 'frames', 'image'),
  shape('frame_circle', 'Circle frame', 'image photo frame circle portrait avatar', 0.3, 0.3,
    frameStyle({ border_radius_ratio: 0.5 }), 'frames', 'image'),
  shape('frame_arch', 'Arch frame', 'image photo frame arch window door', 0.3, 0.42,
    frameStyle({ clip_polygon: [...arc(38, 14), 100, 100, 0, 100] }), 'frames', 'image'),
  shape('frame_diamond', 'Diamond frame', 'image photo frame diamond', 0.3, 0.3,
    frameStyle({ clip_polygon: [50, 0, 100, 50, 50, 100, 0, 50] }), 'frames', 'image'),
  shape('frame_hexagon', 'Hexagon frame', 'image photo frame hexagon', 0.3, 0.3,
    frameStyle({ clip_polygon: regularPolygon(6) }), 'frames', 'image'),
  shape('frame_star', 'Star frame', 'image photo frame star', 0.3, 0.3,
    frameStyle({ clip_polygon: star(5, 0.38) }), 'frames', 'image'),
  shape('frame_heart', 'Heart frame', 'image photo frame heart love', 0.3, 0.28,
    frameStyle({ clip_polygon: heart() }), 'frames', 'image'),
]

function frameStyle(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { object_fit: 'cover', object_position: 'center center', ...extra }
}

export function shapePrimitive(key: string): ShapePrimitive | null {
  return SHAPE_PRIMITIVES.find((primitive) => primitive.key === key) ?? null
}

/** The drag payload's MIME type. Custom so a drop handler can tell a shape
 *  card from a file, a text selection, or anything else the OS can drag in —
 *  those must keep their default behaviour. */
export const SHAPE_DRAG_MIME = 'application/x-listing-studio-shape'
