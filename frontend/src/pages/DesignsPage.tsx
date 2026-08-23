/**
 * The agent's designs: a project list, and nothing more.
 *
 * Everything you can *do* to a design happens in the editor — rename,
 * duplicate, delete, variations, export. This panel's whole job is to get you
 * back into one you already started, so it carries a thumbnail, a name, what
 * it was made from, when you last touched it, and a way in.
 *
 * ONLY YOUR OWN WORK
 * ---------------------------------------------------------------------------
 * The designs endpoint's default scope is the *permission* boundary, and for a
 * brokerage admin that is the whole firm — which is right for an audit and
 * wrong for a screen called "my designs". So the request is made with `mine=1`
 * and the server narrows it to the caller's own AgentProfile.
 *
 * NO TEMPLATES HERE
 * ---------------------------------------------------------------------------
 * The gallery is its own panel. The only template-shaped thing on this screen
 * is the way out to it, because "I have nothing started" and "I want something
 * new" both end at the same place.
 */

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchDesigns, type Design } from '../api/templates.ts'
import { Alert } from '../components/FormControls.tsx'
import { IconSearch, IconTemplates } from '../components/icons.tsx'
import { ApiError } from '../lib/apiClient.ts'
import { TEMPLATES_HOME, designEditorPath } from '../lib/routes.ts'
import { lastEdited } from '../lib/time.ts'

export default function DesignsPage() {
  const [designs, setDesigns] = useState<Design[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  useEffect(() => {
    fetchDesigns({ mine: '1' })
      .then((page) => setDesigns(page.results))
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : 'Could not load your designs.'),
      )
  }, [])

  /**
   * Filtered and ordered here rather than server-side.
   *
   * The list is already in hand and is one agent's own work, so it is small
   * enough that a round trip per keystroke would be slower than the filter it
   * replaces. The sort is defensive: the API orders by `-updated_at` already,
   * and re-stating it costs nothing and survives that changing.
   */
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (designs ?? [])
      .filter((design) => {
        if (!needle) return true
        return [design.name, design.template_detail?.name, design.listing_address]
          .filter(Boolean)
          .some((field) => String(field).toLowerCase().includes(needle))
      })
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  }, [designs, query])

  return (
    // h-full, not h-screen: the shell owns the viewport now, and on phones a
    // sticky top bar sits above this page inside the same column.
    <div className="flex h-full flex-col bg-app">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-4 sm:px-6">
        <div className="mr-auto min-w-0">
          <h1 className="text-xl font-semibold tracking-tight">Designs</h1>
          <p className="mt-0.5 text-sm text-muted">Pick up where you left off</p>
        </div>

        <div className="relative w-full max-w-xs">
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search your designs..."
            aria-label="Search your designs"
            className="w-full rounded-control border border-line bg-surface py-2.5 pl-9 pr-3 text-sm outline-none transition placeholder:text-muted focus:border-brand"
          />
        </div>

        <Link
          to={TEMPLATES_HOME}
          className="flex items-center gap-2 rounded-control bg-brand px-3.5 py-2.5 text-sm font-medium text-white transition hover:opacity-90"
        >
          <IconTemplates className="size-4" />
          New from template
        </Link>
      </header>

      <main className="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        {error && (
          <div className="mb-4">
            <Alert kind="error">{error}</Alert>
          </div>
        )}

        {!designs && !error && <p className="text-sm text-muted">Loading…</p>}

        {designs && (
          <p className="mb-4 text-sm font-medium">
            {shown.length} design{shown.length === 1 ? '' : 's'}
            {query && designs.length !== shown.length && (
              <span className="font-normal text-muted"> of {designs.length}</span>
            )}
          </p>
        )}

        {/* Two different empty states, because they need two different
            answers: nothing started yet is a prompt to go and start, whereas
            nothing matching is a prompt to clear the search. */}
        {designs && designs.length === 0 && (
          <div className="rounded-panel border border-dashed border-line p-10 text-center">
            <p className="text-sm text-muted">
              No designs yet. Pick a template to get started.
            </p>
            <Link
              to={TEMPLATES_HOME}
              className="mt-3 inline-block text-sm font-medium text-brand underline underline-offset-2"
            >
              Browse templates
            </Link>
          </div>
        )}

        {designs && designs.length > 0 && shown.length === 0 && (
          <div className="rounded-panel border border-dashed border-line p-10 text-center text-sm text-muted">
            No designs match “{query}”.
          </div>
        )}

        {shown.length > 0 && (
          <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {shown.map((design) => (
              <li key={design.id}>
                <DesignCard design={design} />
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  )
}

function DesignCard({ design }: { design: Design }) {
  // The last export is the only true picture of a design the list can get
  // cheaply — rendering each card properly would be a browser process per
  // tile. An unexported design says so rather than showing a wrong preview.
  const preview = design.exports[0]?.image_url

  return (
    <Link
      to={designEditorPath(design.id)}
      title={`Open ${design.name}`}
      className="group block overflow-hidden rounded-panel border border-line bg-surface shadow-panel transition hover:-translate-y-0.5 hover:border-brand/50 hover:shadow-pop"
    >
      <div className="flex h-36 items-center justify-center overflow-hidden bg-subtle">
        {preview ? (
          <img
            src={preview}
            alt=""
            aria-hidden="true"
            loading="lazy"
            className="size-full object-cover"
          />
        ) : (
          <span className="text-xs text-muted">Not exported yet</span>
        )}
      </div>

      <div className="p-3.5">
        <p className="truncate text-sm font-medium text-ink">{design.name}</p>

        {/* What it came from, and what it is about. The address is the fact an
            agent actually recognises a design by when four of them started
            from the same template. */}
        <p className="mt-1 truncate text-xs text-muted">
          {design.listing_address ?? design.template_detail?.name ?? 'No property yet'}
        </p>

        <div className="mt-2.5 flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-[11px] text-muted">
            Edited {lastEdited(design.updated_at)}
          </span>
          <span className="shrink-0 rounded-control border border-line px-2.5 py-1 text-xs font-medium transition group-hover:border-brand group-hover:bg-brand group-hover:text-white">
            Open
          </span>
        </div>
      </div>
    </Link>
  )
}
