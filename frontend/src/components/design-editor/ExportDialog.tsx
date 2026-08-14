/**
 * Export, as a dialog rather than a panel pinned beside the canvas.
 *
 * Exporting is a decision you make a handful of times, at the end. Giving it
 * a permanent 340px column meant the size checkboxes were on screen for the
 * entire hour you spent moving a photo two pixels; giving it a dialog means
 * the canvas keeps that space and the decision gets the whole reader's
 * attention when it is actually being made.
 *
 * WHY COMPLIANCE IS IN HERE
 * ---------------------------------------------------------------------------
 * The flags are no longer pinned open in the editor — they live on the rail's
 * bell, which an agent may never click. This dialog is the one place they
 * cannot be skipped: the report sits directly above the button that commits
 * the export, so nobody exports past a warning without having been shown it.
 * A report that blocks export disables the button rather than letting the
 * server refuse a request it already knows the answer to.
 */

import { useEffect } from 'react'

import type { ComplianceReport } from '../../api/compliance.ts'
import type { DesignExport, ExportFormat, RenderDimension } from '../../api/templates.ts'
import { CompliancePanel } from '../CompliancePanel.tsx'

type Props = {
  designName: string
  dimensions: RenderDimension[]
  selected: string[]
  onSelectedChange: (keys: string[]) => void
  format: ExportFormat
  onFormatChange: (format: ExportFormat) => void
  compliance: ComplianceReport | null
  checkingCompliance: boolean
  exports: DesignExport[]
  busy: boolean
  error: string | null
  onExport: () => void
  onClose: () => void
}

export default function ExportDialog({
  designName,
  dimensions,
  selected,
  onSelectedChange,
  format,
  onFormatChange,
  compliance,
  checkingCompliance,
  exports,
  busy,
  error,
  onExport,
  onClose,
}: Props) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  const blocked = Boolean(compliance?.blocks_export)

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Export ${designName}`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose()
      }}
    >
      <div className="flex max-h-full w-full max-w-lg flex-col overflow-hidden rounded-panel border border-line bg-surface shadow-pop">
        <div className="flex items-start gap-2 border-b border-line px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold text-ink">Export</h2>
            <p className="mt-0.5 truncate text-[11px] text-muted">{designName}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
            className="-mr-1 flex size-7 shrink-0 items-center justify-center rounded-control text-lg leading-none text-muted transition hover:bg-hover hover:text-ink disabled:opacity-40"
          >
            ×
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          {error && (
            <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {error}
            </p>
          )}

          <section>
            <h3 className="text-[12px] font-semibold text-ink">Sizes</h3>
            <div className="mt-2 space-y-1.5">
              {dimensions.map((option) => (
                <label key={option.key} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={selected.includes(option.key)}
                    onChange={(event) =>
                      onSelectedChange(
                        event.target.checked
                          ? [...selected, option.key]
                          : selected.filter((key) => key !== option.key),
                      )
                    }
                    className="accent-slate-900"
                  />
                  <span>{option.label}</span>
                  <span className="ml-auto text-xs text-muted">
                    {option.width}×{option.height}
                  </span>
                </label>
              ))}
            </div>
          </section>

          <section>
            <h3 className="text-[12px] font-semibold text-ink">Format</h3>
            <div className="mt-2 flex items-center gap-2">
              {(['png', 'jpg', 'pdf'] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => onFormatChange(option)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium uppercase transition ${
                    format === option
                      ? 'bg-slate-900 text-white'
                      : 'text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
          </section>

          <section>
            <h3 className="text-[12px] font-semibold text-ink">Compliance</h3>
            <div className="mt-2">
              <CompliancePanel report={compliance} loading={checkingCompliance} collapsible />
              {!checkingCompliance && !compliance && (
                <p className="text-xs text-muted">
                  These checks could not be run just now. The server re-checks on
                  export regardless.
                </p>
              )}
            </div>
          </section>

          {exports.length > 0 && (
            <section>
              <h3 className="text-[12px] font-semibold text-ink">
                Already exported ({exports.length})
              </h3>
              <ul className="mt-2 space-y-2 text-sm">
                {exports.map((item) => (
                  <li key={item.id} className="flex items-center gap-2">
                    {item.image_url && (
                      <img
                        src={item.image_url}
                        alt=""
                        className="size-9 rounded border border-line object-cover"
                      />
                    )}
                    <span className="min-w-0 flex-1 truncate">
                      {item.dimension_label}
                      <span className="ml-1 text-xs uppercase text-muted">
                        {item.export_format}
                      </span>
                    </span>
                    {item.image_url && (
                      <a
                        href={item.image_url}
                        download
                        className="shrink-0 text-xs font-medium text-muted underline underline-offset-2 hover:text-ink"
                      >
                        Download
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <div className="flex items-center gap-2 border-t border-line px-4 py-3">
          {blocked && (
            <p className="mr-auto text-[11px] font-medium text-rose-700">
              Fix the issues above to export.
            </p>
          )}
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className={`rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink transition hover:bg-hover disabled:opacity-50 ${
              blocked ? '' : 'ml-auto'
            }`}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onExport}
            disabled={busy || blocked || selected.length === 0}
            className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:opacity-50"
          >
            {busy
              ? 'Exporting…'
              : `Export ${selected.length} image${selected.length === 1 ? '' : 's'}`}
          </button>
        </div>
      </div>
    </div>
  )
}
