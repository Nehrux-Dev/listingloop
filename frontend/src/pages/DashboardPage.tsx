import { useEffect, useState } from 'react'

import { useAuth } from '../auth/AuthContext.tsx'
import { apiRequest } from '../lib/apiClient.ts'

type HealthResponse = {
  status: 'ok' | 'error'
  checks: Record<string, { status: 'ok' | 'error'; detail?: string }>
}

export default function DashboardPage() {
  const { user } = useAuth()
  const [health, setHealth] = useState<HealthResponse | null>(null)

  useEffect(() => {
    apiRequest<HealthResponse>('/api/health/')
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          Signed in as {user?.full_name || user?.email} &middot; {user?.role_display}
        </p>
      </div>

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
