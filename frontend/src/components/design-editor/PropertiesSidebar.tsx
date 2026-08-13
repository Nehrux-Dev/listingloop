/**
 * The right-hand panel: every property of the selected element, as a
 * labelled list.
 *
 * Overlaps the top toolbar on purpose. The toolbar is for the handful of
 * things you reach for mid-flow; this is the full, legible inventory of what
 * the element *is* — including the numbers (X/Y/width/height/rotation) that a
 * drag changes but never shows you.
 *
 * ONE PANEL PER TYPE, NOT ONE PANEL WITH BRANCHES
 * ---------------------------------------------------------------------------
 * `PropertiesSidebar` switches on `element.type` and renders exactly one of
 * TextProperties / ImageProperties / ShapeProperties, plus the shared
 * position block. Line reuses the shape panel minus fill; icon reuses the
 * image panel plus a tint; button is text plus the shape controls;
 * background is a full-bleed image-or-fill. None of them is special-cased
 * into "not selectable" — a background is an element like any other.
 *
 * There is no permission scaffolding left. Every control here is available on
 * every element of the right type. The one thing that withholds anything is
 * `element.locked`, which the user set and which the panel offers to unset.
 */

import type { ListingPhoto } from '../../api/listings.ts'
import type { Geometry, ResolvedElement } from '../../api/templates.ts'
import { ELEMENT_TYPE_LABELS } from '../../api/templates.ts'
import {
  ColorControl,
  FONT_FIXED_REASON,
  ImageReplaceControl,
  PercentField,
  PositionGrid,
  PropertyRow,
  SAFE_FONT_LABEL,
  SliderControl,
  ToggleButton,
} from './controls.tsx'
import { canReset, elementKind, isAgentOwned } from './elementKind.ts'

type Props = {
  element: ResolvedElement | null
  /** Set one field of the selected element. `field` is a path the page
   *  understands: a bare style key, or `content`/`name`/`locked`/`visible`,
   *  or `transform.x` and friends. */
  onChange: (field: string, value: unknown) => void
  /** Close off an undo entry — called when a gesture finishes, not on every
   *  keystroke. */
  onCommit: () => void
  /** Put this element back the way the template has it. */
  onReset?: () => void
  /** Legacy name still used by the editor page while the document refactor is
   *  being stitched through. */
  onClear?: () => void
  /** Clear `manually_overridden`, so a bound element follows its data again. */
  onSyncToData?: () => void
  listingPhotos: ListingPhoto[]
  onPickPhoto: (imageKey: string, previewUrl: string) => void
  onUploadFile: (file: File) => void
  uploading: boolean
  error?: string
}

export default function PropertiesSidebar(props: Props) {
  const { element } = props

  if (!element) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center">
        <p className="text-sm font-medium text-slate-600">Nothing selected</p>
        <p className="mt-1 text-xs text-slate-400">
          Click an element on the canvas to see and edit its properties.
        </p>
      </div>
    )
  }

  const kind = elementKind(element)

  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-ink">{element.name}</p>
          <p className="mt-0.5 text-[11px] text-muted">
            {ELEMENT_TYPE_LABELS[element.type]}
            {isAgentOwned(element) && ' · added to this design'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            props.onChange('locked', !element.locked)
            props.onCommit()
          }}
          title={element.locked ? 'Unlock this element' : 'Lock this element'}
          className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 transition ${
            element.locked
              ? 'bg-beige text-brand ring-brand/30'
              : 'bg-subtle text-muted ring-line hover:text-ink'
          }`}
        >
          {element.locked ? 'Locked' : 'Unlocked'}
        </button>
      </div>

      {props.error && (
        <p role="alert" className="rounded-md bg-rose-50 px-2 py-1 text-xs text-rose-700">
          {props.error}
        </p>
      )}

      {element.locked && (
        <p className="rounded-control bg-subtle px-3 py-2 text-[11px] leading-relaxed text-muted">
          This element is locked, so it cannot be dragged or resized on the
          canvas. Its properties are still editable here, and the badge above
          unlocks it.
        </p>
      )}

      {element.bound_to && <BindingRow element={element} onSync={props.onSyncToData ?? (() => {})} />}

      {/* One panel per type. A button is text plus a fill, so it gets both;
          a line is a shape with no fill of its own to speak of; a background
          is whichever of the two it currently is. */}
      {kind === 'text' && <TextProperties {...props} element={element} />}
      {(kind === 'image' || (kind === 'background' && element.content)) && (
        <ImageProperties {...props} element={element} />
      )}
      {(kind === 'shape' || kind === 'background' || element.type === 'button') && (
        <ShapeProperties {...props} element={element} />
      )}
      <GeometryProperties {...props} element={element} />

      {canReset(element) && (
        <button
          type="button"
          onClick={props.onReset ?? props.onClear}
          className="text-xs font-medium text-muted underline underline-offset-2 hover:text-ink"
        >
          Reset this element to the template
        </button>
      )}
    </div>
  )
}

/**
 * Where this element's content comes from, and how to get it back.
 *
 * Shown only for a bound element. When the agent has typed over it, this is
 * the "sync to current data" affordance — and the reason the binding is
 * flagged rather than deleted on a manual edit: deleting it would leave
 * nothing to sync back to.
 */
function BindingRow({
  element,
  onSync,
}: {
  element: ResolvedElement
  onSync: () => void
}) {
  return (
    <div className="rounded-control border border-line bg-subtle px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-ink">
          Filled from property data
        </span>
        {element.manually_overridden && (
          <button
            type="button"
            onClick={onSync}
            className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold text-brand transition hover:bg-hover"
          >
            Sync to current data
          </button>
        )}
      </div>
      <p className="mt-0.5 truncate text-[11px] text-muted">
        {element.manually_overridden
          ? `Customised. The data says: ${element.bound_value || '(empty)'}`
          : element.bound_value || '(this field is empty)'}
      </p>
    </div>
  )
}

function TextProperties({
  element,
  onChange,
  onCommit,
}: Props & { element: ResolvedElement }) {
  const constraints = element.constraints ?? {}
  const value = (field: string, fallback: unknown) => element.style[field] ?? fallback

  const text = String(element.content ?? '')
  const weight = String(value('font_weight', '400'))
  const align = String(value('text_align', 'left'))

  return (
    <div className="space-y-3">
      {(
        <PropertyRow
          label="Content"
          hint={constraints.max_length ? `${text.length}/${constraints.max_length}` : undefined}
        >
          <textarea
            rows={3}
            maxLength={constraints.max_length}
            value={text}
            onChange={(event) => onChange('text', event.target.value)}
            onBlur={onCommit}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
          />
        </PropertyRow>
      )}

      <PropertyRow label="Font">
        <p className="text-xs italic text-slate-400" title={FONT_FIXED_REASON}>
          {SAFE_FONT_LABEL} — the only family the renderer has
        </p>
      </PropertyRow>

      {(
        <PropertyRow label="Size" hint={`${(Number(value('font_size_ratio', 0.04)) * 100).toFixed(1)}%`}>
          <SliderControl
            className="w-full"
            min={0.01}
            max={0.25}
            step={0.002}
            value={Number(value('font_size_ratio', 0.04))}
            onChange={(next) => onChange('font_size_ratio', next)}
            onCommit={onCommit}
            format={() => ''}
          />
        </PropertyRow>
      )}

      {(
        <PropertyRow label="Weight">
          <select
            value={weight}
            onChange={(event) => onChange('font_weight', event.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs outline-none focus:border-slate-900"
          >
            {['300', '400', '500', '600', '700', '800', '900'].map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </PropertyRow>
      )}

      {(
        <PropertyRow label="Colour">
          <ColorControl
            value={String(value('color', '#000000'))}
              onChange={(next) => onChange('color', next)}
          />
        </PropertyRow>
      )}

      {(
        <PropertyRow label="Alignment">
          <div className="flex gap-1">
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
          </div>
        </PropertyRow>
      )}

      {(
        <PropertyRow label="Line height" hint={Number(value('line_height', 1.2)).toFixed(2)}>
          <SliderControl
            className="w-full"
            min={0.8}
            max={3}
            step={0.05}
            value={Number(value('line_height', 1.2))}
            onChange={(next) => onChange('line_height', next)}
            onCommit={onCommit}
            format={() => ''}
          />
        </PropertyRow>
      )}

      {(
        <PropertyRow
          label="Letter spacing"
          hint={`${Number(value('letter_spacing_em', 0)).toFixed(2)}em`}
        >
          <SliderControl
            className="w-full"
            min={-0.1}
            max={1}
            step={0.01}
            value={Number(value('letter_spacing_em', 0))}
            onChange={(next) => onChange('letter_spacing_em', next)}
            onCommit={onCommit}
            format={() => ''}
          />
        </PropertyRow>
      )}
    </div>
  )
}

function ImageProperties({
  element,
  onChange,
  onCommit,
  listingPhotos,
  onPickPhoto,
  onUploadFile,
  uploading,
}: Props & { element: ResolvedElement }) {
  const value = (field: string, fallback: unknown) => element.style[field] ?? fallback
  const fit = String(value('object_fit', 'cover'))

  return (
    <div className="space-y-3">
      {element.content && (
        <img
          src={element.content}
          alt=""
          className="h-20 w-full rounded border border-slate-200 object-cover"
        />
      )}

      {(
        <PropertyRow label="Replace">
          <ImageReplaceControl
            listingPhotos={listingPhotos}
            onPickPhoto={onPickPhoto}
            onUploadFile={onUploadFile}
            uploading={uploading}
          />
        </PropertyRow>
      )}

      {(
        <PropertyRow label="Crop position" hint={String(value('object_position', 'center center'))}>
          <PositionGrid
            value={String(value('object_position', 'center center'))}
            onChange={(next) => onChange('object_position', next)}
          />
        </PropertyRow>
      )}

      {(
        <PropertyRow label="Object fit">
          <div className="flex gap-1">
            {(['cover', 'contain', 'fill'] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onChange('object_fit', option)}
                className={`rounded-md border px-2 py-1 text-xs capitalize transition ${
                  fit === option
                    ? 'border-slate-900 bg-slate-900 text-white'
                    : 'border-slate-300 text-slate-600 hover:bg-slate-50'
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </PropertyRow>
      )}

      {(
        <PropertyRow label="Opacity" hint={`${Math.round(Number(value('opacity', 1)) * 100)}%`}>
          <SliderControl
            className="w-full"
            min={0}
            max={1}
            step={0.05}
            value={Number(value('opacity', 1))}
            onChange={(next) => onChange('opacity', next)}
            onCommit={onCommit}
            format={() => ''}
          />
        </PropertyRow>
      )}

      {(
        <PropertyRow
          label="Corner radius"
          hint={`${(Number(value('border_radius_ratio', 0)) * 100).toFixed(1)}%`}
        >
          <SliderControl
            className="w-full"
            min={0}
            max={0.5}
            step={0.005}
            value={Number(value('border_radius_ratio', 0))}
            onChange={(next) => onChange('border_radius_ratio', next)}
            onCommit={onCommit}
            format={() => ''}
          />
        </PropertyRow>
      )}
    </div>
  )
}

function ShapeProperties({
  element,
  onChange,
  onCommit,
}: Props & { element: ResolvedElement }) {
  const value = (field: string, fallback: unknown) => element.style[field] ?? fallback

  return (
    <div className="space-y-3">
      {(
        <PropertyRow label="Fill">
          <ColorControl
            value={String(value('background_color', '#000000'))}
              onChange={(next) => onChange('background_color', next)}
          />
        </PropertyRow>
      )}

      {(
        <PropertyRow
          label="Border width"
          hint={`${(Number(value('border_width_ratio', 0)) * 100).toFixed(1)}%`}
        >
          <SliderControl
            className="w-full"
            min={0}
            max={0.05}
            step={0.001}
            value={Number(value('border_width_ratio', 0))}
            onChange={(next) => onChange('border_width_ratio', next)}
            onCommit={onCommit}
            format={() => ''}
          />
        </PropertyRow>
      )}

      {(
        <PropertyRow label="Border colour">
          <ColorControl
            value={String(value('border_color', '#000000'))}
              onChange={(next) => onChange('border_color', next)}
          />
        </PropertyRow>
      )}

      {(
        <PropertyRow label="Opacity" hint={`${Math.round(Number(value('opacity', 1)) * 100)}%`}>
          <SliderControl
            className="w-full"
            min={0}
            max={1}
            step={0.05}
            value={Number(value('opacity', 1))}
            onChange={(next) => onChange('opacity', next)}
            onCommit={onCommit}
            format={() => ''}
          />
        </PropertyRow>
      )}

      {(
        <PropertyRow
          label="Corner radius"
          hint={`${(Number(value('border_radius_ratio', 0)) * 100).toFixed(1)}%`}
        >
          <SliderControl
            className="w-full"
            min={0}
            max={0.5}
            step={0.005}
            value={Number(value('border_radius_ratio', 0))}
            onChange={(next) => onChange('border_radius_ratio', next)}
            onCommit={onCommit}
            format={() => ''}
          />
        </PropertyRow>
      )}
    </div>
  )
}

/**
 * X / Y / width / height / rotation.
 *
 * Rendered for every non-locked element, but disabled unless geometry is
 * actually editable — the spec calls for content-only elements to *disable*
 * position and size rather than hide them, and seeing the numbers is useful
 * even when they're not yours to change.
 */
function GeometryProperties({
  element,
  onChange,
  onCommit,
}: Props & { element: ResolvedElement }) {
  const editable = !element.locked
  const geometry = element.geometry
  const set = (field: keyof Geometry, next: number) => onChange('geometry', { ...geometry, [field]: next })

  return (
    <div className="space-y-2 border-t border-slate-100 pt-3">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-semibold text-slate-600">Position &amp; size</span>
        {!editable && (
          <span className="text-[10px] uppercase tracking-wide text-slate-400">
            Fixed by template
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <PropertyRow label="X">
          <PercentField
            value={geometry.x}
            disabled={!editable}
            onChange={(next) => set('x', next)}
            onCommit={onCommit}
          />
        </PropertyRow>
        <PropertyRow label="Y">
          <PercentField
            value={geometry.y}
            disabled={!editable}
            onChange={(next) => set('y', next)}
            onCommit={onCommit}
          />
        </PropertyRow>
        <PropertyRow label="Width">
          <PercentField
            value={geometry.width}
            disabled={!editable}
            onChange={(next) => set('width', next)}
            onCommit={onCommit}
          />
        </PropertyRow>
        <PropertyRow label="Height">
          <PercentField
            value={geometry.height}
            disabled={!editable}
            onChange={(next) => set('height', next)}
            onCommit={onCommit}
          />
        </PropertyRow>
      </div>

      <PropertyRow label="Rotation" hint={`${Math.round(geometry.rotation)}°`}>
        <SliderControl
          className="w-full"
          min={-180}
          max={180}
          step={1}
          value={geometry.rotation}
          disabled={!editable}
          onChange={(next) => set('rotation', next)}
          onCommit={onCommit}
          format={() => ''}
        />
      </PropertyRow>
    </div>
  )
}
