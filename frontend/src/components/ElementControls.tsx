/**
 * Permission-aware controls for one template element.
 *
 * The controls rendered here are derived from `editable_fields`, which the API
 * supplies per element — so the UI cannot drift from the server's rules by
 * inventing its own copy of the permission table.
 *
 * This is UX, not security. Everything below is re-validated server-side in
 * `apps/templates/overrides.py` on every write; a user who removes the
 * `disabled` attribute in devtools gets a 400, not an edit.
 */

import type {
  ElementConstraints,
  ElementPermission,
  Geometry,
  ResolvedElement,
} from '../api/templates.ts'
import { PERMISSION_HINTS, PERMISSION_LABELS } from '../api/templates.ts'

const PERMISSION_BADGE: Record<ElementPermission, string> = {
  locked: 'bg-slate-100 text-slate-600 ring-slate-200',
  content_only: 'bg-sky-50 text-sky-700 ring-sky-200',
  styled: 'bg-violet-50 text-violet-700 ring-violet-200',
  free: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
}

/**
 * Brand references (`@accent_color`) are stored as tokens, not hex.
 *
 * These are only stand-ins for when the real kit is not to hand — this panel
 * is not passed one. The canvas toolbar's equivalent resolves the actual
 * brand colour (see controls.tsx::swatchColor); until this panel does too, a
 * neutral warm fallback is the honest choice. The previous `#2563EB` was a
 * bright blue advertising an accent that renders red for this brokerage.
 */
function swatchColor(value: string): string {
  if (!value.startsWith('@')) return value
  return { '@primary_color': '#1F2937', '@secondary_color': '#4B5563', '@accent_color': '#8B4F24' }[
    value
  ] ?? '#94A3B8'
}

function swatchLabel(value: string): string {
  return value.startsWith('@') ? value.slice(1).replace(/_/g, ' ') : value
}

type Props = {
  element: ResolvedElement
  editableFields: string[]
  override: Record<string, unknown>
  onChange: (field: string, value: unknown) => void
  onClear: () => void
  error?: string
}

export function ElementControls({
  element,
  editableFields,
  override,
  onChange,
  onClear,
  error,
}: Props) {
  const can = (field: string) => editableFields.includes(field)
  const constraints: ElementConstraints = element.constraints ?? {}
  const isEdited = Object.keys(override).length > 0

  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-slate-800">
            {element.label || element.key}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">
            {PERMISSION_HINTS[element.permission]}
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${
            PERMISSION_BADGE[element.permission]
          }`}
        >
          {PERMISSION_LABELS[element.permission]}
        </span>
      </div>

      {error && (
        <p role="alert" className="mt-2 rounded-md bg-rose-50 px-2 py-1 text-xs text-rose-700">
          {error}
        </p>
      )}

      {/* Locked: show the value so the agent knows what is there, with no
          affordance to change it. An image-bearing element's "value" is a
          (potentially huge) data URI — including static_graphic, which is
          locked by convention — so that case gets a thumbnail instead of
          dumping kilobytes of base64 as literal text. */}
      {element.permission === 'locked' &&
        (['image', 'logo', 'static_graphic'].includes(element.element_type) ? (
          <div className="mt-3">
            {element.content ? (
              <img
                src={String(element.content)}
                alt=""
                className="size-12 rounded border border-slate-200 object-cover"
              />
            ) : (
              <span className="text-sm italic text-slate-500">Set by the template</span>
            )}
          </div>
        ) : (
          <p className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-500">
            {element.content || <span className="italic">Set by the template</span>}
          </p>
        ))}

      {element.permission !== 'locked' && (
        <div className="mt-3 space-y-3">
          {can('text') && ['text', 'badge'].includes(element.element_type) && (
            <label className="block">
              <span className="text-xs font-medium text-slate-600">Text</span>
              <textarea
                rows={2}
                maxLength={constraints.max_length}
                value={String(override.text ?? element.content ?? '')}
                onChange={(event) => onChange('text', event.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
              />
              {constraints.max_length && (
                <span className="text-[11px] text-slate-400">
                  {String(override.text ?? element.content ?? '').length}/
                  {constraints.max_length}
                </span>
              )}
            </label>
          )}

          {['image', 'logo', 'static_graphic'].includes(element.element_type) && (
            <div className="flex items-center gap-3">
              {element.content ? (
                <img
                  src={String(element.content)}
                  alt=""
                  className="size-12 rounded border border-slate-200 object-cover"
                />
              ) : (
                <div className="flex size-12 items-center justify-center rounded border border-dashed border-slate-300 text-[10px] text-slate-400">
                  none
                </div>
              )}
              <p className="text-xs text-slate-500">
                Select this element on the canvas above to replace, fit or reposition
                the image.
              </p>
            </div>
          )}

          {can('color') && (
            <ColorChoice
              label="Text colour"
              value={String(override.color ?? element.style.color ?? '')}
              options={constraints.allowed_colors}
              onChange={(value) => onChange('color', value)}
            />
          )}

          {can('background_color') && (
            <ColorChoice
              label="Background"
              value={String(override.background_color ?? element.style.background_color ?? '')}
              options={constraints.allowed_colors}
              onChange={(value) => onChange('background_color', value)}
            />
          )}

          {can('font_size_ratio') && (
            <label className="block">
              <span className="text-xs font-medium text-slate-600">
                Size{' '}
                <span className="text-slate-400">
                  {(
                    Number(override.font_size_ratio ?? element.style.font_size_ratio ?? 0.04) * 100
                  ).toFixed(1)}
                  % of height
                </span>
              </span>
              <input
                type="range"
                min={constraints.min_font_size_ratio ?? 0.01}
                max={constraints.max_font_size_ratio ?? 0.25}
                step={0.002}
                value={Number(
                  override.font_size_ratio ?? element.style.font_size_ratio ?? 0.04,
                )}
                onChange={(event) => onChange('font_size_ratio', Number(event.target.value))}
                className="mt-1 w-full accent-slate-900"
              />
            </label>
          )}

          {can('geometry') && (
            <GeometryControls
              value={(override.geometry as Geometry) ?? element.geometry}
              bounds={constraints.bounds}
              onChange={(geometry) => onChange('geometry', geometry)}
            />
          )}

          {isEdited && (
            <button
              type="button"
              onClick={onClear}
              className="text-xs font-medium text-slate-500 underline underline-offset-2 hover:text-slate-700"
            >
              Reset to template default
            </button>
          )}
        </div>
      )}
    </li>
  )
}

/** Exported for reuse by the canvas Toolbar's colour control — same swatch
 *  logic, same brand-token handling, so there is only one implementation of
 *  "how a colour override renders as a picker" in the app. */
export function ColorChoice({
  label,
  value,
  options,
  onChange,
}: {
  label?: string
  value: string
  options?: string[]
  onChange: (value: string) => void
}) {
  return (
    <div>
      {label && <span className="text-xs font-medium text-slate-600">{label}</span>}
      {options && options.length > 0 ? (
        // An allowlist means swatches, not a colour picker: offering a picker
        // for values the server will reject is a worse experience than not
        // offering them at all.
        <div className="mt-1 flex flex-wrap gap-1.5">
          {options.map((option) => (
            <button
              key={option}
              type="button"
              title={swatchLabel(option)}
              onClick={() => onChange(option)}
              className={`size-7 rounded-md border transition ${
                value.toLowerCase() === option.toLowerCase()
                  ? 'border-slate-900 ring-2 ring-slate-900 ring-offset-1'
                  : 'border-slate-300 hover:border-slate-500'
              }`}
              style={{ backgroundColor: swatchColor(option) }}
            />
          ))}
        </div>
      ) : (
        <input
          type="color"
          value={/^#[0-9a-fA-F]{6}$/.test(value) ? value : '#000000'}
          onChange={(event) => onChange(event.target.value.toUpperCase())}
          className="mt-1 size-8 cursor-pointer rounded border border-slate-300 bg-white p-0.5"
        />
      )}
    </div>
  )
}

function GeometryControls({
  value,
  bounds,
  onChange,
}: {
  value: Geometry
  bounds?: Geometry
  onChange: (geometry: Geometry) => void
}) {
  // Sliders are clamped to the template's bounds so the common case never
  // produces a rejected save. The server still enforces them.
  const limits = bounds ?? { x: 0, y: 0, width: 1, height: 1 }
  const maxX = Math.max(limits.x, limits.x + limits.width - value.width)
  const maxY = Math.max(limits.y, limits.y + limits.height - value.height)

  const set = (field: keyof Geometry, next: number) => onChange({ ...value, [field]: next })

  return (
    <div className="space-y-2 rounded-md bg-slate-50 p-3">
      <p className="text-xs font-medium text-slate-600">
        Position and size
        {bounds && (
          <span className="ml-1 font-normal text-slate-400">
            (movable within the template's area)
          </span>
        )}
      </p>
      <Slider label="Left" min={limits.x} max={maxX} value={value.x} onChange={(v) => set('x', v)} />
      <Slider label="Top" min={limits.y} max={maxY} value={value.y} onChange={(v) => set('y', v)} />
      <Slider
        label="Width"
        min={0.05}
        max={limits.width}
        value={value.width}
        onChange={(v) => set('width', v)}
      />
      <Slider
        label="Height"
        min={0.02}
        max={limits.height}
        value={value.height}
        onChange={(v) => set('height', v)}
      />
    </div>
  )
}

function Slider({
  label,
  min,
  max,
  value,
  onChange,
}: {
  label: string
  min: number
  max: number
  value: number
  onChange: (value: number) => void
}) {
  return (
    <label className="flex items-center gap-2">
      <span className="w-12 shrink-0 text-[11px] text-slate-500">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={0.005}
        value={Math.min(Math.max(value, min), max)}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-slate-900"
      />
      <span className="w-10 shrink-0 text-right text-[11px] tabular-nums text-slate-400">
        {(value * 100).toFixed(0)}%
      </span>
    </label>
  )
}
