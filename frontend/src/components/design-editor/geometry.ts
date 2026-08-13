/**
 * Pure geometry math for the canvas's drag/resize/rotate handles — no React,
 * no DOM, so the somewhat fiddly trigonometry involved (rotation-aware
 * resize, angle snapping) can be reasoned about and adjusted in one place
 * rather than buried inside pointer-event handlers.
 *
 * Two coordinate spaces matter throughout this file:
 *  - "fraction" space: normalized geometry, the actual source of truth that
 *    gets saved on the element's `transform`. Never store anything else.
 *  - "canvas-frame" space: true pixels at the current dimension's real size
 *    (1080x1080, 1080x1920, ...), BEFORE the zoom-level CSS scale is
 *    applied. Every element is laid out in this space — it's what
 *    `_element_html` on the backend computes too. Screen/pointer pixels are
 *    a third space (post-zoom); converting between screen and canvas-frame
 *    is the caller's job (divide/multiply by the current zoom scale), not
 *    this module's — it has no notion of zoom.
 */

import type { Transform } from '../../api/templates.ts'

/** The part of a Transform this module works in. `z_index` is stacking,
 *  not geometry, and is deliberately not threaded through the math. */
export type Box = Pick<Transform, 'x' | 'y' | 'width' | 'height' | 'rotation'>

export type CanvasFrame = {
  width: number
  height: number
  safe_inset_top: number
  safe_inset_bottom: number
}

export type PixelBox = { left: number; top: number; width: number; height: number }

export type ResizeHandle = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'

/** Every element position/size is mapped into the area between the safe-area
 *  insets, not the raw canvas — mirrors ElementLayer's own conversion (and
 *  the backend's `_element_html`), duplicated nowhere else now. */
function safeHeightFraction(canvas: CanvasFrame): number {
  return 1 - canvas.safe_inset_top - canvas.safe_inset_bottom
}

export function geometryToPixelBox(geometry: Box, canvas: CanvasFrame): PixelBox {
  const safeHeight = safeHeightFraction(canvas)
  return {
    left: geometry.x * canvas.width,
    top: (canvas.safe_inset_top + geometry.y * safeHeight) * canvas.height,
    width: geometry.width * canvas.width,
    height: geometry.height * safeHeight * canvas.height,
  }
}

export function pixelBoxToGeometry(box: PixelBox, rotation: number, canvas: CanvasFrame): Box {
  const safeHeight = safeHeightFraction(canvas)
  return {
    x: box.left / canvas.width,
    y: (box.top / canvas.height - canvas.safe_inset_top) / safeHeight,
    width: box.width / canvas.width,
    height: box.height / (safeHeight * canvas.height),
    rotation,
  }
}

/** Rotates a canvas-frame vector by `degrees` (clockwise, matching CSS
 *  `transform: rotate()`) — used both to project a screen-space drag delta
 *  into an element's own (rotated) local axes for resize, and to place
 *  handles around a rotated box. */
export function rotateVector(dx: number, dy: number, degrees: number): { x: number; y: number } {
  const rad = (degrees * Math.PI) / 180
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  return { x: dx * cos - dy * sin, y: dx * sin + dy * cos }
}

/** Wraps into (-180, 180] rather than clamping — hitting the limit while
 *  dragging should keep spinning the same direction, the way a compass
 *  bearing wraps, not stick dead at 180°. Matches the backend's inclusive
 *  [-180, 180] validation range either way. */
export function normalizeRotation(degrees: number): number {
  let value = degrees % 360
  if (value <= -180) value += 360
  if (value > 180) value -= 360
  return value
}

/**
 * The outer limits of the coordinate space, mirroring document.py exactly.
 *
 * These are NOT the old per-element `bounds` constraint — that was the
 * template declaring where an element was allowed to live, and it is gone with
 * the rest of the permission model. What is left is the edge of the world:
 * elements may hang off the canvas (cropping a photo against the bleed is a
 * normal thing to do) but not end up somewhere the agent can never find them
 * again.
 *
 * Kept in step with the server so a drag can never produce a transform the
 * next save would be rejected for — a rejected autosave loses work silently.
 */
const MIN_COORD = -2
const MAX_COORD = 3
const MIN_SIZE = 0.005
const MAX_SIZE = 4

export function clampToCanvasLimits(geometry: Box): Box {
  const width = Math.min(Math.max(geometry.width, MIN_SIZE), MAX_SIZE)
  const height = Math.min(Math.max(geometry.height, MIN_SIZE), MAX_SIZE)
  return {
    x: Math.min(Math.max(geometry.x, MIN_COORD), MAX_COORD),
    y: Math.min(Math.max(geometry.y, MIN_COORD), MAX_COORD),
    width,
    height,
    rotation: geometry.rotation,
  }
}

/** Which local edges a given handle moves — (-1, 0, 1) on each axis, `-1`
 *  meaning "this handle drags the west/north edge", `1` meaning east/south,
 *  `0` meaning that axis is untouched (a pure n/s or e/w edge handle). */
const HANDLE_SIGN: Record<ResizeHandle, { sx: -1 | 0 | 1; sy: -1 | 0 | 1 }> = {
  n: { sx: 0, sy: -1 },
  s: { sx: 0, sy: 1 },
  e: { sx: 1, sy: 0 },
  w: { sx: -1, sy: 0 },
  ne: { sx: 1, sy: -1 },
  nw: { sx: -1, sy: -1 },
  se: { sx: 1, sy: 1 },
  sw: { sx: -1, sy: 1 },
}

/**
 * Resizes a box from one handle, given the total canvas-frame mouse delta
 * since the drag started. Rotation-aware: the canvas-frame delta is rotated
 * into the box's own local (unrotated) axes first, so the edge/corner
 * OPPOSITE the one being dragged stays visually anchored in the box's own
 * rotated orientation — the behavior every design tool uses, rather than
 * the box appearing to slide sideways as soon as it's tilted.
 */
export function resizeBox(
  handle: ResizeHandle,
  startBox: PixelBox,
  totalDeltaCanvas: { x: number; y: number },
  rotationDegrees: number,
): PixelBox {
  const { sx, sy } = HANDLE_SIGN[handle]
  // Undo the box's own visual rotation so the delta lines up with its local
  // (pre-rotation) left/top/width/height axes.
  const local = rotateVector(totalDeltaCanvas.x, totalDeltaCanvas.y, -rotationDegrees)

  let { left, top, width, height } = startBox
  if (sx === 1) {
    width = startBox.width + local.x
  } else if (sx === -1) {
    width = startBox.width - local.x
    left = startBox.left + local.x
  }
  if (sy === 1) {
    height = startBox.height + local.y
  } else if (sy === -1) {
    height = startBox.height - local.y
    top = startBox.top + local.y
  }
  return { left, top, width, height }
}

export type SnapResult = {
  box: PixelBox
  guides: { vertical: number[]; horizontal: number[] }
}

/**
 * Snaps a moving box's edges/center to the canvas center and to other
 * elements' edges/centers, within `thresholdPx` (already zoom-adjusted by
 * the caller — this function only sees canvas-frame pixels). Returns the
 * (possibly adjusted) box plus the guide line positions to draw, so the
 * visual feedback and the actual snap always agree.
 */
export function snapMovingBox(
  box: PixelBox,
  canvas: CanvasFrame,
  others: PixelBox[],
  thresholdPx: number,
): SnapResult {
  const targetsX = [canvas.width / 2]
  const targetsY = [canvas.height / 2]
  for (const other of others) {
    targetsX.push(other.left, other.left + other.width / 2, other.left + other.width)
    targetsY.push(other.top, other.top + other.height / 2, other.top + other.height)
  }

  const candidatesX = [
    { edge: box.left, guide: 'left' as const },
    { edge: box.left + box.width / 2, guide: 'center' as const },
    { edge: box.left + box.width, guide: 'right' as const },
  ]
  const candidatesY = [
    { edge: box.top, guide: 'top' as const },
    { edge: box.top + box.height / 2, guide: 'center' as const },
    { edge: box.top + box.height, guide: 'bottom' as const },
  ]

  let bestX: { offset: number; guide: number } | null = null
  for (const candidate of candidatesX) {
    for (const target of targetsX) {
      const offset = target - candidate.edge
      if (Math.abs(offset) <= thresholdPx && (!bestX || Math.abs(offset) < Math.abs(bestX.offset))) {
        bestX = { offset, guide: target }
      }
    }
  }

  let bestY: { offset: number; guide: number } | null = null
  for (const candidate of candidatesY) {
    for (const target of targetsY) {
      const offset = target - candidate.edge
      if (Math.abs(offset) <= thresholdPx && (!bestY || Math.abs(offset) < Math.abs(bestY.offset))) {
        bestY = { offset, guide: target }
      }
    }
  }

  return {
    box: {
      ...box,
      left: box.left + (bestX?.offset ?? 0),
      top: box.top + (bestY?.offset ?? 0),
    },
    guides: {
      vertical: bestX ? [bestX.guide] : [],
      horizontal: bestY ? [bestY.guide] : [],
    },
  }
}

/** Rotation snaps to these common angles when the drag comes within a few
 *  degrees — the small assist every design tool offers for "make it level"
 *  without demanding pixel-perfect mouse control. */
const ROTATION_SNAP_TARGETS = [-180, -135, -90, -45, 0, 45, 90, 135, 180]
const ROTATION_SNAP_THRESHOLD_DEG = 3

export function snapRotation(degrees: number): number {
  for (const target of ROTATION_SNAP_TARGETS) {
    if (Math.abs(degrees - target) <= ROTATION_SNAP_THRESHOLD_DEG) return target
  }
  return degrees
}
