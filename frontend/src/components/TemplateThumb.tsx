/**
 * A template's thumbnail.
 *
 * Two cases, and the difference is whether the template has ever been a
 * picture. A template imported from artwork keeps the rasterised source page
 * (`source_image_url`), which is exactly what the design looks like, so that
 * is what the grid shows. A Nehrux library template stores a layout and
 * nothing else — rendering one per tile would be a Chromium process per tile —
 * so it falls back to a gradient derived from its style, which at least makes
 * the grid scannable and keeps one template looking like itself everywhere it
 * appears.
 *
 * When library templates get real previews too, this is still the one
 * component that has to change.
 */

import type { TemplateSummary } from '../api/templates.ts'

const STYLE_SWATCH: Record<string, string> = {
  bold: 'from-slate-900 to-slate-700',
  minimal: 'from-slate-200 to-slate-100',
  luxury: 'from-stone-800 to-amber-700',
  warm: 'from-orange-300 to-rose-300',
  editorial: 'from-slate-700 to-slate-500',
  classic: 'from-emerald-900 to-emerald-700',
}

export default function TemplateThumb({
  template,
  className = 'h-32',
  showStyleLabel = true,
  style,
  children,
}: {
  template: TemplateSummary
  /** Height (and any other box utilities) for the surface this sits in. */
  className?: string
  showStyleLabel?: boolean
  /** For `aspectRatio`, which is a computed number rather than one of a
   *  handful of utility classes — the gallery sizes each card to the true
   *  shape of the format the template was composed for. */
  style?: React.CSSProperties
  /** Overlays — a "current" pip, a busy state. */
  children?: React.ReactNode
}) {
  const preview = template.source_image_url

  return (
    <div
      style={style}
      className={`relative flex items-end overflow-hidden p-2 ${
        preview
          ? 'bg-slate-100'
          : `bg-gradient-to-br ${STYLE_SWATCH[template.style] ?? 'from-slate-300 to-slate-200'}`
      } ${className}`}
    >
      {preview && (
        <img
          src={preview}
          alt=""
          /* Decorative: the card's own text already names the template, and a
             second copy of that name would just be read out twice. */
          aria-hidden="true"
          loading="lazy"
          /* `contain`, not `cover`: the whole composition is the point of the
             preview, and cropping the top off a flyer to fill a tile hides the
             headline that identifies it. */
          className="absolute inset-0 size-full object-contain"
        />
      )}
      {showStyleLabel && (
        <span className="relative rounded bg-white/90 px-1.5 py-0.5 text-[10px] font-medium text-slate-700">
          {template.style_display}
        </span>
      )}
      {children}
    </div>
  )
}
