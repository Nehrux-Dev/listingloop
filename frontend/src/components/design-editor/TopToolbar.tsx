/**
 * The contextual toolbar, DOCKED across the top of the workspace — the way
 * Canva's is — rather than floating beside the selected element.
 *
 * WHY DOCKED RATHER THAN FLOATING
 * ---------------------------------------------------------------------------
 * The floating version sat on top of the artwork: a wide control strip
 * anchored to the selection routinely buried the element above or below the
 * one being edited, and its position jumped with every drag. A fixed strip
 * above the canvas is always in the same place, never covers the design, and
 * leaves the on-canvas chrome to a small quick-action pill (see
 * QuickActions.tsx) that is short enough not to hide anything.
 *
 * The strip is always rendered — with nothing selected it shows a hint at a
 * constant height — because appearing and disappearing would make the canvas
 * itself jump on every selection change.
 *
 * The full property inventory (position, size, rotation, every slider) lives
 * in PropertiesSidebar, which no longer opens on selection: the `Position`
 * button at the right end of this strip toggles it, mirroring Canva's
 * Position button. Mid-flow edits happen here; the panel is for deliberate
 * numeric work.
 */

import type { ListingPhoto } from '../../api/listings.ts'
import type { BrandKit } from '../../api/profiles.ts'
import type { ResolvedElement } from '../../api/templates.ts'
import {
  ColorControl,
  ImageReplaceControl,
  PositionGrid,
  SliderControl,
  ToggleButton,
  ToolbarGroup,
} from './controls.tsx'
import { IconSliders } from '../icons.tsx'
import { elementKind } from './elementKind.ts'
import { FONT_OPTIONS, FONT_STACKS } from './fonts.ts'

type Props = {
  /** Undefined when nothing is selected — the strip then shows its hint. */
  element?: ResolvedElement
  override: Record<string, unknown>
  onChange: (field: string, value: unknown) => void
  /** Ends the current run of edits so a slider drag is one undo step. */
  onCommit: () => void

  /** So `@accent_color` swatches show the real colour. */
  brandKit?: BrandKit | null

  listingPhotos: ListingPhoto[]
  onPickPhoto: (imageKey: string, previewUrl: string) => void
  onUploadFile: (file: File) => void
  uploading: boolean

  /** The `Position` toggle — opens/closes the full properties panel. */
  propertiesOpen: boolean
  onToggleProperties: () => void
}

export default function TopToolbar(props: Props) {
  const { element } = props
  const kind = element ? elementKind(element) : null
  // The one state that withholds controls, and the user set it themselves —
  // so the message says how to undo it rather than who decided.
  const isLocked = element?.locked ?? false

  return (
    <div className="flex min-h-[46px] w-full flex-wrap items-center gap-x-3 gap-y-2 rounded-panel border border-line bg-surface px-3 py-1.5 shadow-panel">
      {!element && (
        <span className="text-[11px] text-muted">
          Select an element on the canvas to edit it here.
        </span>
      )}

      {element && isLocked && (
        <div className="flex items-center gap-2">
          <span className="rounded bg-ink px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
            Locked
          </span>
          <span className="whitespace-nowrap text-[11px] text-muted">
            Unlock it from the pill on the canvas or the layers panel to edit.
          </span>
        </div>
      )}

      {element && !isLocked && (
        <>
          {kind === 'text' && (
            <TextControls
              element={element}
              override={props.override}
              onChange={props.onChange}
              onCommit={props.onCommit}
              brandKit={props.brandKit}
            />
          )}
          {kind === 'image' && (
            <ImageControls
              element={element}
              override={props.override}
              onChange={props.onChange}
              onCommit={props.onCommit}
              listingPhotos={props.listingPhotos}
              onPickPhoto={props.onPickPhoto}
              onUploadFile={props.onUploadFile}
              uploading={props.uploading}
            />
          )}
          {kind === 'shape' && (
            <ShapeControls
              element={element}
              override={props.override}
              onChange={props.onChange}
              onCommit={props.onCommit}
              brandKit={props.brandKit}
            />
          )}
        </>
      )}

      {element && (
        <div className="ml-auto flex items-center gap-1.5 pl-2">
          <span className="h-5 w-px bg-line" />
          <button
            type="button"
            onClick={props.onToggleProperties}
            aria-pressed={props.propertiesOpen}
            title="Position, size and every property of this element"
            className={`flex items-center gap-1.5 rounded-control px-2.5 py-1 text-[12px] font-medium transition ${
              props.propertiesOpen
                ? 'bg-active text-brand'
                : 'text-muted hover:bg-hover hover:text-ink'
            }`}
          >
            <IconSliders className="size-3.5" />
            Position
          </button>
        </div>
      )}
    </div>
  )
}


function TextControls({
  element,
  override,
  onChange,
  onCommit,
  brandKit,
}: {
  element: ResolvedElement
  override: Record<string, unknown>
  onChange: (field: string, value: unknown) => void
  onCommit: () => void
  brandKit?: BrandKit | null
}) {
  const style = element.style

  const value = (field: string, fallback: unknown) => override[field] ?? style[field] ?? fallback
  const weight = String(value('font_weight', '400'))
  const bold = Number(weight) >= 600
  const italic = String(value('font_style', 'normal')) === 'italic'
  const align = String(value('text_align', 'left'))

  // Every text element gets every text control. There used to be a branch
  // here for elements that granted no style fields at all — a content-only
  // element, which showed "styling is set by the template" instead of a
  // toolbar. No element is in that state any more, so the branch is gone
  // rather than left behind as unreachable code that still reads like policy.

  return (
    <>
      <ToolbarGroup label="Font">
        <select
          value={String(value('font_family', 'body'))}
          onChange={(event) => {
            onChange('font_family', event.target.value)
            onCommit()
          }}
          // Wears the selected role's own face, so the control doubles as a
          // live preview without needing per-option styling (which the native
          // select cannot do cross-browser).
          style={{ fontFamily: FONT_STACKS[String(value('font_family', 'body'))] }}
          className="max-w-[130px] rounded-md border border-line bg-surface px-1.5 py-1 text-xs outline-none focus:border-brand"
        >
          {FONT_OPTIONS.map((option) => (
            <option key={option.role} value={option.role}>
              {option.family}
            </option>
          ))}
        </select>
      </ToolbarGroup>

      {(
        <ToolbarGroup label="Size">
          <SliderControl
            min={0.01}
            max={0.25}
            step={0.002}
            value={Number(value('font_size_ratio', 0.04))}
            onChange={(next) => onChange('font_size_ratio', next)}
            onCommit={onCommit}
            format={(v) => `${(v * 100).toFixed(1)}%`}
          />
        </ToolbarGroup>
      )}

      {(
        <ToolbarGroup label="Weight">
          {(
            <ToggleButton
              active={bold}
              onClick={() => onChange('font_weight', bold ? '400' : '700')}
              label="Bold"
            >
              <strong>B</strong>
            </ToggleButton>
          )}
          {(
            <ToggleButton
              active={italic}
              onClick={() => onChange('font_style', italic ? 'normal' : 'italic')}
              label="Italic"
            >
              <em>I</em>
            </ToggleButton>
          )}
        </ToolbarGroup>
      )}

      {(
        <ToolbarGroup label="Align">
          {(['left', 'center', 'right'] as const).map((option) => (
            <ToggleButton
              key={option}
              active={align === option}
              onClick={() => onChange('text_align', option)}
              label={`Align ${option}`}
            >
              {option[0].toUpperCase()}
            </ToggleButton>
          ))}
        </ToolbarGroup>
      )}

      {(
        <ToolbarGroup label="Colour">
          <ColorControl
            brandKit={brandKit}
            value={String(value('color', '#000000'))}
            onChange={(next) => onChange('color', next)}
          />
        </ToolbarGroup>
      )}

      {(
        <ToolbarGroup label="Line height">
          <SliderControl
            min={0.8}
            max={3}
            step={0.05}
            value={Number(value('line_height', 1.2))}
            onChange={(next) => onChange('line_height', next)}
            onCommit={onCommit}
            className="w-20"
            format={(v) => v.toFixed(2)}
          />
        </ToolbarGroup>
      )}

      {(
        <ToolbarGroup label="Letter spacing">
          <SliderControl
            min={-0.1}
            max={1}
            step={0.01}
            value={Number(value('letter_spacing_em', 0))}
            onChange={(next) => onChange('letter_spacing_em', next)}
            onCommit={onCommit}
            className="w-20"
            format={(v) => `${v.toFixed(2)}em`}
          />
        </ToolbarGroup>
      )}
    </>
  )
}

function ImageControls({
  element,
  override,
  onChange,
  onCommit,
  listingPhotos,
  onPickPhoto,
  onUploadFile,
  uploading,
}: {
  element: ResolvedElement
  override: Record<string, unknown>
  onChange: (field: string, value: unknown) => void
  onCommit: () => void
  listingPhotos: ListingPhoto[]
  onPickPhoto: (imageKey: string, previewUrl: string) => void
  onUploadFile: (file: File) => void
  uploading: boolean
}) {
  const style = element.style
  const value = (field: string, fallback: unknown) => override[field] ?? style[field] ?? fallback
  const fit = String(value('object_fit', 'cover'))

  return (
    <>
      {(
        <ToolbarGroup label="Replace">
          <ImageReplaceControl
            listingPhotos={listingPhotos}
            onPickPhoto={onPickPhoto}
            onUploadFile={onUploadFile}
            uploading={uploading}
          />
        </ToolbarGroup>
      )}

      {/* "Crop" is this pair — which part of the photo survives the frame
          (position) and how it fills it (fit). A true drag-to-crop tool would
          need free dragging inside the frame, which is a different gesture
          from the element dragging Phase 3 introduced. */}
      {(
        <ToolbarGroup label="Crop">
          <PositionGrid
            value={String(value('object_position', 'center center'))}
            onChange={(next) => onChange('object_position', next)}
          />
        </ToolbarGroup>
      )}

      {(
        <ToolbarGroup label="Object fit">
          {(['cover', 'contain', 'fill'] as const).map((option) => (
            <ToggleButton
              key={option}
              active={fit === option}
              onClick={() => onChange('object_fit', option)}
              label={option}
            >
              {option[0].toUpperCase()}
            </ToggleButton>
          ))}
        </ToolbarGroup>
      )}

      {(
        <ToolbarGroup label="Opacity">
          <SliderControl
            min={0}
            max={1}
            step={0.05}
            value={Number(value('opacity', 1))}
            onChange={(next) => onChange('opacity', next)}
            onCommit={onCommit}
            className="w-20"
            format={(v) => `${Math.round(v * 100)}%`}
          />
        </ToolbarGroup>
      )}
    </>
  )
}

function ShapeControls({
  element,
  override,
  onChange,
  onCommit,
  brandKit,
}: {
  element: ResolvedElement
  override: Record<string, unknown>
  onChange: (field: string, value: unknown) => void
  onCommit: () => void
  brandKit?: BrandKit | null
}) {
  const style = element.style
  const value = (field: string, fallback: unknown) => override[field] ?? style[field] ?? fallback

  return (
    <>
      {(
        <ToolbarGroup label="Fill">
          <ColorControl
            brandKit={brandKit}
            value={String(value('background_color', '#000000'))}
            onChange={(next) => onChange('background_color', next)}
          />
        </ToolbarGroup>
      )}

      {(
        <ToolbarGroup label="Border">
          <SliderControl
            min={0}
            max={0.05}
            step={0.001}
            value={Number(value('border_width_ratio', 0))}
            onChange={(next) => onChange('border_width_ratio', next)}
            onCommit={onCommit}
            className="w-20"
            format={(v) => `${(v * 100).toFixed(1)}%`}
          />
          {(
            <ColorControl
              brandKit={brandKit}
              value={String(value('border_color', '#000000'))}
                onChange={(next) => onChange('border_color', next)}
            />
          )}
        </ToolbarGroup>
      )}

      {(
        <ToolbarGroup label="Opacity">
          <SliderControl
            min={0}
            max={1}
            step={0.05}
            value={Number(value('opacity', 1))}
            onChange={(next) => onChange('opacity', next)}
            onCommit={onCommit}
            className="w-20"
            format={(v) => `${Math.round(v * 100)}%`}
          />
        </ToolbarGroup>
      )}

      {(
        <ToolbarGroup label="Radius">
          <SliderControl
            min={0}
            max={0.5}
            step={0.005}
            value={Number(value('border_radius_ratio', 0))}
            onChange={(next) => onChange('border_radius_ratio', next)}
            onCommit={onCommit}
            className="w-20"
            format={(v) => `${(v * 100).toFixed(1)}%`}
          />
        </ToolbarGroup>
      )}
    </>
  )
}



