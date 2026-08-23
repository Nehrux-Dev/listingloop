/**
 * The small input primitives the contextual toolbar and the properties
 * sidebar both use.
 *
 * They live here rather than in either consumer because the toolbar and the
 * sidebar deliberately expose overlapping controls (size, colour, fit, ...) —
 * the toolbar as a compact strip, the sidebar as a labelled list. Sharing the
 * primitives is what keeps a value edited in one place from behaving
 * differently when edited in the other.
 *
 * None of these decide *whether* a control is allowed; callers do that from
 * `editable_fields`. These only render.
 */

import { useRef, useState } from 'react'

import type { ListingPhoto } from '../../api/listings.ts'
import type { BrandKit } from '../../api/profiles.ts'

/** A named row of colour swatches for ColorControl — brand tokens, colours
 *  already in the design, or a preset palette. */
export type SwatchSection = {
  label: string
  colors: string[]
  /** Rendered inside a closed disclosure — for the preset palettes, which
   *  would otherwise turn every colour row into a wall of swatches. */
  collapsed?: boolean
}

export function ToggleButton({
  active,
  onClick,
  label,
  disabled,
  children,
}: {
  active: boolean
  onClick: () => void
  label: string
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={label}
      disabled={disabled}
      className={`flex size-7 shrink-0 items-center justify-center rounded-md border text-xs transition disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? 'border-brand bg-brand text-white'
          : 'border-line text-muted hover:bg-hover'
      }`}
    >
      {children}
    </button>
  )
}

export function ToolbarGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="whitespace-nowrap text-[10px] font-semibold uppercase tracking-wide text-muted">{label}</span>
      <div className="flex items-center gap-1">{children}</div>
    </div>
  )
}

/** A labelled row in the properties sidebar. */
export function PropertyRow({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-medium text-muted">{label}</span>
        {hint && <span className="text-[10px] tabular-nums text-muted">{hint}</span>}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  )
}

/**
 * A slider plus its numeric readout.
 *
 * `onCommit` fires on release, separately from `onChange` on every step —
 * the caller uses that to decide when a drag becomes one undo entry rather
 * than a hundred.
 */
export function SliderControl({
  min,
  max,
  step,
  value,
  onChange,
  onCommit,
  disabled,
  format,
  className = 'w-24',
}: {
  min: number
  max: number
  step: number
  value: number
  onChange: (value: number) => void
  onCommit?: () => void
  disabled?: boolean
  format?: (value: number) => string
  className?: string
}) {
  return (
    <span className="flex items-center gap-1.5">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        onPointerUp={onCommit}
        onKeyUp={onCommit}
        className={`${className} accent-brand disabled:cursor-not-allowed disabled:opacity-40`}
      />
      <span className="w-11 shrink-0 text-right text-[11px] tabular-nums text-muted">
        {format ? format(value) : value.toFixed(2)}
      </span>
    </span>
  )
}

/**
 * A number input that reports its value as a percentage but stores a 0–1
 * fraction — the geometry inputs in the sidebar.
 *
 * Deliberately uncontrolled while focused: retyping "12" into a field
 * showing "12.5" would otherwise fight the caret as each keystroke
 * round-trips through normalized geometry and back.
 */
export function PercentField({
  value,
  onChange,
  onCommit,
  disabled,
  min = 0,
  max = 100,
}: {
  value: number
  onChange: (fraction: number) => void
  onCommit?: () => void
  disabled?: boolean
  min?: number
  max?: number
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const shown = draft ?? (value * 100).toFixed(1)

  return (
    <input
      type="number"
      inputMode="decimal"
      step={0.1}
      min={min}
      max={max}
      disabled={disabled}
      value={shown}
      onChange={(event) => {
        setDraft(event.target.value)
        const parsed = Number(event.target.value)
        if (Number.isFinite(parsed)) onChange(parsed / 100)
      }}
      onBlur={() => {
        setDraft(null)
        onCommit?.()
      }}
      className="w-full rounded-md border border-line px-2 py-1 text-xs tabular-nums outline-none focus:border-brand focus:ring-1 focus:ring-brand disabled:cursor-not-allowed disabled:bg-subtle disabled:text-muted"
    />
  )
}

/**
 * What a colour value should look like in a swatch.
 *
 * `@accent_color` and friends are brand tokens, not hex — they resolve at
 * render time from the agent's brand kit. When the kit is available the
 * swatch shows the real colour; the fallbacks below are only for when it is
 * not loaded yet. Previously these fallbacks were shown unconditionally,
 * which meant a swatch could advertise blue for an accent that renders red.
 */
function swatchColor(value: string, brandKit?: BrandKit | null): string {
  if (!value.startsWith('@')) return value

  if (brandKit) {
    const resolved = (brandKit as unknown as Record<string, unknown>)[value.slice(1)]
    if (typeof resolved === 'string' && resolved) return resolved
  }

  return (
    { '@primary_color': '#1F2937', '@secondary_color': '#4B5563', '@accent_color': '#8B4F24' }[
      value
    ] ?? '#94A3B8'
  )
}

function swatchLabel(value: string): string {
  return value.startsWith('@') ? value.slice(1).replace(/_/g, ' ') : value
}

/**
 * Swatches when the template supplies an allowlist, a free picker when it
 * doesn't — offering a full picker for values the server will reject is a
 * worse experience than not offering them at all.
 */
export function ColorControl({
  value,
  options,
  onChange,
  disabled,
  brandKit,
  sections,
}: {
  value: string
  options?: string[]
  onChange: (value: string) => void
  disabled?: boolean
  /** Lets a `@token` swatch show the colour it will actually render as. */
  brandKit?: BrandKit | null
  /** Optional swatch rows above the free picker: brand tokens, the design's
   *  own colours, preset palettes. Purely additive — the picker still accepts
   *  any colour, and callers that pass nothing get the old control. */
  sections?: SwatchSection[]
}) {
  if (options && options.length > 0) {
    return (
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            disabled={disabled}
            title={swatchLabel(option)}
            onClick={() => onChange(option)}
            className={`size-7 rounded-md border transition disabled:cursor-not-allowed disabled:opacity-40 ${
              value.toLowerCase() === option.toLowerCase()
                ? 'border-brand ring-2 ring-brand ring-offset-1'
                : 'border-line hover:border-brand/60'
            }`}
            style={{ backgroundColor: swatchColor(option, brandKit) }}
          />
        ))}
      </div>
    )
  }

  const open = (sections ?? []).filter((section) => !section.collapsed && section.colors.length > 0)
  const collapsed = (sections ?? []).filter((section) => section.collapsed && section.colors.length > 0)

  const swatchRow = (section: SwatchSection) => (
    <div key={section.label}>
      <p className="mb-0.5 text-[10px] font-medium text-muted">{section.label}</p>
      <div className="flex flex-wrap gap-1">
        {section.colors.map((color) => (
          <button
            key={`${section.label}-${color}`}
            type="button"
            disabled={disabled}
            title={swatchLabel(color)}
            onClick={() => onChange(color)}
            className={`size-5 rounded border transition disabled:cursor-not-allowed disabled:opacity-40 ${
              value.toLowerCase() === color.toLowerCase()
                ? 'border-brand ring-1 ring-brand'
                : 'border-line hover:border-brand/60'
            }`}
            style={{ backgroundColor: swatchColor(color, brandKit) }}
          />
        ))}
      </div>
    </div>
  )

  return (
    <div className="space-y-1.5">
      <input
        type="color"
        disabled={disabled}
        value={/^#[0-9a-fA-F]{6}$/.test(value) ? value : '#000000'}
        onChange={(event) => onChange(event.target.value.toUpperCase())}
        className="size-8 cursor-pointer rounded border border-line bg-surface p-0.5 disabled:cursor-not-allowed disabled:opacity-40"
      />
      {open.map(swatchRow)}
      {collapsed.length > 0 && (
        <details>
          <summary className="cursor-pointer select-none text-[10px] font-medium text-muted hover:text-ink">
            Palettes
          </summary>
          <div className="mt-1 space-y-1.5">{collapsed.map(swatchRow)}</div>
        </details>
      )}
    </div>
  )
}

export const OBJECT_POSITIONS = [
  'left top', 'center top', 'right top',
  'left center', 'center center', 'right center',
  'left bottom', 'center bottom', 'right bottom',
] as const

/** The nine-way crop grid — which part of the photo survives the frame. */
export function PositionGrid({
  value,
  onChange,
  disabled,
}: {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  return (
    <div className="inline-grid grid-cols-3 gap-0.5 rounded-control border border-line bg-surface p-0.5">
      {OBJECT_POSITIONS.map((position) => (
        <button
          key={position}
          type="button"
          title={position}
          disabled={disabled}
          onClick={() => onChange(position)}
          className={`size-4 rounded-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${
            value === position ? 'bg-brand' : 'bg-beige hover:bg-active'
          }`}
        />
      ))}
    </div>
  )
}

/**
 * "Replace image": pick one of the listing's photos, or upload a new file.
 *
 * Only ever sets `image_key` — never geometry, z-index or border radius — so
 * the replacement lands in exactly the frame the template drew.
 */
export function ImageReplaceControl({
  listingPhotos,
  onPickPhoto,
  onUploadFile,
  uploading,
  disabled,
}: {
  listingPhotos: ListingPhoto[]
  onPickPhoto: (imageKey: string, previewUrl: string) => void
  onUploadFile: (file: File) => void
  uploading: boolean
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  return (
    <div className="space-y-2">
      <button
        type="button"
        disabled={disabled || uploading}
        onClick={() => setOpen((current) => !current)}
        className={`rounded-md border px-2 py-1 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
          open
            ? 'border-brand bg-brand text-white'
            : 'border-slate-300 text-slate-700 hover:bg-slate-50'
        }`}
      >
        {uploading ? 'Uploading…' : 'Choose image'}
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onUploadFile(file)
          event.target.value = ''
          setOpen(false)
        }}
      />

      {open && (
        <div className="rounded-md border border-line bg-subtle p-2">
          <p className="mb-1.5 text-[11px] text-muted">
            Pick one of this listing's photos, or{' '}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="font-medium underline underline-offset-2 hover:text-slate-800"
            >
              upload a new image
            </button>
            .
          </p>
          {listingPhotos.length === 0 ? (
            <p className="text-[11px] italic text-muted">No listing photos yet.</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {listingPhotos.map((photo) => (
                <button
                  key={photo.id}
                  type="button"
                  onClick={() => {
                    onPickPhoto(photo.image_key, photo.image_url ?? '')
                    setOpen(false)
                  }}
                  title={photo.caption || undefined}
                  className="size-12 shrink-0 overflow-hidden rounded-control border border-line transition hover:border-brand"
                >
                  {photo.image_url && (
                    <img src={photo.image_url} alt="" className="size-full object-cover" />
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
