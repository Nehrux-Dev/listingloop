/**
 * The buying agency's overview.
 *
 * A brokerage admin's question is never "what am I working on" — it is "what
 * is my firm doing". So this counts the team and its work rather than showing
 * a to-do list, and every number is scoped to their own brokerage by the
 * endpoints behind it.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchAgents } from '../../api/profiles.ts'
import { fetchListings } from '../../api/listings.ts'
import { fetchDesigns } from '../../api/templates.ts'
import { useAuth } from '../../auth/AuthContext.tsx'
import { IconBrokerage, IconTemplates } from '../../components/icons.tsx'

export default function AdminHomePage() {
  const { user } = useAuth()
  const [agents, setAgents] = useState<number | null>(null)
  const [listings, setListings] = useState<number | null>(null)
  const [designs, setDesigns] = useState<number | null>(null)

  useEffect(() => {
    // Each of these fails independently: one endpoint being unhappy should
    // cost its own tile, not the whole page.
    fetchAgents().then((page) => setAgents(page.count)).catch(() => setAgents(null))
    fetchListings({}).then((page) => setListings(page.count)).catch(() => setListings(null))
    fetchDesigns().then((page) => setDesigns(page.count)).catch(() => setDesigns(null))
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Agency overview</h1>
        <p className="mt-1 text-sm text-muted">
          Signed in as {user?.full_name || user?.email} · {user?.role_display}
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Agents" value={agents} />
        <Stat label="Listings" value={listings} />
        <Stat label="Designs" value={designs} />
      </div>

      <section className="rounded-panel border border-line bg-surface p-5 shadow-panel">
        <h2 className="text-base font-semibold tracking-tight">Set up your agency</h2>
        <p className="mt-1 text-sm text-muted">
          The logo, colours and required disclaimer here are applied across every
          template your agents use — so their work comes out looking like the
          agency made it, whoever made it.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link
            to="/admin/brokerage"
            className="flex items-center gap-2 rounded-control bg-brand px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90"
          >
            <IconBrokerage className="size-4" />
            Agency settings
          </Link>
          <Link
            to="/admin/brand-kit"
            className="flex items-center gap-2 rounded-control border border-line px-4 py-2.5 text-sm font-medium transition hover:bg-hover"
          >
            <IconTemplates className="size-4 text-muted" />
            Brand kit
          </Link>
        </div>
      </section>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-panel border border-line bg-surface p-4 shadow-panel">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">
        {value === null ? '—' : value}
      </p>
    </div>
  )
}
