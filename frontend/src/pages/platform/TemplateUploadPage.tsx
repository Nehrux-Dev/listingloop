/**
 * Upload a PDF, watch it extract, publish it to every agent.
 *
 * WHY PUBLISHING IS A SECOND CLICK
 * ---------------------------------------------------------------------------
 * Extraction is good, not perfect. A headline set in calligraphy can come back
 * in the wrong face, a binding gets missed. Publishing straight out of the
 * extractor would put that in front of every agent in every agency at once,
 * with no moment in between to look at it.
 *
 * So an import lands as a private draft — owned by the uploader, which is what
 * makes it invisible to everyone else — and the Upload button is what clears
 * that owner. Nothing about the draft is special-cased: it is an ordinary
 * template that happens to have an owner, openable in the normal editor and
 * fixable there before anybody else sees it.
 */

import { useEffect, useRef, useState } from 'react'

import {
  deleteTemplate,
  fetchTemplateImport,
  fetchTemplates,
  importTemplate,
  publishTemplateToLibrary,
  type TemplateCategory,
  type TemplateImport,
  type TemplateStyle,
  type TemplateSummary,
} from '../../api/templates.ts'
import { Alert } from '../../components/FormControls.tsx'
import TemplateThumb from '../../components/TemplateThumb.tsx'
import { IconCheckCircle, IconTrash, IconUpload } from '../../components/icons.tsx'
import { ApiError } from '../../lib/apiClient.ts'

/** Mirrors IMPORT_EXTENSIONS / MAX_TEMPLATE_IMPORT_MB in the serializer. The
 *  server re-checks both and sniffs the bytes, which a browser cannot — this
 *  keeps the picker useful, it does not enforce anything.
 *
 *  PDF only for now, although the backend can also read PNG/JPG/WEBP: image
 *  extraction goes through the vision model, which needs OPENAI_API_KEY
 *  configured — and on a server without it, offering images here just walks
 *  the admin into "content generation is not configured". Restore
 *  '.pdf,.png,.jpg,.jpeg,.webp' (and the hint text below) when the key is
 *  set. A text PDF needs no key at all — it is read structurally. */
const ACCEPT = '.pdf'
const MAX_MB = 25

/** A PDF carrying real text is read structurally and finishes in about a
 *  second; a scan goes to the vision model and takes far longer, so the poll
 *  has to be patient either way. */
const POLL_MS = 2000

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

export default function TemplateUploadPage() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [category, setCategory] = useState<TemplateCategory>('new_listing')
  const [style, setStyle] = useState<TemplateStyle>('luxury')
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /** The job being extracted or just finished. One at a time on purpose: this
   *  screen is "publish this template", not a bulk queue. */
  const [job, setJob] = useState<TemplateImport | null>(null)
  const [published, setPublished] = useState<Set<number>>(new Set())
  const [publishing, setPublishing] = useState(false)

  // Poll until the worker finishes. Cleared on unmount so navigating away
  // mid-extraction leaves no timer writing into a dead component.
  useEffect(() => {
    if (!job || job.is_finished) return
    const timer = window.setTimeout(() => {
      fetchTemplateImport(job.id)
        .then(setJob)
        .catch(() => {
          /* transient; the next tick tries again */
        })
    }, POLL_MS)
    return () => window.clearTimeout(timer)
  }, [job])

  function chooseFile(next: File | null) {
    setError(null)
    if (next && next.size > MAX_MB * 1024 * 1024) {
      setError(
        `That file is ${(next.size / 1024 / 1024).toFixed(1)}MB. The limit is ${MAX_MB}MB.`,
      )
      return
    }
    setFile(next)
  }

  async function startImport() {
    if (!file || busy) return
    setBusy(true)
    setError(null)
    try {
      setJob(
        await importTemplate({ file, name: name.trim() || undefined, category, style }),
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That upload could not be started.')
    } finally {
      setBusy(false)
    }
  }

  async function publish(templateId: number) {
    setPublishing(true)
    setError(null)
    try {
      await publishTemplateToLibrary(templateId)
      setPublished((current) => new Set(current).add(templateId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That template could not be published.')
    } finally {
      setPublishing(false)
    }
  }

  const extracted = job && job.status === 'succeeded' ? job.template_detail : null
  const elementCount = job?.element_count ?? 0
  const isPublished = extracted ? published.has(extracted.id) : false

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Upload a template</h1>
        <p className="mt-1 text-sm text-muted">
          A PDF is read into editable elements — text, photos, panels and
          colours, each one editable on the canvas.
        </p>
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      <section className="rounded-panel border border-line bg-surface p-5 shadow-panel">
        <div
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
          className={`flex flex-col items-center justify-center rounded-control border-2 border-dashed px-6 py-10 text-center transition ${
            dragging ? 'border-brand bg-brand-soft/40' : 'border-line'
          }`}
        >
          <IconUpload className="size-6 text-muted" />
          <p className="mt-2 text-sm font-medium">
            {file ? file.name : 'Drop a PDF here, or choose a file'}
          </p>
          <p className="mt-0.5 text-xs text-muted">
            PDF · up to {MAX_MB}MB · the first page becomes the template
          </p>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="mt-3 rounded-control border border-line px-3 py-2 text-[13px] font-medium transition hover:bg-hover"
          >
            Choose file
          </button>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-muted">
              Name
            </span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="From the headline"
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand"
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-muted">
              Occasion
            </span>
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value as TemplateCategory)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm"
            >
              {CATEGORIES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-muted">
              Style
            </span>
            <select
              value={style}
              onChange={(event) => setStyle(event.target.value as TemplateStyle)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm"
            >
              {STYLES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <button
          type="button"
          onClick={() => void startImport()}
          disabled={!file || busy || (job !== null && !job.is_finished)}
          className="mt-4 rounded-control bg-brand px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
        >
          {busy ? 'Uploading…' : 'Extract template'}
        </button>
      </section>

      {job && !job.is_finished && (
        <p className="rounded-control border border-line bg-subtle px-3 py-2.5 text-sm text-muted">
          Reading <span className="font-medium text-ink">{job.original_filename}</span>…
        </p>
      )}

      {job?.status === 'failed' && (
        <Alert kind="error">{job.error || 'That file could not be extracted.'}</Alert>
      )}

      {/* A half-worked import must not look like one that worked. Anything the
          extractor could not describe is named here, while the person who
          chose the file is still looking at the screen — not discovered weeks
          later by somebody noticing the flyer is wrong. */}
      {extracted && (job?.warnings.length ?? 0) > 0 && (
        <section className="rounded-panel border border-amber-300 bg-amber-50 p-4">
          <p className="text-sm font-semibold text-amber-900">
            {job?.warnings.length} element
            {job?.warnings.length === 1 ? '' : 's'} need a look
          </p>
          <p className="mt-1 text-xs text-amber-800">
            Everything else extracted cleanly. You can publish as-is and fix
            these later, or open the template in the editor first.
          </p>
          <ul className="mt-3 space-y-1.5">
            {job?.warnings.map((warning, index) => (
              <li key={`${warning.element}-${index}`} className="text-xs text-amber-900">
                <span className="font-medium">{warning.element}</span> — {warning.issue}
              </li>
            ))}
          </ul>
        </section>
      )}

      <PublishedTemplates key={published.size} />

      {extracted && (
        <section className="rounded-panel border border-line bg-surface p-5 shadow-panel">
          <h2 className="text-base font-semibold tracking-tight">
            {isPublished ? 'Published' : 'Ready to publish'}
          </h2>
          <div className="mt-4 flex flex-wrap items-start gap-4">
            <TemplateThumb
              template={extracted}
              className="h-40 w-30 shrink-0 rounded-control"
              showStyleLabel={false}
            />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">{extracted.name}</p>
              <p className="mt-0.5 text-xs text-muted">
                {elementCount} editable element{elementCount === 1 ? '' : 's'} ·{' '}
                {extracted.category_display} · {extracted.style_display}
              </p>

              {isPublished ? (
                <p className="mt-3 flex items-center gap-1.5 text-sm font-medium text-emerald-700">
                  <IconCheckCircle className="size-4" />
                  In every agent&rsquo;s Templates panel now.
                </p>
              ) : (
                <p className="mt-3 text-sm text-muted">
                  Only you can see this. Publish it to put it in front of every
                  agent.
                </p>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => void publish(extracted.id)}
                  disabled={publishing || isPublished}
                  className="flex items-center gap-1.5 rounded-control bg-brand px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                >
                  <IconUpload className="size-4" />
                  {isPublished ? 'Uploaded' : publishing ? 'Uploading…' : 'Upload'}
                </button>
                {isPublished && (
                  <button
                    type="button"
                    onClick={() => {
                      setJob(null)
                      setFile(null)
                      setName('')
                    }}
                    className="rounded-control border border-line px-3 py-2.5 text-sm font-medium transition hover:bg-hover"
                  >
                    Upload another
                  </button>
                )}
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  )
}

// -- what is already out there -----------------------------------------------

/**
 * Everything published, with a way to take it back out.
 *
 * Removing is a Nehrux Admin's alone: the library is one shelf shared by every
 * agency, so a delete here reaches every agent in every firm at once. That is
 * exactly what makes it useful and exactly why it asks first.
 *
 * Remounted (via `key`) whenever something is published, so a template appears
 * here the moment it goes live rather than after a reload.
 */
function PublishedTemplates() {
  const [templates, setTemplates] = useState<TemplateSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [removing, setRemoving] = useState<number | null>(null)

  useEffect(() => {
    fetchTemplates({})
      .then((page) => setTemplates(page.results))
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : 'Could not load the library.'),
      )
  }, [])

  async function remove(template: TemplateSummary) {
    const confirmed = window.confirm(
      `Remove “${template.name}” from the library?\n\n` +
        'It disappears from every agent’s Templates panel, in every agency. ' +
        'Designs already made from it keep working.',
    )
    if (!confirmed) return

    setRemoving(template.id)
    setError(null)
    setNote(null)
    try {
      const result = await deleteTemplate(template.id)
      setTemplates((current) =>
        (current ?? []).filter((entry) => entry.id !== template.id),
      )
      setNote(result.detail)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That template could not be removed.')
    } finally {
      setRemoving(null)
    }
  }

  return (
    <section className="rounded-panel border border-line bg-surface p-5 shadow-panel">
      <h2 className="text-base font-semibold tracking-tight">
        In the library
        {templates && (
          <span className="ml-2 text-sm font-normal text-muted">{templates.length}</span>
        )}
      </h2>
      <p className="mt-1 text-sm text-muted">
        What every agent can start from. Removing one takes it out of their
        Templates panel everywhere.
      </p>

      {error && (
        <div className="mt-4">
          <Alert kind="error">{error}</Alert>
        </div>
      )}
      {note && (
        <p className="mt-4 rounded-control border border-line bg-subtle px-3 py-2.5 text-sm text-muted">
          {note}
        </p>
      )}

      {!templates && !error && <p className="mt-4 text-sm text-muted">Loading…</p>}

      {templates && templates.length === 0 && (
        <p className="mt-4 rounded-panel border border-dashed border-line p-6 text-center text-sm text-muted">
          Nothing published yet.
        </p>
      )}

      {templates && templates.length > 0 && (
        <ul className="mt-4 divide-y divide-line">
          {templates.map((template) => (
            <li key={template.id} className="flex items-center gap-3 py-2.5">
              <TemplateThumb
                template={template}
                className="h-12 w-9 shrink-0 rounded"
                showStyleLabel={false}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{template.name}</p>
                <p className="truncate text-xs text-muted">
                  {template.category_display} · {template.style_display} ·{' '}
                  {template.element_count} elements
                </p>
              </div>
              <button
                type="button"
                onClick={() => void remove(template)}
                disabled={removing === template.id}
                title={`Remove ${template.name} from every agent's Templates panel`}
                className="flex shrink-0 items-center gap-1.5 rounded-control border border-line px-3 py-2 text-[13px] font-medium text-rose-700 transition hover:border-rose-300 hover:bg-rose-50 disabled:opacity-50"
              >
                <IconTrash className="size-4" />
                {removing === template.id ? 'Removing…' : 'Delete'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
