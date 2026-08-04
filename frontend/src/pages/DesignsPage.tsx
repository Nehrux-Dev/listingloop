import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import {
  deleteDesign,
  duplicateDesign,
  fetchDesigns,
  renameDesign,
  type Design,
} from '../api/templates.ts'
import { Alert } from '../components/FormControls.tsx'
import { ApiError } from '../lib/apiClient.ts'

export default function DesignsPage() {
  const navigate = useNavigate()
  const [designs, setDesigns] = useState<Design[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    try {
      const page = await fetchDesigns()
      setDesigns(page.results)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load your designs.')
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function handleRename(design: Design) {
    const name = window.prompt('Design name', design.name)
    if (!name) return
    await renameDesign(design.id, name)
    await load()
  }

  async function handleDuplicate(design: Design) {
    const copy = await duplicateDesign(design.id)
    void navigate(`/designs/${copy.id}`)
  }

  async function handleDelete(design: Design) {
    if (!window.confirm(`Delete “${design.name}”? Its exports go with it.`)) return
    await deleteDesign(design.id)
    await load()
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h1 className="text-xl font-semibold tracking-tight">Designs</h1>
          <p className="mt-1 text-sm text-slate-500">
            Saved designs, ready to reopen, duplicate or export.
          </p>
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
        </div>
      )}

      {designs && designs.length > 0 && (
        <ul className="space-y-3">
          {designs.map((design) => (
            <li
              key={design.id}
              className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
            >
              <div className="flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-md bg-slate-100">
                {design.exports[0]?.image_url ? (
                  <img
                    src={design.exports[0].image_url}
                    alt=""
                    className="size-full object-cover"
                  />
                ) : (
                  <span className="text-[10px] text-slate-400">No export</span>
                )}
              </div>

              <div className="min-w-0 flex-1">
                <Link
                  to={`/designs/${design.id}`}
                  className="truncate font-medium text-slate-800 hover:underline"
                >
                  {design.name}
                </Link>
                <p className="mt-0.5 truncate text-xs text-slate-500">
                  {design.template_detail.name}
                  {design.listing_address && ` · ${design.listing_address}`}
                </p>
                <p className="mt-0.5 text-xs text-slate-400">
                  {design.exports.length} export{design.exports.length === 1 ? '' : 's'} ·
                  updated {new Date(design.updated_at).toLocaleDateString()}
                </p>
              </div>

              <div className="flex gap-1.5">
                <Action onClick={() => void handleRename(design)}>Rename</Action>
                <Action onClick={() => void handleDuplicate(design)}>Duplicate</Action>
                <Action onClick={() => void handleDelete(design)} danger>
                  Delete
                </Action>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Action({
  children,
  onClick,
  danger,
}: {
  children: React.ReactNode
  onClick: () => void
  danger?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border px-2.5 py-1 text-xs font-medium transition ${
        danger
          ? 'border-rose-200 text-rose-600 hover:bg-rose-50'
          : 'border-slate-200 text-slate-600 hover:bg-slate-50'
      }`}
    >
      {children}
    </button>
  )
}
