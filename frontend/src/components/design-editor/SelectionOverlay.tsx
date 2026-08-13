/**
 * Editor-only chrome for the currently selected element: the blue selection
 * border + key label (shown for anything selected), and — only when the
 * element is not locked — resize handles, a rotation handle, and a
 * live angle readout.
 *
 * Rendered as a sibling to the (clipped) content stage, not inside
 * ElementLayer's own box, specifically so none of this can be cut off by
 * that box's `overflow: hidden`. See ElementLayer's file doc comment for
 * why that clipping has to stay.
 */

import type { ResolvedDesign, ResolvedElement } from '../../api/templates.ts'
import { geometryToPixelBox, type ResizeHandle } from './geometry.ts'
import { isAgentOwned } from './elementKind.ts'

const RESIZE_HANDLES: ResizeHandle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']

/** Position (percentage of the box's own size) and cursor per handle —
 *  centered on the corner/edge via translate(-50%,-50%) below, so no
 *  handle-size arithmetic is needed here. */
const HANDLE_LAYOUT: Record<ResizeHandle, { left: string; top: string; cursor: string }> = {
  nw: { left: '0%', top: '0%', cursor: 'nwse-resize' },
  n: { left: '50%', top: '0%', cursor: 'ns-resize' },
  ne: { left: '100%', top: '0%', cursor: 'nesw-resize' },
  e: { left: '100%', top: '50%', cursor: 'ew-resize' },
  se: { left: '100%', top: '100%', cursor: 'nwse-resize' },
  s: { left: '50%', top: '100%', cursor: 'ns-resize' },
  sw: { left: '0%', top: '100%', cursor: 'nesw-resize' },
  w: { left: '0%', top: '50%', cursor: 'ew-resize' },
}

const SAFE_FONT_STACK =
  "'DejaVu Sans', 'Liberation Sans', 'Noto Sans', 'Helvetica Neue', Arial, sans-serif"

/**
 * The selection accent, as literal values rather than theme utilities.
 *
 * Everything in this file is an inline style on an element positioned in
 * canvas-frame pixels, so it cannot use Tailwind classes — the sizes are
 * computed per zoom level. These are the `--color-brand` / `--color-ink`
 * tokens written out; if the theme's brown changes, change it here too.
 */
const ACCENT = '#8B4F24'
const ACCENT_INK = '#2A1A10'

type Props = {
  element: ResolvedElement
  canvas: Pick<ResolvedDesign, 'width' | 'height' | 'safe_inset_top' | 'safe_inset_bottom'>
  editing: boolean
  /** Current zoom level (1 = 100%) — handles are sized in screen pixels, so
   *  they need to compensate for the ancestor stage's CSS scale to stay a
   *  constant, grabbable size at any zoom instead of shrinking to nothing
   *  zoomed out or ballooning zoomed in. */
  scale: number
  onResizeStart: (key: string, handle: ResizeHandle, event: React.PointerEvent) => void
  onRotateStart: (key: string, event: React.PointerEvent) => void
}

export default function SelectionOverlay({ element, canvas, editing, scale, onResizeStart, onRotateStart }: Props) {
  const { left, top, width, height } = geometryToPixelBox(element.transform, canvas)
  const scaleRef = Math.min(canvas.width, canvas.height)
  const borderRadius =
    typeof element.style.border_radius_ratio === 'number'
      ? element.style.border_radius_ratio * scaleRef
      : 0
  const canTransform = !element.locked

  const boxStyle: React.CSSProperties = {
    position: 'absolute',
    left,
    top,
    width,
    height,
    pointerEvents: 'none',
  }
  if (element.transform.rotation) {
    boxStyle.transform = `rotate(${element.transform.rotation}deg)`
    boxStyle.transformOrigin = 'center center'
  }

  const handleSize = 10 / scale
  const rotateGap = 28 / scale

  return (
    <div style={boxStyle}>
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          inset: -2,
          border: `${1.5 / scale}px solid ${ACCENT}`,
          borderRadius,
        }}
      />
      <span
        style={{
          position: 'absolute',
          top: -24 / scale,
          left: -1,
          background: ACCENT,
          color: '#FFFFFF',
          fontSize: 11 / scale,
          fontFamily: SAFE_FONT_STACK,
          fontWeight: 600,
          padding: `${2 / scale}px ${6 / scale}px`,
          borderRadius: 4 / scale,
          whiteSpace: 'nowrap',
        }}
      >
        {element.name}
        {isAgentOwned(element) && ' · added'}
      </span>

      {canTransform && !editing && (
        <>
          {RESIZE_HANDLES.map((handle) => (
            <div
              key={handle}
              onPointerDown={(event) => {
                event.stopPropagation()
                event.preventDefault()
                onResizeStart(element.id, handle, event)
              }}
              style={{
                position: 'absolute',
                left: HANDLE_LAYOUT[handle].left,
                top: HANDLE_LAYOUT[handle].top,
                transform: 'translate(-50%, -50%)',
                width: handleSize,
                height: handleSize,
                borderRadius: 2,
                background: '#FFFFFF',
                border: `${1.5 / scale}px solid ${ACCENT}`,
                boxSizing: 'border-box',
                cursor: HANDLE_LAYOUT[handle].cursor,
                pointerEvents: 'auto',
              }}
            />
          ))}

          {/* Rotation indicator: the connecting line + grab handle, plus a
              live angle readout so the current tilt is always legible, not
              just guessable from the tilt itself. */}
          <div
            aria-hidden="true"
            style={{
              position: 'absolute',
              left: '50%',
              top: -rotateGap,
              width: 1 / scale,
              height: rotateGap - handleSize / 2,
              background: ACCENT,
              transform: 'translateX(-50%)',
            }}
          />
          <div
            onPointerDown={(event) => {
              event.stopPropagation()
              event.preventDefault()
              onRotateStart(element.id, event)
            }}
            title="Drag to rotate"
            style={{
              position: 'absolute',
              left: '50%',
              top: -rotateGap,
              transform: 'translate(-50%, -50%)',
              width: handleSize + 2 / scale,
              height: handleSize + 2 / scale,
              borderRadius: '50%',
              background: '#FFFFFF',
              border: `${1.5 / scale}px solid ${ACCENT}`,
              boxSizing: 'border-box',
              cursor: 'grab',
              pointerEvents: 'auto',
            }}
          />
          <span
            style={{
              position: 'absolute',
              left: '50%',
              top: -rotateGap - 16 / scale,
              transform: 'translate(-50%, -100%)',
              background: ACCENT_INK,
              color: '#FFFFFF',
              fontSize: 10 / scale,
              fontFamily: SAFE_FONT_STACK,
              fontWeight: 600,
              padding: `${2 / scale}px ${5 / scale}px`,
              borderRadius: 3 / scale,
              whiteSpace: 'nowrap',
            }}
          >
            {Math.round(element.transform.rotation)}°
          </span>
        </>
      )}
    </div>
  )
}
