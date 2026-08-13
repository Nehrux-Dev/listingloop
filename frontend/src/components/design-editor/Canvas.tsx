/**
 * The interactive design surface: every TemplateElement rendered as its own
 * positioned DOM node at the template's true pixel size, then the whole
 * stage scaled uniformly to fit the available space.
 *
 * WHY A TRUE-SIZE STAGE SCALED BY CSS TRANSFORM, RATHER THAN COMPUTING EVERY
 * STYLE AT DISPLAY SIZE
 * ---------------------------------------------------------------------------
 * Every element's CSS (position, font-size, border-radius, ...) is computed
 * once, at the dimension's real pixel size (1080x1920, 1200x630, ...) —
 * exactly the numbers `_element_html` on the backend would compute. Zoom is
 * then a single `transform: scale()` on the outer stage. This is what
 * guarantees the canvas cannot drift from the actual renderer: there is only
 * one set of position/size formulas, not one for "real" and a second,
 * separately-scaled one for "on screen".
 *
 * Normalized 0–1 geometry is the source of truth throughout — this component
 * converts it to true pixels for layout and never writes anything back.
 */

import { useEffect, useRef, useState } from 'react'

import type { BrandKit } from '../../api/profiles.ts'
import type { ResolvedDesign } from '../../api/templates.ts'
import { IconComment, IconCursor, IconGrid, IconHand } from '../icons.tsx'
import ElementLayer, { resolveColor } from './ElementLayer.tsx'
import SelectionOverlay from './SelectionOverlay.tsx'
import {
  clampToCanvasLimits,
  geometryToPixelBox,
  normalizeRotation,
  pixelBoxToGeometry,
  resizeBox,
  snapMovingBox,
  snapRotation,
  type Box,
  type PixelBox,
  type ResizeHandle,
} from './geometry.ts'

const ZOOM_STEPS = [25, 50, 75, 100, 125, 150, 200]
const MIN_ZOOM = ZOOM_STEPS[0]
const MAX_ZOOM = ZOOM_STEPS[ZOOM_STEPS.length - 1]

/** On-screen pixels, converted to canvas-frame by dividing by the current
 *  zoom scale — keeps the "feel" of snapping constant across zoom levels
 *  rather than snapping too eagerly zoomed-out or barely at all zoomed-in. */
const SNAP_THRESHOLD_SCREEN_PX = 6

/** Alignment guides, in the theme's accent. An inline style rather than a
 *  utility because it is drawn in canvas-frame pixels. */
const SNAP_GUIDE = '#8B4F24'

/** Vertical room (screen px) the floating toolbar needs above an element
 *  before it flips to sitting below it instead. */
const TOOLBAR_CLEARANCE = 90

/** Which pointer gesture the mat is in. Select is the editor's normal
 *  mode; hand drags the workspace instead of the artwork. */
export type CanvasTool = 'select' | 'hand'

type Interaction =
  | {
      type: 'move'
      key: string
      startBox: PixelBox
      startClient: { x: number; y: number }
      rotation: number
    }
  | {
      type: 'resize'
      key: string
      handle: ResizeHandle
      startBox: PixelBox
      startClient: { x: number; y: number }
      rotation: number
    }
  | {
      type: 'rotate'
      key: string
      center: { x: number; y: number }
      startAngleDeg: number
      startRotation: number
    }

type Props = {
  design: ResolvedDesign
  backgroundColor?: string
  brandKit: BrandKit | null
  /** The id of the selected element. One value, read and written by the
   *  canvas AND the layers panel — selection has a single source of truth so
   *  the two surfaces cannot disagree about what is selected. */
  selectedKey: string | null
  onSelect: (id: string | null) => void
  editingKey: string | null
  onStartEdit: (key: string) => void
  onCommitEdit: (key: string, text: string) => void
  onCancelEdit: () => void
  /** Move/resize/rotate all funnel through this — it's just `changeField`
   *  with the 'geometry' field baked in, one level up. */
  onGeometryChange: (id: string, geometry: Box) => void
  /** Fired once when a drag gesture finishes, so the page can close off one
   *  undo entry per gesture instead of one per pointermove. */
  onGeometryCommit: () => void
  /** Zoom lives on the page because the top toolbar owns the controls; the
   *  canvas still computes the "fit" value, since only it can measure the
   *  space available. */
  zoom: number
  onZoomChange: (zoom: number) => void
  /** Incremented by the page's "Fit" button — Canvas re-measures whenever
   *  this changes. A counter rather than a boolean so repeated presses each
   *  re-fit, which matters after the panel is resized. */
  fitNonce: number
  /** The contextual controls for whatever is selected. Passed in rather
   *  than built here so the canvas stays agnostic about what an element
   *  can do; the canvas only decides where the toolbar sits. */
  selectionToolbar?: React.ReactNode
}

export default function Canvas({
  design,
  backgroundColor,
  brandKit,
  selectedKey,
  onSelect,
  editingKey,
  onStartEdit,
  onCommitEdit,
  onCancelEdit,
  onGeometryChange,
  onGeometryCommit,
  zoom,
  onZoomChange,
  fitNonce,
  selectionToolbar,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const [autoFitted, setAutoFitted] = useState(false)
  const [guides, setGuides] = useState<{ vertical: number[]; horizontal: number[] }>({
    vertical: [],
    horizontal: [],
  })
  const [tool, setTool] = useState<CanvasTool>('select')
  /**
   * Widths needed to keep the floating toolbar fully visible.
   *
   * The mat clips its overflow, so a toolbar wider than the space to the
   * right of an element gets its far end cut off — which is how the line
   * height and letter spacing controls disappeared. Measuring both lets the
   * toolbar cap its width to the workspace and slide left rather than run
   * off the edge.
   */
  const [matWidth, setMatWidth] = useState(0)
  const [toolbarWidth, setToolbarWidth] = useState(0)

  useEffect(() => {
    const element = containerRef.current
    if (!element) return
    const measure = () => setMatWidth(element.clientWidth)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // Read inside the window pointermove/pointerup listeners (subscribed once,
  // see below) without making that subscription churn on every render —
  // `design` in particular changes on every drag step, since each step
  // round-trips through the parent's state.
  const interactionRef = useRef<Interaction | null>(null)
  const suppressNextClickRef = useRef(false)
  const designRef = useRef(design)
  useEffect(() => {
    designRef.current = design
  }, [design])
  const scaleValueRef = useRef(1)
  const onGeometryChangeRef = useRef(onGeometryChange)
  useEffect(() => {
    onGeometryChangeRef.current = onGeometryChange
  }, [onGeometryChange])
  const onGeometryCommitRef = useRef(onGeometryCommit)
  useEffect(() => {
    onGeometryCommitRef.current = onGeometryCommit
  }, [onGeometryCommit])

  const onZoomChangeRef = useRef(onZoomChange)
  useEffect(() => {
    onZoomChangeRef.current = onZoomChange
  }, [onZoomChange])

  // Fit when a design first loads, when its dimension changes (which changes
  // design.width), and whenever the toolbar's Fit button bumps fitNonce.
  useEffect(() => {
    setAutoFitted(false)
    // Deferred a tick so the container has its final layout size.
    const id = window.requestAnimationFrame(() => {
      const container = containerRef.current
      if (container) {
        // Leave a little breathing room rather than butting the design
        // against the panel edge.
        const available = container.clientWidth - 32
        const pct = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, (available / design.width) * 100))
        onZoomChangeRef.current(Math.round(pct))
      }
      setAutoFitted(true)
    })
    return () => window.cancelAnimationFrame(id)
  }, [design.width, design.height, fitNonce])

  const scale = zoom / 100
  const stageWidth = design.width * scale
  const stageHeight = design.height * scale
  useEffect(() => {
    scaleValueRef.current = scale
  }, [scale])

  // Back to front, so the canvas paints in the order the export does.
  const sortedElements = [...design.elements].sort(
    (a, b) => a.transform.z_index - b.transform.z_index,
  )
  const selectedElement = selectedKey
    ? design.elements.find((element) => element.id === selectedKey)
    : undefined

  function clientToCanvasFrame(clientX: number, clientY: number): { x: number; y: number } {
    const rect = stageRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return { x: (clientX - rect.left) / scaleValueRef.current, y: (clientY - rect.top) / scaleValueRef.current }
  }

  function handleDragStart(key: string, event: React.PointerEvent) {
    // While panning, a press on an element pans the view rather than
    // moving the element.
    if (tool === 'hand') return
    const element = design.elements.find((item) => item.id === key)
    if (!element) return
    interactionRef.current = {
      type: 'move',
      key,
      startBox: geometryToPixelBox(element.transform, design),
      startClient: { x: event.clientX, y: event.clientY },
      rotation: element.transform.rotation,
    }
    document.body.style.cursor = 'move'
  }

  function handleResizeStart(key: string, handle: ResizeHandle, event: React.PointerEvent) {
    const element = design.elements.find((item) => item.id === key)
    if (!element) return
    interactionRef.current = {
      type: 'resize',
      key,
      handle,
      startBox: geometryToPixelBox(element.transform, design),
      startClient: { x: event.clientX, y: event.clientY },
      rotation: element.transform.rotation,
    }
    document.body.style.cursor = getComputedStyle(event.currentTarget).cursor
  }

  function handleRotateStart(key: string, event: React.PointerEvent) {
    const element = design.elements.find((item) => item.id === key)
    if (!element) return
    const box = geometryToPixelBox(element.transform, design)
    const center = { x: box.left + box.width / 2, y: box.top + box.height / 2 }
    const pointer = clientToCanvasFrame(event.clientX, event.clientY)
    const startAngleDeg = (Math.atan2(pointer.y - center.y, pointer.x - center.x) * 180) / Math.PI
    interactionRef.current = {
      type: 'rotate',
      key,
      center,
      startAngleDeg,
      startRotation: element.transform.rotation,
    }
    document.body.style.cursor = 'grabbing'
  }

  // Subscribed once — see the interactionRef/designRef/onGeometryChangeRef
  // comment above for why the listeners themselves read refs instead of
  // depending on (and re-subscribing for) every prop change mid-gesture.
  useEffect(() => {
    function handlePointerMove(event: PointerEvent) {
      const interaction = interactionRef.current
      if (!interaction) return
      event.preventDefault()
      const currentDesign = designRef.current
      const scaleValue = scaleValueRef.current

      if (interaction.type === 'move') {
        const dx = (event.clientX - interaction.startClient.x) / scaleValue
        const dy = (event.clientY - interaction.startClient.y) / scaleValue
        const movedBox: PixelBox = {
          ...interaction.startBox,
          left: interaction.startBox.left + dx,
          top: interaction.startBox.top + dy,
        }
        const others = currentDesign.elements
          .filter((element) => element.id !== interaction.key && element.visible)
          .map((element) => geometryToPixelBox(element.transform, currentDesign))
        const snapThreshold = SNAP_THRESHOLD_SCREEN_PX / scaleValue
        const { box: snappedBox, guides: nextGuides } = snapMovingBox(
          movedBox,
          currentDesign,
          others,
          snapThreshold,
        )
        setGuides(nextGuides)
        const geometry = pixelBoxToGeometry(snappedBox, interaction.rotation, currentDesign)
        onGeometryChangeRef.current(interaction.key, clampToCanvasLimits(geometry))
      } else if (interaction.type === 'resize') {
        const totalDelta = {
          x: (event.clientX - interaction.startClient.x) / scaleValue,
          y: (event.clientY - interaction.startClient.y) / scaleValue,
        }
        const resizedBox = resizeBox(interaction.handle, interaction.startBox, totalDelta, interaction.rotation)
        const geometry = pixelBoxToGeometry(resizedBox, interaction.rotation, currentDesign)
        onGeometryChangeRef.current(interaction.key, clampToCanvasLimits(geometry))
      } else if (interaction.type === 'rotate') {
        const element = currentDesign.elements.find((item) => item.id === interaction.key)
        if (!element) return
        const rect = stageRef.current?.getBoundingClientRect()
        if (!rect) return
        const pointer = {
          x: (event.clientX - rect.left) / scaleValue,
          y: (event.clientY - rect.top) / scaleValue,
        }
        const currentAngleDeg = (Math.atan2(pointer.y - interaction.center.y, pointer.x - interaction.center.x) * 180) / Math.PI
        const nextRotation = snapRotation(
          normalizeRotation(interaction.startRotation + (currentAngleDeg - interaction.startAngleDeg)),
        )
        onGeometryChangeRef.current(interaction.key, { ...element.transform, rotation: nextRotation })
      }
    }

    function handlePointerUp() {
      if (interactionRef.current) {
        interactionRef.current = null
        setGuides({ vertical: [], horizontal: [] })
        document.body.style.cursor = ''
        // A drag that started on a resize/rotate handle and ended anywhere
        // else fires a `click` on the nearest common ancestor of the two —
        // which is the mat, whose handler deselects. Without this the
        // element vanished from selection the instant a resize finished.
        suppressNextClickRef.current = true
        // One gesture, one undo entry — see DesignEditorPage's history.
        onGeometryCommitRef.current()
      }
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    window.addEventListener('pointercancel', handlePointerUp)
    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      window.removeEventListener('pointercancel', handlePointerUp)
    }
  }, [])

  /** Hand tool: drag the mat to pan instead of moving elements. */
  const panRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null)

  function beginPan(event: React.PointerEvent) {
    const container = containerRef.current
    if (!container) return
    panRef.current = {
      x: event.clientX,
      y: event.clientY,
      left: container.scrollLeft,
      top: container.scrollTop,
    }
    const move = (moveEvent: PointerEvent) => {
      const origin = panRef.current
      if (!origin || !containerRef.current) return
      containerRef.current.scrollLeft = origin.left - (moveEvent.clientX - origin.x)
      containerRef.current.scrollTop = origin.top - (moveEvent.clientY - origin.y)
    }
    const up = () => {
      panRef.current = null
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const selectedBox =
    selectedElement && selectedElement.visible
      ? geometryToPixelBox(selectedElement.transform, design)
      : null

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-panel border border-line bg-workspace">
      <div className="flex items-center justify-between border-b border-line bg-surface/70 px-3 py-1.5">
        <ToolDock tool={tool} onToolChange={setTool} onReset={() => onZoomChange(100)} />
        <span className="text-[11px] tabular-nums text-muted">
          {design.width} &times; {design.height}
        </span>
      </div>

      <div
        ref={containerRef}
        className={`min-h-0 flex-1 overflow-auto p-5 ${
          tool === 'hand' ? 'cursor-grab active:cursor-grabbing' : ''
        }`}
        onPointerDown={(event) => {
          if (tool === 'hand' && event.button === 0) beginPan(event)
        }}
        // Clicking the surrounding mat deselects, the way clicking empty
        // canvas space in any design tool does — unless the click is just the
        // tail of a drag gesture (see suppressNextClickRef).
        onClick={() => {
          if (suppressNextClickRef.current) {
            suppressNextClickRef.current = false
            return
          }
          onSelect(null)
        }}
      >
        {!autoFitted ? (
          <p className="text-[11px] text-muted">Loading canvas…</p>
        ) : (
          <div className="mx-auto w-fit">
            <div className="flex">
              <div className="size-[22px] shrink-0 border-b border-r border-line bg-surface/60" />
              <Ruler axis="x" length={design.width} scale={scale} />
            </div>
            <div className="flex">
              <Ruler axis="y" length={design.height} scale={scale} />
              <div
                // A fixed-size box holding the scaled stage keeps the
                // scrollable area's layout stable — the inner stage transform
                // does not affect document flow, so without this the mat would
                // not know how big the (visually shrunk) canvas actually is.
                //
                // `position: relative` is load-bearing: the selection overlay
                // is absolutely positioned, and without a positioned ancestor
                // here it resolved against the page instead, drawing the
                // handles in the top-left page margin.
                style={{ width: stageWidth, height: stageHeight, position: 'relative' }}
              >
                <div
                  ref={stageRef}
                  style={{
                    width: design.width,
                    height: design.height,
                    transform: `scale(${scale})`,
                    transformOrigin: 'top left',
                    position: 'relative',
                    overflow: 'hidden',
                    background: backgroundColor
                      ? resolveColor(backgroundColor, brandKit)
                      : '#FFFFFF',
                    boxShadow: '0 1px 3px rgba(42,26,16,0.10), 0 0 0 1px rgba(42,26,16,0.05)',
                  }}
                  onClick={(event) => event.stopPropagation()}
                >
                  {sortedElements.map((element) => (
                    <ElementLayer
                      key={element.id}
                      element={element}
                      canvas={design}
                      brandKit={brandKit}
                      onSelect={(id) => onSelect(id)}
                      editing={editingKey === element.id}
                      onStartEdit={onStartEdit}
                      onCommitEdit={onCommitEdit}
                      onCancelEdit={onCancelEdit}
                      onDragStart={handleDragStart}
                    />
                  ))}
                </div>

                {/* A second, unclipped layer at the same position and scale,
                    purely for chrome that was never part of the rendered
                    design — selection border, handles, snap guides — so none
                    of it can be cut off by the stage's overflow:hidden. */}
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    width: design.width,
                    height: design.height,
                    transform: `scale(${scale})`,
                    transformOrigin: 'top left',
                    pointerEvents: 'none',
                  }}
                >
                  {selectedElement && selectedElement.visible && (
                    <SelectionOverlay
                      element={selectedElement}
                      canvas={design}
                      editing={editingKey === selectedElement.id}
                      scale={scale}
                      onResizeStart={handleResizeStart}
                      onRotateStart={handleRotateStart}
                    />
                  )}
                  {guides.vertical.map((x) => (
                    <div
                      key={`v-${x}`}
                      style={{
                        position: 'absolute',
                        left: x,
                        top: 0,
                        width: 1 / scale,
                        height: design.height,
                        background: SNAP_GUIDE,
                      }}
                    />
                  ))}
                  {guides.horizontal.map((y) => (
                    <div
                      key={`h-${y}`}
                      style={{
                        position: 'absolute',
                        top: y,
                        left: 0,
                        height: 1 / scale,
                        width: design.width,
                        background: SNAP_GUIDE,
                      }}
                    />
                  ))}
                </div>

                {/* The contextual toolbar, floated beside what it acts on.
                    Deliberately a sibling of the scaled stage rather than a
                    child: at 40% zoom a scaled toolbar would be unreadable and
                    barely clickable. Its position is computed in screen
                    pixels; the controls inside are never scaled. */}
                {selectionToolbar && selectedBox && editingKey === null && (
                  <div
                    ref={(node) => {
                      // Remeasure whenever the toolbar's contents change; its
                      // width decides how far left it has to slide.
                      const width = node?.offsetWidth ?? 0
                      if (width && width !== toolbarWidth) setToolbarWidth(width)
                    }}
                    // `w-max` matters more than it looks: without it the
                    // toolbar's width resolves against this wrapper (the
                    // stage, often only a few hundred pixels at fit zoom), so
                    // its controls wrapped into a tall block that buried the
                    // artwork it was meant to sit beside. Sizing to content
                    // keeps it one shallow strip; maxWidth then stops that
                    // strip growing wider than the workspace can show.
                    className="absolute z-20 w-max"
                    style={{
                      maxWidth: matWidth ? Math.max(260, matWidth - 48) : undefined,
                      // Anchored to the element, then slid left by however
                      // much would otherwise hang past the stage's right edge.
                      left: Math.max(
                        Math.min(0, stageWidth - toolbarWidth),
                        Math.min(selectedBox.left * scale, stageWidth - toolbarWidth),
                      ),
                      // Above the element by default; below it when the
                      // element sits near the top and there is no room, so the
                      // toolbar never rides off the top of the workspace.
                      ...(selectedBox.top * scale > TOOLBAR_CLEARANCE
                        ? { top: selectedBox.top * scale, transform: 'translateY(-100%)', paddingBottom: 30 }
                        : { top: (selectedBox.top + selectedBox.height) * scale, paddingTop: 14 }),
                    }}
                    onClick={(event) => event.stopPropagation()}
                    onPointerDown={(event) => event.stopPropagation()}
                  >
                    {selectionToolbar}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * A ruler edge.
 *
 * Ticks are spaced in canvas units and multiplied by the zoom, so the numbers
 * read as the design's own coordinates — the same ones the properties panel
 * shows for X and Y — rather than screen pixels. The label interval grows as
 * you zoom out so the strip never crowds.
 */
function Ruler({ axis, length, scale }: { axis: 'x' | 'y'; length: number; scale: number }) {
  const horizontal = axis === 'x'
  const size = length * scale
  const step = [50, 100, 200, 250, 500, 1000].find((candidate) => candidate * scale >= 55) ?? 1000

  const ticks: number[] = []
  for (let value = 0; value <= length; value += step) ticks.push(value)

  return (
    <div
      aria-hidden="true"
      className={`relative shrink-0 overflow-hidden bg-surface/60 ${
        horizontal ? 'h-[22px] border-b' : 'w-[22px] border-r'
      } border-line`}
      style={horizontal ? { width: size } : { height: size }}
    >
      {ticks.map((value) => (
        <span
          key={value}
          className="absolute text-[9px] leading-none text-muted/80"
          style={
            horizontal
              ? { left: value * scale + 3, top: 7 }
              : { top: value * scale + 3, left: 3, fontSize: 8 }
          }
        >
          {value}
        </span>
      ))}
      {ticks.map((value) => (
        <span
          key={`tick-${value}`}
          className="absolute bg-line"
          style={
            horizontal
              ? { left: value * scale, top: 0, width: 1, height: 6 }
              : { top: value * scale, left: 0, height: 1, width: 6 }
          }
        />
      ))}
    </div>
  )
}

/** Select, pan, reset zoom — and a comments slot that says what it is. */
function ToolDock({
  tool,
  onToolChange,
  onReset,
}: {
  tool: CanvasTool
  onToolChange: (tool: CanvasTool) => void
  onReset: () => void
}) {
  return (
    <div className="flex items-center gap-0.5">
      <DockButton active={tool === 'select'} onClick={() => onToolChange('select')} label="Select">
        <IconCursor className="size-4" />
      </DockButton>
      <DockButton active={tool === 'hand'} onClick={() => onToolChange('hand')} label="Pan">
        <IconHand className="size-4" />
      </DockButton>
      <span className="mx-1 h-4 w-px bg-line" />
      <DockButton active={false} onClick={onReset} label="Zoom to 100%">
        <IconGrid className="size-4" />
      </DockButton>
      <DockButton active={false} disabled label="Comments (coming soon)">
        <IconComment className="size-4" />
      </DockButton>
    </div>
  )
}

function DockButton({
  active,
  onClick,
  label,
  disabled,
  children,
}: {
  active: boolean
  onClick?: () => void
  label: string
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={`flex size-7 items-center justify-center rounded-control transition disabled:cursor-not-allowed disabled:opacity-35 ${
        active ? 'bg-active text-brand' : 'text-muted hover:bg-hover hover:text-ink'
      }`}
    >
      {children}
    </button>
  )
}

