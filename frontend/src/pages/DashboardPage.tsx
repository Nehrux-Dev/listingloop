import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchProfileCompletion, type ProfileCompletion } from '../api/onboarding.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { apiRequest } from '../lib/apiClient.ts'

type HealthResponse = {
  status: 'ok' | 'error'
  checks: Record<string, { status: 'ok' | 'error'; detail?: string }>
}

export default function DashboardPage() {
  const { user } = useAuth()
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [completion, setCompletion] = useState<ProfileCompletion | null>(null)

  useEffect(() => {
    apiRequest<HealthResponse>('/api/health/')
      .then(setHealth)
      .catch(() => setHealth(null))
    fetchProfileCompletion()
      .then(setCompletion)
      .catch(() => setCompletion(null))
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          Signed in as {user?.full_name || user?.email} &middot; {user?.role_display}
        </p>
      </div>

      {/* Completion is informational; readiness is the thing that blocks an
          export, so the two are shown as different statements. */}
      {completion && !completion.is_complete && (
        <section
          className={`rounded-lg border p-5 shadow-sm ${
            completion.ready_for_marketing
              ? 'border-slate-200 bg-white'
              : 'border-amber-200 bg-amber-50'
          }`}
        >
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-700">
              {completion.ready_for_marketing
                ? 'Complete your marketing profile'
                : 'Your profile needs a little more before you can export'}
            </h2>
            <span className="text-sm font-semibold text-slate-900">
              {completion.completion_percent}%
            </span>
          </div>

          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
            <div
              className={`h-full transition-all ${
                completion.ready_for_marketing ? 'bg-emerald-600' : 'bg-amber-500'
              }`}
              style={{ width: `${completion.completion_percent}%` }}
            />
          </div>

          {completion.missing_required.length > 0 && (
            <p className="mt-3 text-sm text-amber-800">
              Still needed:{' '}
              {completion.missing_required.map((field) => field.label).join(', ')}.
            </p>
          )}

          <Link
            to="/onboarding"
            className="mt-3 inline-block rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-slate-800"
          >
            Finish setting up
          </Link>
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
