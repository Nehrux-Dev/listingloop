/**
 * The toolbar above the canvas: a persistent row of document-level actions,
 * plus a contextual row that changes with what's selected.
 *
 * WHY THE GLOBAL ROW IS PERSISTENT RATHER THAN "ONLY WHEN NOTHING IS
 * SELECTED"
 * ---------------------------------------------------------------------------
 * The spec lists Undo/Redo/Zoom/Preview/Save/Export as the no-selection
 * toolbar. Taken literally that would mean Save disappears the moment you
 * click an element — you'd have to deselect to save the edit you just made.
 * So the global row stays put and the contextual row appears *in addition*
 * when something is selected. With nothing selected the toolbar shows
 * exactly the specified set, which is the behaviour the spec was describing.
 *
 * Every contextual control is gated on `editable_fields`, the list the API
 * derives from the element's permission — so a control the server would
 * reject is never rendered. That is UX, not security: `overrides.py`
 * re-validates every write regardless.
 */

import type { ListingPhoto } from '../../api/listings.ts'
import type { BrandKit } from '../../api/profiles.ts'
import type { ResolvedElement } from '../../api/templates.ts'
import {
  ColorControl,
  FONT_FIXED_REASON,
  ImageReplaceControl,
  PositionGrid,
  SAFE_FONT_LABEL,
  SliderControl,
  ToggleButton,
  ToolbarGroup,
} from './controls.tsx'
import { IconTrash } from '../icons.tsx'
import { elementKind } from './elementKind.ts'

type Props = {
  /** Undefined when nothing is selected — the toolbar then shows only its
   *  global row. */
  element?: ResolvedElement
  override: Record<string, unknown>
  onChange: (field: string, value: unknown) => void
  /** Ends the current run of edits so a slider drag is one undo step. */
  onCommit: () => void

  /** Only supplied for elements the agent owns — a template element has
   *  nothing to delete back to, so the button simply is not rendered. */
  onDelete?: () => void
  /** So `@accent_color` swatches show the real colour. */
  brandKit?: BrandKit | null

  listingPhotos: ListingPhoto[]
  onPickPhoto: (imageKey: string, previewUrl: string) => void
  onUploadFile: (file: File) => void
  uploading: boolean
}

export default function TopToolbar(props: Props) {
  const { element } = props
  const kind = element ? elementKind(element) : null
  // The one state that withholds controls, and the user set it themselves —
  // so the message says how to undo it rather than who decided.
  const isLocked = element?.locked ?? false

  return (
    <div>
      {element && isLocked && (
        <div className="flex items-center gap-2 rounded-panel border border-line bg-surface px-3 py-2 shadow-pop">
          <span className="rounded bg-ink px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
            Locked
          </span>
          <span className="whitespace-nowrap text-[11px] text-muted">
            Set by the template
          </span>
        </div>
      )}

      {element && !isLocked && (
        <div className="flex max-w-[min(760px,72vw)] flex-wrap items-center gap-x-3 gap-y-2 rounded-panel border border-line bg-surface px-2.5 py-2 shadow-pop">
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

          {props.onDelete && (
            <>
              <span className="h-5 w-px bg-line" />
              <button
                type="button"
                onClick={props.onDelete}
                title="Delete element"
                aria-label="Delete element"
                className="flex size-7 items-center justify-center rounded-control text-muted transition hover:bg-hover hover:text-danger"
              >
                <IconTrash className="size-4" />
              </button>
            </>
          )}
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
        <span className="whitespace-nowrap text-[11px] italic text-muted" title={FONT_FIXED_REASON}>
          {SAFE_FONT_LABEL} (fixed)
        </span>
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



