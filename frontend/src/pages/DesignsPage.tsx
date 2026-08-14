/**
 * The agent's designs: a project list, and nothing more.
 *
 * Everything you can *do* to a design happens in the editor now — rename,
 * duplicate, delete, variations, export. This page's whole job is to get you
 * back into one you already started, so it carries a thumbnail, a name, when
 * you last touched it, and a way in.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchDesigns, type Design } from '../api/templates.ts'
import { Alert } from '../components/FormControls.tsx'
import { ApiError } from '../lib/apiClient.ts'
import { designEditorPath } from '../lib/routes.ts'

/** "3 days ago" — the only fact about a design this page needs to date it. */
function lastEdited(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60_000))
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  return new Date(then).toLocaleDateString()
}

export default function DesignsPage() {
  const [designs, setDesigns] = useState<Design[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchDesigns()
      .then((page) => setDesigns(page.results))
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : 'Could not load your designs.'),
      )
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h1 className="text-xl font-semibold tracking-tight">Designs</h1>
          <p className="mt-1 text-sm text-slate-500">Pick up where you left off.</p>
        </div>
        <Link
          to="/templates"
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
        >
          New from template
        </Link>
      </div>

      {error && <Alert kind="error">{error}</Alert>}
      {!designs && !error && <p className="text-sm text-slate-500">Loading…</p>}

      {designs && designs.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center">
          <p className="text-sm text-slate-500">
            No designs yet. Pick a template to get started.
          </p>
          <Link
            to="/templates"
            className="mt-3 inline-block text-sm font-medium text-slate-700 underline underline-offset-2"
          >
            Browse templates
          </Link>
        </div>
      )}

      {designs && designs.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {designs.map((design) => (
            <li key={design.id}>
              <Link
                to={designEditorPath(design.id)}
                className="group block overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm transition hover:border-slate-400 hover:shadow-md"
              >
                <div className="flex h-32 items-center justify-center overflow-hidden bg-slate-100">
                  {design.exports[0]?.image_url ? (
                    <img
                      src={design.exports[0].image_url}
                      alt=""
                      className="size-full object-cover"
                    />
                  ) : (
                    <span className="text-xs text-slate-400">Not exported yet</span>
                  )}
                </div>
                <div className="flex items-center gap-2 p-4">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-slate-800">{design.name}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      Edited {lastEdited(design.updated_at)}
                    </p>
                  </div>
                  <span className="shrink-0 rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 transition group-hover:border-slate-900 group-hover:bg-slate-900 group-hover:text-white">
                    Open
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
