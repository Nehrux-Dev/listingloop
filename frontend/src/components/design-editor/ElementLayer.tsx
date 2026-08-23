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

import { useEffect, useLayoutEffect, useRef } from 'react'

import type { BrandKit } from '../../api/profiles.ts'
import { carriesImage, carriesText } from '../../api/templates.ts'
import type { ResolvedDesign, ResolvedElement } from '../../api/templates.ts'
import { geometryToPixelBox } from './geometry.ts'

// The role -> family stacks moved to fonts.ts so the canvas and the font
// picker read one list; the parity contract with html_builder is documented
// there.
import { FONT_STACKS, SAFE_FONT_STACK } from './fonts.ts'

const JUSTIFY_BY_ALIGN: Record<string, string> = {
  left: 'flex-start',
  center: 'center',
  right: 'flex-end',
}

/**
 * `clip-path` for an element whose visible edge is not its own box — the
 * angled and chevron photo cuts an imported flyer is full of.
 *
 * Takes the flat `[x1, y1, x2, y2, ...]` percentage list the server validated
 * and builds the CSS from numbers. Deliberately not "whatever string the
 * element carried": `clip-path` takes a function, and the canvas should be no
 * more willing to interpolate one than the renderer is. See
 * `html_builder._clip_path`, which this mirrors exactly.
 */
/**
 * A dotted ground as CSS. Mirrors `html_builder._dot_pattern`.
 *
 * A repeating grid of dots is a pattern, and flattening it to one hex — the
 * dot's colour, or the average of the area — produces something that looks
 * nothing like the artwork. The extractor records the dot and the grid; this
 * rebuilds one tile holding one dot and repeats it.
 */
function dotPattern(
  style: Record<string, unknown>,
  scaleRef: number,
  brandKit: BrandKit | null,
): React.CSSProperties | undefined {
  if (style.fill_type !== 'dot_pattern') return undefined
  const radius = num(style.dot_radius_ratio) * scaleRef
  const spacingX = num(style.dot_spacing_x_ratio) * scaleRef
  const spacingY = num(style.dot_spacing_y_ratio) * scaleRef
  if (radius <= 0 || spacingX <= 0 || spacingY <= 0) return undefined
  const colour = resolveColor(style.dot_color ?? '#000000', brandKit)
  return {
    // `radius` twice so the stop lands exactly on the dot's edge and the
    // gradient draws a hard circle rather than a soft blob.
    backgroundImage: `radial-gradient(circle at 50% 50%, ${colour} 0 ${radius.toFixed(2)}px, transparent ${radius.toFixed(2)}px)`,
    backgroundSize: `${spacingX.toFixed(2)}px ${spacingY.toFixed(2)}px`,
    backgroundRepeat: 'repeat',
  }
}

function clipPath(points: unknown): string | undefined {
  if (!Array.isArray(points) || points.length < 6 || points.length % 2) return undefined
  const pairs: string[] = []
  for (let index = 0; index < points.length; index += 2) {
    const x = Number(points[index])
    const y = Number(points[index + 1])
    if (!Number.isFinite(x) || !Number.isFinite(y)) return undefined
    pairs.push(`${x.toFixed(3)}% ${y.toFixed(3)}%`)
  }
  return `polygon(${pairs.join(',')})`
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

/** The shrink-to-fit constants. Mirror `html_builder.FIT_MIN_SCALE` and
 *  `FIT_STEPS`; the two implementations must produce the same pixel. */
const FIT_MIN_SCALE = 0.5
const FIT_STEPS = 8

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
  /** Right-click. Fires even on a locked element — the context menu is how a
   *  locked element gets unlocked without a trip to the layers panel. */
  onContextMenu?: (id: string, event: React.MouseEvent) => void
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
  onContextMenu,
}: Props) {
  const boxRef = useRef<HTMLDivElement>(null)

  // Shrink-to-fit. Mirrors html_builder.FIT_TEXT_JS exactly — same floor, same
  // fixed step count, same overflow test — because an agent who lays a design
  // out on a canvas that shrinks and exports through one that clips has been
  // shown a lie. If you change one, change the other.
  //
  // Declared above the `visible` early-return: hooks may not sit behind a
  // conditional. When the element is hidden there is no node and the effect
  // does nothing.
  //
  // No dependency array on purpose. React only rewrites style properties it
  // sees change, so a font size this effect lowered would survive into the
  // next render and be shrunk again from the already-shrunk value. Resetting
  // to the base size first makes the pass idempotent however often it runs.
  const fitBasePx = carriesText(element.type)
    ? num(element.style?.font_size_ratio, 0.04) * Math.min(canvas.width, canvas.height)
    : 0
  useLayoutEffect(() => {
    const node = boxRef.current
    if (!node || !(fitBasePx > 0) || editing) return
    node.style.fontSize = `${fitBasePx}px`
    const over = () =>
      node.scrollWidth > node.clientWidth + 0.5 ||
      node.scrollHeight > node.clientHeight + 0.5
    if (!over()) return
    let lo = fitBasePx * FIT_MIN_SCALE
    let hi = fitBasePx
    for (let step = 0; step < FIT_STEPS; step += 1) {
      const mid = (lo + hi) / 2
      node.style.fontSize = `${mid}px`
      if (over()) hi = mid
      else lo = mid
    }
    node.style.fontSize = `${lo}px`
  })

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
  // A dotted ground, rebuilt as a tiling pattern rather than flattened to a
  // flat fill. Mirrors html_builder._dot_pattern — same tile, same hard-edged
  // stop — and is built from numbers here for the same reason clipPath is:
  // `background-image` takes a url(), so a pass-through string would be a way
  // to make the renderer fetch something.
  const dots = dotPattern(style, scaleRef, brandKit)
  if (dots) Object.assign(box, dots)
  // Angled and chevron photo edges, the same way the export draws them. Built
  // from numbers here rather than accepting a CSS string, mirroring
  // html_builder._clip_path — the canvas and the export must agree, and they
  // agree by both refusing to interpolate anything but numbers.
  const clip = clipPath(style.clip_polygon)
  if (clip) box.clipPath = clip
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
    box.fontFamily = FONT_STACKS[String(style.font_family ?? 'body')] ?? SAFE_FONT_STACK
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
      ref={boxRef}
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
      // Unlike click, this deliberately does NOT pass through when locked:
      // the menu it opens is where Unlock lives.
      onContextMenu={(event) => {
        if (!onContextMenu || editing) return
        event.preventDefault()
        event.stopPropagation()
        onContextMenu(element.id, event)
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
