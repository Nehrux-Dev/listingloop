/**
 * Renders ONE resolved element as its own positioned DOM node.
 *
 * Deliberately mirrors `_element_html` in `apps/templates/html_builder.py`
 * field for field — same geometry-to-pixel mapping, same style properties,
 * same font stack — so the canvas is a faithful preview of what an export
 * would actually produce, not a second, independently-drifting layout engine.
 *
 * Double-click enters inline text editing via `contentEditable`, exiting on
 * Escape (cancel) or blur/click-outside (commit). Dragging moves the element.
 * Both are available on EVERY element — the four-tier permission that used to
 * gate them is gone. The one thing that stops either is `element.locked`,
 * which the user sets themselves and clears from the layers panel.
 *
 * Resize/rotate handles and the selection border are deliberately NOT
 * rendered here — see `SelectionOverlay.tsx`. This component's box has
 * `overflow: hidden` (it must: that's what makes an oversized image or a
 * near-edge element clip exactly the way the real export clips it), and a
 * handle sitting outside the box, or a top-anchored element's rotate handle
 * above it, would be silently clipped along with everything else. The
 * overlay is a sibling layer with the same position/scale but no clipping,
 * purely for editor chrome that was never part of the rendered design.
 */

import { useEffect, useRef } from 'react'

import type { BrandKit } from '../../api/profiles.ts'
import { carriesImage, carriesText } from '../../api/templates.ts'
import type { ResolvedDesign, ResolvedElement } from '../../api/templates.ts'
import { geometryToPixelBox } from './geometry.ts'

/** Only families known to be installed in the renderer image — matches
 *  SAFE_FONT_STACK in html_builder.py. The browser previewing this canvas may
 *  substitute a local equivalent if DejaVu isn't present locally; the actual
 *  export always goes through the renderer's own Chromium, where it is. */
const SAFE_FONT_STACK =
  "'DejaVu Sans', 'Liberation Sans', 'Noto Sans', 'Helvetica Neue', Arial, sans-serif"

const JUSTIFY_BY_ALIGN: Record<string, string> = {
  left: 'flex-start',
  center: 'center',
  right: 'flex-end',
}

/** A style value may reference the brand kit, e.g. `@accent_color` — the same
 *  convention `_resolve_color` implements server-side. Mirrored here rather
 *  than resolved by the API so the canvas needs no extra round trip per
 *  element; the brand kit is fetched once for the whole page. */
export function resolveColor(value: unknown, brandKit: BrandKit | null): string {
  if (typeof value !== 'string') return 'transparent'
  if (!value.startsWith('@')) return value
  const key = value.slice(1)
  const fromBrand = brandKit ? (brandKit as unknown as Record<string, unknown>)[key] : undefined
  return typeof fromBrand === 'string' ? fromBrand : '#000000'
}

function num(value: unknown, fallback = 0): number {
  return typeof value === 'number' ? value : fallback
}

type Props = {
  element: ResolvedElement
  /** The parts of the resolved design every element needs to position
   *  itself: true canvas size and the safe-area insets it's mapped into. */
  canvas: Pick<ResolvedDesign, 'width' | 'height' | 'safe_inset_top' | 'safe_inset_bottom'>
  brandKit: BrandKit | null
  onSelect: (id: string) => void
  /** True when THIS element is the one currently being edited inline. */
  editing: boolean
  onStartEdit: (id: string) => void
  onCommitEdit: (id: string, text: string) => void
  onCancelEdit: () => void
  onDragStart: (id: string, event: React.PointerEvent) => void
}

export default function ElementLayer({
  element,
  canvas,
  brandKit,
  onSelect,
  editing,
  onStartEdit,
  onCommitEdit,
  onCancelEdit,
  onDragStart,
}: Props) {
  if (!element.visible) return null

  const { transform, style } = element
  const scaleRef = Math.min(canvas.width, canvas.height)
  // The only gate there is. A locked element still draws — locked is not
  // hidden — it simply does not respond to the pointer.
  const canTransform = !element.locked

  const { left, top, width, height } = geometryToPixelBox(transform, canvas)

  const box: React.CSSProperties = {
    position: 'absolute',
    left,
    top,
    width,
    height,
    zIndex: transform.z_index,
    boxSizing: 'border-box',
  }
  if (transform.rotation) {
    box.transform = `rotate(${transform.rotation}deg)`
    box.transformOrigin = 'center center'
  }

  const backgroundColor = style.background_color
  if (backgroundColor) box.backgroundColor = resolveColor(backgroundColor, brandKit)
  if (style.border_radius_ratio) {
    box.borderRadius = num(style.border_radius_ratio) * scaleRef
  }
  if (style.opacity != null) box.opacity = num(style.opacity, 1)
  if (typeof style.background_gradient === 'string') {
    box.backgroundImage = style.background_gradient
  }
  // Mirrors _element_html: width alone decides whether a border is drawn, and
  // box-sizing:border-box (set above) is what keeps it from changing the
  // element's outer size — same as the export.
  if (style.border_width_ratio) {
    const borderPx = num(style.border_width_ratio) * scaleRef
    const borderStyle = typeof style.border_style === 'string' ? style.border_style : 'solid'
    box.border = `${borderPx}px ${borderStyle} ${resolveColor(style.border_color ?? '#000000', brandKit)}`
  }

  // Resolved content, not stored content: a bound element shows the live
  // price, and an image shows a data URI rather than a storage key.
  const content = element.resolved_content
  const isImage = carriesImage(element.type, element.content)
  const isText = carriesText(element.type)

  if (isText) {
    box.display = 'flex'
    box.flexDirection = 'column'
    box.justifyContent = String(style.vertical_align ?? 'flex-start')
    const align = String(style.text_align ?? 'left')
    box.alignItems = JUSTIFY_BY_ALIGN[align] ?? 'flex-start'
    box.textAlign = align as React.CSSProperties['textAlign']
    box.fontSize = num(style.font_size_ratio, 0.04) * scaleRef
    box.fontWeight = String(style.font_weight ?? '400') as React.CSSProperties['fontWeight']
    box.lineHeight = num(style.line_height, 1.2) || 1.2
    box.color = resolveColor(style.color ?? '#000000', brandKit)
    box.fontFamily = SAFE_FONT_STACK
    box.fontStyle = String(style.font_style ?? 'normal') as React.CSSProperties['fontStyle']
    if (style.letter_spacing_em) box.letterSpacing = `${num(style.letter_spacing_em)}em`
    if (typeof style.text_transform === 'string') {
      box.textTransform = style.text_transform as React.CSSProperties['textTransform']
    }
    if (typeof style.text_decoration === 'string') {
      box.textDecoration = style.text_decoration
    }
    if (style.padding_ratio) box.padding = num(style.padding_ratio) * scaleRef
    box.overflow = 'hidden'
  } else if (isImage) {
    box.overflow = 'hidden'
  }
  box.cursor = element.locked ? 'default' : editing ? 'text' : 'move'

  return (
    <div
      style={box}
      // A locked element is invisible to the pointer, so a click passes
      // through to whatever is behind it — which is the point of locking the
      // background: you can click the thing sitting on top of it.
      onClick={(event) => {
        if (element.locked) return
        event.stopPropagation()
        onSelect(element.id)
      }}
      onDoubleClick={(event) => {
        if (!isText || element.locked || editing) return
        event.stopPropagation()
        onStartEdit(element.id)
      }}
      onPointerDown={(event) => {
        if (!canTransform || editing || event.button !== 0) return
        event.stopPropagation()
        onSelect(element.id)
        onDragStart(element.id, event)
      }}
      title={element.name}
    >
      {isImage &&
        (content ? (
          <img
            src={content}
            alt=""
            draggable={false}
            style={{
              width: '100%',
              height: '100%',
              objectFit: (style.object_fit as React.CSSProperties['objectFit']) ?? 'cover',
              objectPosition: typeof style.object_position === 'string'
                ? style.object_position
                : 'center center',
              display: 'block',
              pointerEvents: 'none',
              // Zoom-and-pan inside the frame: the crop, expressed the same
              // way _image_framing does server-side so the canvas and the
              // export are laying out the same box rather than each deriving
              // its own idea of where the picture sits.
              transform:
                style.image_scale || style.image_offset_x || style.image_offset_y
                  ? `translate(${num(style.image_offset_x) * 100}%, ${
                      num(style.image_offset_y) * 100
                    }%) scale(${num(style.image_scale, 1) || 1})`
                  : undefined,
              transformOrigin: 'center center',
            }}
          />
        ) : (
          // Nothing to show yet — a faint placeholder rather than nothing at
          // all, so an empty image is still visible (and selectable) on the
          // canvas. The real export renders truly nothing here; this
          // placeholder is a canvas-only affordance, not resolved content.
          <div
            style={{
              width: '100%',
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'repeating-linear-gradient(45deg, #E2E8F0, #E2E8F0 8px, #F1F5F9 8px, #F1F5F9 16px)',
              color: '#64748B',
              fontSize: 11,
            }}
          >
            no image
          </div>
        ))}
      {isText && editing && (
        <InlineTextEditor
          initialText={typeof content === 'string' ? content : ''}
          onCommit={(text) => onCommitEdit(element.id, text)}
          onCancel={onCancelEdit}
        />
      )}
      {isText && !editing && typeof content === 'string' && content.trim() !== '' && (
        <span style={{ whiteSpace: 'pre-wrap' }}>{content}</span>
      )}
    </div>
  )
}

/**
 * A contentEditable box swapped in for the plain `<span>` while a text
 * element is being edited. Deliberately uncontrolled — React never touches
 * its DOM content while mounted, since fighting the browser's own caret
 * position on every keystroke is what makes contentEditable + React state
 * unusable. The typed text is only read out on commit.
 */
function InlineTextEditor({
  initialText,
  onCommit,
  onCancel,
}: {
  initialText: string
  onCommit: (text: string) => void
  onCancel: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const cancelledRef = useRef(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    node.textContent = initialText
    node.focus()
    // Start the caret at the end rather than the browser's default of the
    // start — matches clicking into the end of an existing line of text.
    const range = document.createRange()
    range.selectNodeContents(node)
    range.collapse(false)
    const selection = window.getSelection()
    selection?.removeAllRanges()
    selection?.addRange(range)
    // Only ever run once, on mount — see the component doc comment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div
      ref={ref}
      contentEditable
      suppressContentEditableWarning
      role="textbox"
      aria-multiline="true"
      onClick={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault()
          cancelledRef.current = true
          ref.current?.blur()
        }
      }}
      onBlur={() => {
        if (cancelledRef.current) {
          onCancel()
        } else {
          onCommit(ref.current?.textContent ?? '')
        }
      }}
      style={{
        width: '100%',
        height: '100%',
        outline: 'none',
        cursor: 'text',
        whiteSpace: 'pre-wrap',
        // A visible caret target even where the source text is empty.
        minHeight: '1em',
      }}
    />
  )
}
