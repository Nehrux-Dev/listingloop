import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fetchListings, type Listing } from '../api/listings.ts'
import {
  createDesign,
  fetchTemplateFacets,
  fetchTemplates,
  type Facet,
  type TemplateSummary,
} from '../api/templates.ts'
import { Alert } from '../components/FormControls.tsx'
import { ApiError } from '../lib/apiClient.ts'

/** A cheap visual stand-in, derived from the style so the grid is scannable. */
const STYLE_SWATCH: Record<string, string> = {
  bold: 'from-slate-900 to-slate-700',
  minimal: 'from-slate-200 to-slate-100',
  luxury: 'from-stone-800 to-amber-700',
  warm: 'from-orange-300 to-rose-300',
  editorial: 'from-slate-700 to-slate-500',
  classic: 'from-emerald-900 to-emerald-700',
}

export default function TemplateLibraryPage() {
  const navigate = useNavigate()
  const [templates, setTemplates] = useState<TemplateSummary[] | null>(null)
  const [facets, setFacets] = useState<{ categories: Facet[]; styles: Facet[] } | null>(null)
  const [category, setCategory] = useState('')
  const [style, setStyle] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Only verified listings can back a design, so only those are offered.
  const [listings, setListings] = useState<Listing[]>([])
  const [chosen, setChosen] = useState<TemplateSummary | null>(null)
  const [listingId, setListingId] = useState<string>('')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    fetchTemplateFacets().then(setFacets).catch(() => setFacets(null))
    fetchListings({ verification_status: 'verified' })
      .then((page) => setListings(page.results))
      .catch(() => setListings([]))
  }, [])

  useEffect(() => {
    const params: Record<string, string> = {}
    if (category) params.category = category
    if (style) params.style = style

    setTemplates(null)
    fetchTemplates(Object.keys(params).length > 0 ? params : undefined)
      .then((page) => setTemplates(page.results))
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : 'Could not load templates.'),
      )
  }, [category, style])

  const availableCategories = useMemo(
    () => (facets?.categories ?? []).filter((facet) => facet.count > 0),
    [facets],
  )
  const availableStyles = useMemo(
    () => (facets?.styles ?? []).filter((facet) => facet.count > 0),
    [facets],
  )

  async function startDesign() {
    if (!chosen) return
    setCreating(true)
    setError(null)
    try {
      const design = await createDesign({
        name: `${chosen.name} — ${new Date().toLocaleDateString()}`,
        template: chosen.id,
        listing: listingId ? Number(listingId) : null,
      })
      void navigate(`/designs/${design.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start that design.')
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Template library</h1>
        <p className="mt-1 text-sm text-slate-500">
          Pick a template, then fill it with one of your verified listings.
        </p>
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      <div className="space-y-3">
        <FilterRow
          label="Category"
          options={availableCategories}
          value={category}
          onChange={setCategory}
        />
        <FilterRow label="Style" options={availableStyles} value={style} onChange={setStyle} />
      </div>

      {!templates && <p className="text-sm text-slate-500">Loading…</p>}

      {templates && templates.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">
          No templates match those filters.
        </div>
      )}

      {templates && templates.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {templates.map((template) => (
            <li key={template.id}>
              <button
                type="button"
                onClick={() => setChosen(template)}
                className={`w-full overflow-hidden rounded-lg border bg-white text-left shadow-sm transition hover:border-slate-400 ${
                  chosen?.id === template.id ? 'border-slate-900 ring-1 ring-slate-900' : 'border-slate-200'
                }`}
              >
                <div
                  className={`flex h-32 items-end bg-gradient-to-br p-3 ${
                    STYLE_SWATCH[template.style] ?? 'from-slate-300 to-slate-200'
                  }`}
                >
                  <span className="rounded bg-white/90 px-2 py-0.5 text-xs font-medium text-slate-700">
                    {template.style_display}
                  </span>
                </div>
                <div className="p-4">
                  <p className="font-medium text-slate-800">{template.name}</p>
                  <p className="mt-0.5 text-xs text-slate-500">{template.category_display}</p>
                  {template.description && (
                    <p className="mt-2 line-clamp-2 text-xs text-slate-500">
                      {template.description}
                    </p>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}

      {chosen && (
        <div className="sticky bottom-4 rounded-lg border border-slate-300 bg-white p-4 shadow-lg">
          <p className="text-sm font-medium text-slate-800">{chosen.name}</p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            {/* A seasonal or agent-led template has nothing to attach, so the
                picker is not shown at all rather than shown-and-ignored. */}
            {chosen.requires_listing ? (
              <label className="text-sm">
                <span className="block text-xs font-medium text-slate-600">Listing</span>
                <select
                  value={listingId}
                  onChange={(event) => setListingId(event.target.value)}
                  className="mt-1 w-64 rounded-md border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="">Choose a verified listing…</option>
                  {listings.map((listing) => (
                    <option key={listing.id} value={listing.id}>
                      {listing.full_address || `Listing #${listing.id}`}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="text-xs text-slate-500">
                This template needs no listing.
              </p>
            )}

            <button
              type="button"
              disabled={creating}
              onClick={() => void startDesign()}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
            >
              {creating ? 'Creating…' : 'Start design'}
            </button>
            <button
              type="button"
              onClick={() => setChosen(null)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-600 transition hover:bg-slate-50"
            >
              Cancel
            </button>
          </div>
          {chosen.requires_listing && listings.length === 0 && (
            <p className="mt-2 text-xs text-amber-700">
              You have no verified listings yet. Verify one to use this template, or
              try the <a href="/calendar" className="underline">content calendar</a> —
              those templates need no property.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function FilterRow({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: Facet[]
  value: string
  onChange: (value: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 w-16 text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <button
        type="button"
        onClick={() => onChange('')}
        className={`rounded-md px-2.5 py-1 text-sm transition ${
          value === '' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
        }`}
      >
        All
      </button>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={`rounded-md px-2.5 py-1 text-sm transition ${
            value === option.value
              ? 'bg-slate-900 text-white'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          {option.label}
          <span className="ml-1 text-xs opacity-60">{option.count}</span>
        </button>
      ))}
    </div>
  )
}
