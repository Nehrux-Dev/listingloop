import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  fetchProfileCompleteness,
  type ProfileCompleteness,
} from '../api/profileSetup.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { apiRequest } from '../lib/apiClient.ts'

type HealthResponse = {
  status: 'ok' | 'error'
  checks: Record<string, { status: 'ok' | 'error'; detail?: string }>
}

/**
 * Remembers a dismissal against *what was missing at the time*, not just
 * "dismissed".
 *
 * Dismissing forever would hide a genuinely new gap — an agent who dismisses
 * this at 90%, then joins a brokerage with a disclaimer they have not filled
 * in, should hear about it. Keying on the missing set means the prompt comes
 * back when the answer changes and stays gone when it does not.
 */
const DISMISSED_KEY = 'profile-prompt-dismissed'

function signatureOf(completeness: ProfileCompleteness): string {
  return completeness.missing_required
    .map((field) => field.key)
    .sort()
    .join(',')
}

function readDismissed(userId: number | undefined): string | null {
  if (userId === undefined) return null
  try {
    return window.localStorage.getItem(`${DISMISSED_KEY}:${userId}`)
  } catch {
    // Private browsing, or storage disabled. Showing the prompt is the safe
    // failure: it is advice, and it can be dismissed again.
    return null
  }
}

export default function DashboardPage() {
  const { user } = useAuth()
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [completeness, setCompleteness] = useState<ProfileCompleteness | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(() => readDismissed(user?.id))

  useEffect(() => {
    apiRequest<HealthResponse>('/api/health/')
      .then(setHealth)
      .catch(() => setHealth(null))
    fetchProfileCompleteness()
      .then(setCompleteness)
      .catch(() => setCompleteness(null))
  }, [])

  const signature = useMemo(
    () => (completeness ? signatureOf(completeness) : null),
    [completeness],
  )

  function dismiss() {
    if (signature === null || user === null) return
    setDismissed(signature)
    try {
      window.localStorage.setItem(`${DISMISSED_KEY}:${user.id}`, signature)
    } catch {
      // Dismissal just will not survive a reload. Not worth an error message.
    }
  }

  const showPrompt =
    completeness !== null && !completeness.is_complete && dismissed !== signature

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          Signed in as {user?.full_name || user?.email} &middot; {user?.role_display}
        </p>
      </div>

      {/* An offer, not a gate: dismissible, and nothing on the dashboard stops
          working while it is ignored. What it must not do is be the first time
          an agent hears about a gap at the moment they try to publish, which is
          why each missing field links straight to the screen that fixes it. */}
      {showPrompt && completeness && (
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm font-medium text-slate-700">
                Complete your profile
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                {completeness.ready_for_marketing
                  ? 'You have everything you need to export. These would round it out.'
                  : 'Optional for now — needed before you can export marketing material.'}
              </p>
            </div>
            <button
              type="button"
              onClick={dismiss}
              className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
            >
              Dismiss
            </button>
          </div>

          <div className="mt-3 flex items-center gap-3">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-full transition-all ${
                  completeness.ready_for_marketing ? 'bg-emerald-600' : 'bg-slate-400'
                }`}
                style={{ width: `${completeness.completion_percent}%` }}
              />
            </div>
            <span className="text-sm font-semibold text-slate-900">
              {completeness.completion_percent}%
            </span>
          </div>

          {completeness.missing_required.length > 0 && (
            <ul className="mt-4 flex flex-wrap gap-2">
              {completeness.missing_required.map((field) => (
                <li key={field.key}>
                  <Link
                    to={field.fix_path}
                    title={field.hint || undefined}
                    className="inline-block rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 transition hover:border-slate-500 hover:bg-slate-50"
                  >
                    {field.label} →
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-medium text-slate-700">Backend health</h2>
        <ul className="mt-3 divide-y divide-slate-100 text-sm">
          {health ? (
            Object.entries(health.checks).map(([name, check]) => (
              <li key={name} className="flex items-center gap-2 py-2">
                <span
                  className={`inline-block size-2.5 rounded-full ${
                    check.status === 'ok' ? 'bg-emerald-500' : 'bg-rose-500'
                  }`}
                  aria-hidden="true"
                />
                <span className="font-medium capitalize">{name}</span>
                <span className="ml-auto text-slate-500">
                  {check.status === 'ok' ? 'ok' : (check.detail ?? 'error')}
                </span>
              </li>
            ))
          ) : (
            <li className="py-2 text-slate-500">Checking&hellip;</li>
          )}
        </ul>
      </section>
    </div>
  )
}
