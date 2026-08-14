/**
 * Upload a PDF or image and have it extracted into an editable template.
 *
 * WHAT THIS DIALOG IS RESPONSIBLE FOR, AND WHAT IT IS NOT
 * ---------------------------------------------------------------------------
 * It collects a file and two pieces of filing (occasion and style), and hands
 * them to the server. It does *not* wait for the extraction: that is a
 * minute-scale vision call on a worker, and a modal spinner held open for a
 * minute is a modal the user cannot escape from.
 *
 * So `onQueued` fires the moment the job is accepted and the dialog closes.
 * The gallery behind it owns the polling and shows the progress card, which
 * means the user can keep browsing — or queue a second import — while the
 * first one runs.
 *
 * The name is deliberately optional. Left blank, the extractor names the
 * template from the headline it read off the page, which is almost always
 * better than "flyer-final-v3.pdf".
 */

import { useRef, useState } from 'react'

import {
  importTemplate,
  type TemplateCategory,
  type TemplateImport,
  type TemplateStyle,
} from '../api/templates.ts'
import { ApiError } from '../lib/apiClient.ts'
import { Alert, fieldErrors } from './FormControls.tsx'
import { IconUpload } from './icons.tsx'

/** Mirrors IMPORT_EXTENSIONS in apps/templates/serializers.py. The server
 *  re-checks all of this — and sniffs the bytes, which a browser cannot — so
 *  this exists to keep the file picker useful, not to enforce anything. */
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp'

/** Mirrors MAX_TEMPLATE_IMPORT_MB. Checked here only so an oversized file is
 *  refused before it spends a minute uploading. */
const MAX_MB = 25

const CATEGORIES: { value: TemplateCategory; label: string }[] = [
  { value: 'new_listing', label: 'New Listing' },
  { value: 'coming_soon', label: 'Coming Soon' },
  { value: 'open_house', label: 'Open House' },
  { value: 'just_sold', label: 'Just Sold' },
  { value: 'price_reduced', label: 'Price Reduced' },
  { value: 'leased', label: 'Leased' },
  { value: 'agent_introduction', label: 'Agent Introduction' },
  { value: 'testimonial', label: 'Testimonial' },
  { value: 'market_update', label: 'Market Update' },
  { value: 'neighbourhood_guide', label: 'Neighbourhood Guide' },
]

const STYLES: { value: TemplateStyle; label: string }[] = [
  { value: 'minimal', label: 'Minimal' },
  { value: 'bold', label: 'Bold' },
  { value: 'luxury', label: 'Luxury' },
  { value: 'warm', label: 'Warm' },
  { value: 'editorial', label: 'Editorial' },
  { value: 'classic', label: 'Classic' },
]

export default function ImportTemplateDialog({
  onQueued,
  onClose,
}: {
  onQueued: (job: TemplateImport) => void
  onClose: () => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [category, setCategory] = useState<TemplateCategory>('new_listing')
  const [style, setStyle] = useState<TemplateStyle>('minimal')
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function chooseFile(next: File | null) {
    setError(null)
    if (next && next.size > MAX_MB * 1024 * 1024) {
      setError(`That file is larger than ${MAX_MB}MB. Export the design at a smaller size.`)
      return
    }
    setFile(next)
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!file || busy) return
    setBusy(true)
    setError(null)
    try {
      const job = await importTemplate({ file, name: name.trim(), category, style })
      onQueued(job)
    } catch (err) {
      // Field errors from the serializer arrive keyed by `file`; showing the
      // generic message instead would hide the only sentence that says what
      // was actually wrong with the upload.
      const fields = fieldErrors(err)
      setError(
        fields.file ??
          fields.detail ??
          (err instanceof ApiError ? err.message : 'That design could not be imported.'),
      )
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="import-template-title"
    >
      <form
        onSubmit={submit}
        className="max-h-full w-full max-w-lg overflow-y-auto rounded-panel border border-line bg-surface p-6 shadow-pop"
      >
        <h2 id="import-template-title" className="text-lg font-semibold tracking-tight">
          Import a design
        </h2>
        <p className="mt-1 text-sm text-muted">
          Upload a PDF or image of a finished design. Every element is measured
          off the page and becomes an editable layer — text, photos, shapes and
          all.
        </p>

        {error && (
          <div className="mt-4">
            <Alert kind="error">{error}</Alert>
          </div>
        )}

        {/* A drop target that is also a real file input, so keyboard and
            screen-reader users get the same control as a drag does. */}
        <label
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            chooseFile(event.dataTransfer.files?.[0] ?? null)
          }}
          className={`mt-4 flex cursor-pointer flex-col items-center gap-2 rounded-panel border-2 border-dashed px-6 py-8 text-center transition ${
            dragging ? 'border-brand bg-active' : 'border-line hover:border-brand/50'
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
          />
          <IconUpload className="size-6 text-muted" />
          {file ? (
            <>
              <span className="text-sm font-medium text-ink">{file.name}</span>
              <span className="text-xs text-muted">
                {(file.size / 1024 / 1024).toFixed(1)}MB · click to choose another
              </span>
            </>
          ) : (
            <>
              <span className="text-sm font-medium text-ink">
                Drop a design here, or click to choose
              </span>
              <span className="text-xs text-muted">PDF, PNG, JPG or WebP · up to {MAX_MB}MB</span>
            </>
          )}
        </label>
        <p className="mt-2 text-xs text-muted">
          Only the first page of a PDF is imported — a template is one
          composition.
        </p>

        <div className="mt-4 space-y-3">
          <label className="block">
            <span className="block text-sm font-medium text-ink">Name</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={160}
              placeholder="Taken from the design's headline if left blank"
              className="mt-1 w-full rounded-control border border-line bg-surface px-3 py-2 text-sm outline-none transition placeholder:text-muted focus:border-brand"
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-sm font-medium text-ink">Occasion</span>
              <select
                value={category}
                onChange={(event) => setCategory(event.target.value as TemplateCategory)}
                className="mt-1 w-full rounded-control border border-line bg-surface px-3 py-2 text-sm"
              >
                {CATEGORIES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="block text-sm font-medium text-ink">Style</span>
              <select
                value={style}
                onChange={(event) => setStyle(event.target.value as TemplateStyle)}
                className="mt-1 w-full rounded-control border border-line bg-surface px-3 py-2 text-sm"
              >
                {STYLES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-control border border-line px-4 py-2 text-sm font-medium transition hover:bg-hover disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!file || busy}
            className="rounded-control bg-brand px-4 py-2 text-sm font-medium text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? 'Uploading…' : 'Import design'}
          </button>
        </div>
      </form>
    </div>
  )
}
