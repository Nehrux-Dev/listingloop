/**
 * The template gallery: a filter sidebar beside a grid you pick from.
 *
 * Templates and nothing else. This screen briefly carried a strip of the
 * agent's own designs across the top, which made one screen answer two
 * questions and put the catalogue below the fold on a short window. Your work
 * in progress lives on its own panel now — see DesignsPage.
 *
 * Clicking a card does not create anything. It opens a confirm dialog with a
 * proper look at the template, and only a yes there opens a design — see
 * UseTemplateDialog, which is also where an already-started design is resumed
 * rather than a second one made.
 *
 * WHAT THE THREE FILTER GROUPS ACTUALLY ARE
 * ---------------------------------------------------------------------------
 * They look alike and are not. **Format** is `default_dimension` — what you
 * are posting to. **Occasion** is `category` — what the post is about.
 * **Style** is the visual treatment. A "Just Sold" exists as a Post and as a
 * Story, so collapsing format into occasion would lose exactly the choice an
 * agent came here to make. All three are counted and filtered server-side;
 * the counts come from `/facets/` so they describe the whole library rather
 * than the page currently loaded.
 *
 * NO PROPERTY IS ASKED FOR HERE ANY MORE
 * ---------------------------------------------------------------------------
 * This page used to carry a property selector, defaulted to the most recent
 * verified listing, and hand it to every design it created. The effect was
 * that saving one listing silently made every template an agent opened be
 * about that property — including the ones they were only looking at.
 *
 * A template is now opened as itself. The property is attached later, from
 * inside the editor, by an agent who has decided which design it belongs to.
 */

import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import {
  fetchRenderDimensions,
  fetchTemplateFacets,
  fetchTemplateImport,
  fetchTemplateImports,
  fetchTemplates,
  type Facet,
  type RenderDimension,
  type TemplateFacets,
  type TemplateImport,
  type TemplateSummary,
} from '../api/templates.ts'
import { Alert } from '../components/FormControls.tsx'
import {
  IconDesigns,
  IconFilter,
  IconGrid,
  IconLayers,
  IconSearch,
  IconUpload,
} from '../components/icons.tsx'
import ImportTemplateDialog from '../components/ImportTemplateDialog.tsx'
import TemplateThumb from '../components/TemplateThumb.tsx'
import UseTemplateDialog from '../components/UseTemplateDialog.tsx'
import { ApiError } from '../lib/apiClient.ts'
import { DESIGNS_HOME, designEditorPath } from '../lib/routes.ts'

type Sort = 'name' | 'name_desc'

const SORTS: { value: Sort; label: string }[] = [
  { value: 'name', label: 'Name (A–Z)' },
  { value: 'name_desc', label: 'Name (Z–A)' },
]

/** Debounce before a keystroke becomes a request. Long enough that typing a
 *  word is one query, short enough to feel like filtering rather than search. */
const SEARCH_IDLE_MS = 300

/** How often a running import is polled. Extraction takes tens of seconds, so
 *  anything faster is just load; anything slower and a finished import sits
 *  there looking stuck. */
const IMPORT_POLL_MS = 3000

export default function TemplateLibraryPage() {
  const navigate = useNavigate()

  const [templates, setTemplates] = useState<TemplateSummary[] | null>(null)
  const [total, setTotal] = useState(0)
  const [facets, setFacets] = useState<TemplateFacets | null>(null)
  const [renderDimensions, setRenderDimensions] = useState<RenderDimension[]>([])
  const [error, setError] = useState<string | null>(null)

  const [dimensions, setDimensions] = useState<string[]>([])
  const [styles, setStyles] = useState<string[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [rawQuery, setRawQuery] = useState('')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<Sort>('name')
  const [view, setView] = useState<'grid' | 'list'>('grid')
  // Open by default only where the panel has a column to live in. On a phone
  // it floats over the grid, so starting open would hide the templates the
  // page exists to show. Initial-width check, not a live listener: a resize
  // mid-visit should not yank a panel the user opened or closed themselves.
  const [filtersOpen, setFiltersOpen] = useState(
    () => window.matchMedia('(min-width: 768px)').matches,
  )

  /** The template awaiting a yes/no in the confirm dialog. */
  const [picked, setPicked] = useState<TemplateSummary | null>(null)

  /** Imports still worth watching: anything unfinished, plus the failures,
   *  which stay on screen until dismissed so a reason is never lost to a
   *  re-render. A succeeded one is dropped as soon as its template joins the
   *  grid — leaving it would show the same design twice. */
  const [imports, setImports] = useState<TemplateImport[]>([])
  const [importOpen, setImportOpen] = useState(false)

  useEffect(() => {
    fetchTemplateFacets().then(setFacets).catch(() => setFacets(null))
    fetchRenderDimensions().then(setRenderDimensions).catch(() => setRenderDimensions([]))
    // Pick up anything still running from a previous visit: an import survives
    // a page reload, and a user who navigated away mid-extraction should come
    // back to it in progress rather than to no trace of it.
    fetchTemplateImports()
      .then((page) => setImports(page.results.filter((job) => !job.is_finished)))
      .catch(() => setImports([]))
  }, [])

  /**
   * Poll every unfinished import until it lands.
   *
   * A succeeded job puts its template straight into the grid from
   * `template_detail` rather than re-fetching the list: the filters currently
   * applied might exclude it, and a card that vanishes the instant it appears
   * is worse than one that is simply there.
   */
  // Depends on the *ids* being watched, not on the jobs themselves: rewriting
  // a row on every tick would tear down and rebuild the interval each time.
  const pendingIds = imports
    .filter((job) => !job.is_finished)
    .map((job) => job.id)
    .join(',')

  useEffect(() => {
    if (!pendingIds) return
    const watching = pendingIds.split(',').map(Number)

    const timer = window.setInterval(() => {
      for (const id of watching) {
        void fetchTemplateImport(id)
          .then((fresh) => {
            if (fresh.status === 'succeeded' && fresh.template_detail) {
              const finished = fresh.template_detail
              setTemplates((current) =>
                current && current.some((entry) => entry.id === finished.id)
                  ? current
                  : [finished, ...(current ?? [])],
              )
              setTotal((current) => current + 1)
              setImports((current) => current.filter((entry) => entry.id !== fresh.id))
              // The new template changes every count in the sidebar.
              fetchTemplateFacets().then(setFacets).catch(() => {})
              return
            }
            setImports((current) =>
              current.map((entry) =>
                // Replaced only on a real change, so an unchanged job does not
                // produce a new array identity on every single tick.
                entry.id === fresh.id && entry.status !== fresh.status ? fresh : entry,
              ),
            )
          })
          .catch(() => {
            // A dropped poll is not a failed import. Leave the row alone and
            // try again on the next tick.
          })
      }
    }, IMPORT_POLL_MS)

    return () => window.clearInterval(timer)
  }, [pendingIds])

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(rawQuery.trim()), SEARCH_IDLE_MS)
    return () => window.clearTimeout(timer)
  }, [rawQuery])

  useEffect(() => {
    const params: Record<string, string> = {}
    if (dimensions.length > 0) params.dimension = dimensions.join(',')
    if (styles.length > 0) params.style = styles.join(',')
    if (categories.length > 0) params.category = categories.join(',')
    if (query) params.search = query

    setTemplates(null)
    setError(null)
    fetchTemplates(Object.keys(params).length > 0 ? params : undefined)
      .then((page) => {
        setTemplates(page.results)
        setTotal(page.count)
      })
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : 'Could not load templates.'),
      )
  }, [dimensions, styles, categories, query])

  /** Aspect per format, so a Story card is tall and a Facebook card is wide —
   *  the shape is half of what you are picking. */
  const aspectFor = useMemo(() => {
    const byKey = new Map(renderDimensions.map((entry) => [entry.key, entry.aspect]))
    return (template: TemplateSummary) => byKey.get(template.default_dimension) ?? 1
  }, [renderDimensions])

  const formatLabel = useMemo(() => {
    const byKey = new Map((facets?.dimensions ?? []).map((f) => [f.value, f.label]))
    return (template: TemplateSummary) =>
      byKey.get(template.default_dimension) ?? template.default_dimension
  }, [facets])

  const shown = useMemo(() => {
    if (!templates) return []
    const sorted = [...templates].sort((a, b) => a.name.localeCompare(b.name))
    return sort === 'name_desc' ? sorted.reverse() : sorted
  }, [templates, sort])

  const activeFilters = dimensions.length + styles.length + categories.length
  const withCounts = (list: Facet[] | undefined) =>
    (list ?? []).filter((facet) => facet.count > 0)

  function toggle(setter: (fn: (current: string[]) => string[]) => void, value: string) {
    setter((current) =>
      current.includes(value)
        ? current.filter((entry) => entry !== value)
        : [...current, value],
    )
  }

  function clearFilters() {
    setDimensions([])
    setStyles([])
    setCategories([])
    setRawQuery('')
  }

  return (
    // h-full, not h-screen: the shell owns the viewport now, and on phones a
    // sticky top bar sits above this page inside the same column.
    <div className="flex h-full flex-col bg-app">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-4 sm:px-6">
        <div className="mr-auto min-w-0">
          <h1 className="text-xl font-semibold tracking-tight">Templates</h1>
          <p className="mt-0.5 text-sm text-muted">
            Choose a template to start creating stunning designs
          </p>
        </div>

        <div className="relative w-full max-w-xs">
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <input
            value={rawQuery}
            onChange={(event) => setRawQuery(event.target.value)}
            placeholder="Search templates..."
            aria-label="Search templates"
            className="w-full rounded-control border border-line bg-surface py-2.5 pl-9 pr-3 text-sm outline-none transition placeholder:text-muted focus:border-brand"
          />
        </div>

        {/* The way across to the other half. The rail already has it, but an
            agent who arrived here to start something and then remembered the
            one they had going should not have to hunt for it. */}
        <Link
          to={DESIGNS_HOME}
          className="flex items-center gap-2 rounded-control border border-line px-3.5 py-2.5 text-sm font-medium transition hover:bg-hover"
        >
          <IconDesigns className="size-4 text-muted" />
          My designs
        </Link>

        <button
          type="button"
          onClick={() => setImportOpen(true)}
          className="flex items-center gap-2 rounded-control bg-brand px-3.5 py-2.5 text-sm font-medium text-white transition hover:opacity-90"
        >
          <IconUpload className="size-4" />
          Import design
        </button>

        <button
          type="button"
          onClick={() => setFiltersOpen((open) => !open)}
          aria-expanded={filtersOpen}
          className={`flex items-center gap-2 rounded-control border px-3.5 py-2.5 text-sm font-medium transition ${
            filtersOpen || activeFilters > 0
              ? 'border-brand text-brand'
              : 'border-line text-ink hover:bg-hover'
          }`}
        >
          <IconFilter className="size-4" />
          Filters
          {activeFilters > 0 && (
            <span className="rounded-full bg-brand px-1.5 text-[10px] font-bold text-white">
              {activeFilters}
            </span>
          )}
        </button>
      </header>

      <div className="relative flex min-h-0 flex-1">
        {filtersOpen && (
          // On phones the panel floats over the grid instead of pushing it:
          // a 264px column beside a 390px viewport leaves no grid to filter.
          <aside className="w-[264px] shrink-0 overflow-y-auto border-r border-line bg-surface p-4 max-md:absolute max-md:inset-y-0 max-md:left-0 max-md:z-20 max-md:shadow-pop">
            <FilterGroup title="Format">
              <FilterRow
                label="All templates"
                count={(facets?.dimensions ?? []).reduce((sum, f) => sum + f.count, 0)}
                active={dimensions.length === 0}
                onClick={() => setDimensions([])}
              />
              {withCounts(facets?.dimensions).map((facet) => (
                <FilterRow
                  key={facet.value}
                  label={facet.label}
                  count={facet.count}
                  active={dimensions.includes(facet.value)}
                  onClick={() => toggle(setDimensions, facet.value)}
                />
              ))}
            </FilterGroup>

            <FilterGroup title="Style">
              {withCounts(facets?.styles).map((facet) => (
                <CheckRow
                  key={facet.value}
                  label={facet.label}
                  count={facet.count}
                  checked={styles.includes(facet.value)}
                  onChange={() => toggle(setStyles, facet.value)}
                />
              ))}
            </FilterGroup>

            <FilterGroup title="Occasion">
              {withCounts(facets?.categories).map((facet) => (
                <CheckRow
                  key={facet.value}
                  label={facet.label}
                  count={facet.count}
                  checked={categories.includes(facet.value)}
                  onChange={() => toggle(setCategories, facet.value)}
                />
              ))}
            </FilterGroup>

            <button
              type="button"
              onClick={clearFilters}
              disabled={activeFilters === 0 && !rawQuery}
              className="mt-2 w-full rounded-control border border-line px-3 py-2 text-[13px] font-medium text-brand transition hover:bg-hover disabled:cursor-not-allowed disabled:text-muted disabled:hover:bg-transparent"
            >
              Clear filters
            </button>
          </aside>
        )}

        <main className="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          {error && (
            <div className="mb-4">
              <Alert kind="error">{error}</Alert>
            </div>
          )}

          <div className="mb-4 flex flex-wrap items-center gap-3">
            <p className="mr-auto text-sm font-medium">
              {templates ? `${total} template${total === 1 ? '' : 's'}` : 'Loading…'}
            </p>

            <label className="flex items-center gap-2 text-sm text-muted">
              Sort by:
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value as Sort)}
                className="rounded-control border border-line bg-surface px-2.5 py-1.5 text-sm text-ink"
              >
                {SORTS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <div className="flex items-center gap-0.5 rounded-control border border-line p-0.5">
              <ViewButton active={view === 'grid'} onClick={() => setView('grid')} label="Grid view">
                <IconGrid className="size-4" />
              </ViewButton>
              <ViewButton active={view === 'list'} onClick={() => setView('list')} label="List view">
                <IconLayers className="size-4" />
              </ViewButton>
            </div>
          </div>

          {imports.length > 0 && (
            <ul className="mb-4 space-y-2">
              {imports.map((job) => (
                <li key={job.id}>
                  <ImportRow
                    job={job}
                    onDismiss={() =>
                      setImports((current) => current.filter((entry) => entry.id !== job.id))
                    }
                  />
                </li>
              ))}
            </ul>
          )}

          {templates && shown.length === 0 && (
            <div className="rounded-lg border border-dashed border-line p-10 text-center text-sm text-muted">
              No templates match those filters.
            </div>
          )}

          {shown.length > 0 && (
            <ul
              className={
                view === 'grid'
                  ? 'grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4'
                  : 'space-y-2'
              }
            >
              {shown.map((template) => {
                const card = {
                  template,
                  aspect: aspectFor(template),
                  format: formatLabel(template),
                  onOpen: () => setPicked(template),
                }
                return (
                  <li key={template.id}>
                    {view === 'grid' ? <GridCard {...card} /> : <ListRow {...card} />}
                  </li>
                )
              })}
            </ul>
          )}
        </main>
      </div>

      {importOpen && (
        <ImportTemplateDialog
          onClose={() => setImportOpen(false)}
          onQueued={(job) => {
            setImports((current) => [job, ...current])
            setImportOpen(false)
          }}
        />
      )}

      {picked && (
        <UseTemplateDialog
          template={picked}
          format={formatLabel(picked)}
          aspect={aspectFor(picked)}
          onClose={() => setPicked(null)}
          onOpen={(designId) => void navigate(designEditorPath(designId))}
        />
      )}
    </div>
  )
}

// -- imports in progress -----------------------------------------------------

/**
 * One import, while it runs and after it fails.
 *
 * A failure is dismissible rather than auto-clearing: the message names what
 * was wrong with that particular file, and it is the only place that
 * information exists once the job is off screen.
 */
function ImportRow({ job, onDismiss }: { job: TemplateImport; onDismiss: () => void }) {
  const failed = job.status === 'failed'
  return (
    <div
      className={`flex items-center gap-3 rounded-control border px-3 py-2.5 text-sm ${
        failed ? 'border-rose-200 bg-rose-50' : 'border-line bg-surface'
      }`}
    >
      {!failed && (
        <span
          aria-hidden="true"
          className="size-4 shrink-0 animate-spin rounded-full border-2 border-brand border-t-transparent"
        />
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium text-ink">
          {job.original_filename || 'Imported design'}
        </span>
        <span className={`block text-xs ${failed ? 'text-rose-700' : 'text-muted'}`}>
          {failed
            ? job.error
            : job.status === 'queued'
              ? 'Queued — waiting for a worker.'
              : 'Reading the design and measuring its elements…'}
        </span>
      </span>
      {failed && (
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 rounded-control border border-rose-200 px-2.5 py-1 text-xs font-medium text-rose-700 transition hover:bg-rose-100"
        >
          Dismiss
        </button>
      )}
    </div>
  )
}

// -- cards -------------------------------------------------------------------

type CardProps = {
  template: TemplateSummary
  aspect: number
  format: string
  onOpen: () => void
}

/** No card is ever disabled now. A property template opens as a property
 *  template with its fields empty, and the agent attaches a listing from the
 *  editor — so there is nothing left for the gallery to refuse. */
function cardTitle(template: TemplateSummary): string {
  return `Customize ${template.name}`
}

function GridCard({ template, aspect, format, onOpen }: CardProps) {
  return (
    <button
      type="button"
      title={cardTitle(template)}
      onClick={onOpen}
      className="group w-full overflow-hidden rounded-panel border border-line bg-surface text-left shadow-panel transition hover:-translate-y-0.5 hover:border-brand/50 hover:shadow-pop"
    >
      <TemplateThumb
        template={template}
        className="w-full p-3"
        style={{ aspectRatio: String(aspect) }}
      >
        {/* The affordance the dialog needs to be worth opening: the card says
            what the click leads to before it is clicked. */}
        <span className="absolute inset-0 flex items-center justify-center bg-black/45 opacity-0 transition group-hover:opacity-100">
          <span className="rounded-control bg-white px-3 py-1.5 text-xs font-semibold text-slate-900">
            Customize
          </span>
        </span>
      </TemplateThumb>
      <div className="p-3">
        <p className="truncate text-sm font-medium text-ink">{template.name}</p>
        <p className="mt-0.5 text-xs text-muted">
          {format} · {template.category_display}
        </p>
      </div>
    </button>
  )
}

function ListRow({ template, format, onOpen }: CardProps) {
  return (
    <button
      type="button"
      title={cardTitle(template)}
      onClick={onOpen}
      className="flex w-full items-center gap-3 overflow-hidden rounded-control border border-line bg-surface p-2 text-left transition hover:border-brand/50"
    >
      <TemplateThumb
        template={template}
        className="size-12 shrink-0 rounded-control p-1"
        showStyleLabel={false}
      />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-ink">{template.name}</span>
        <span className="block truncate text-xs text-muted">
          {format} · {template.category_display} · {template.style_display}
        </span>
      </span>
    </button>
  )
}

// -- sidebar chrome ----------------------------------------------------------

function FilterGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5">
      <h2 className="mb-2 text-[13px] font-semibold text-ink">{title}</h2>
      <div className="space-y-0.5">{children}</div>
    </section>
  )
}

/** A single-tap row — the format list, where "All templates" is a real
 *  choice rather than the absence of one. */
function FilterRow({
  label,
  count,
  active,
  onClick,
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex w-full items-center gap-2 rounded-control px-2.5 py-2 text-[13px] font-medium transition ${
        active ? 'bg-active text-brand' : 'text-muted hover:bg-hover hover:text-ink'
      }`}
    >
      <span className="min-w-0 flex-1 truncate text-left">{label}</span>
      <span className="shrink-0 text-xs opacity-70">{count}</span>
    </button>
  )
}

function CheckRow({
  label,
  count,
  checked,
  onChange,
}: {
  label: string
  count: number
  checked: boolean
  onChange: () => void
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2.5 rounded-control px-2.5 py-1.5 text-[13px] transition hover:bg-hover">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="size-4 shrink-0 accent-brand"
      />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <span className="shrink-0 text-xs text-muted">{count}</span>
    </label>
  )
}

function ViewButton({
  active,
  onClick,
  label,
  children,
}: {
  active: boolean
  onClick: () => void
  label: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={`flex size-8 items-center justify-center rounded transition ${
        active ? 'bg-active text-brand' : 'text-muted hover:bg-hover hover:text-ink'
      }`}
    >
      {children}
    </button>
  )
}
