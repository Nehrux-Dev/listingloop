import { useEffect, useState } from 'react'

import { apiRequest } from '../lib/apiClient.ts'

type PlatformOverview = {
  scope: string
  total_users: number
  users_by_role: Record<string, number>
}

/**
 * Nehrux Admin only. The route guard keeps Agents from navigating here, and
 * the endpoint below returns 403 to anyone else regardless — the guard is
 * convenience, the 403 is the actual control.
 */
export default function PlatformAdminPage() {
  const [data, setData] = useState<PlatformOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiRequest<PlatformOverview>('/api/admin/platform-overview/')
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed'))
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Platform administration</h1>
        <p className="mt-1 text-sm text-slate-500">Restricted to Nehrux Admins.</p>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm text-sm">
        {error && <p className="text-rose-600">{error}</p>}
        {!error && !data && <p className="text-slate-500">Loading&hellip;</p>}
        {data && (
          <>
            <p className="font-medium text-slate-700">
              {data.total_users} user{data.total_users === 1 ? '' : 's'}
            </p>
            <ul className="mt-3 divide-y divide-slate-100">
              {Object.entries(data.users_by_role).map(([role, count]) => (
                <li key={role} className="flex justify-between py-2">
                  <span className="capitalize">{role.replace(/_/g, ' ')}</span>
                  <span className="text-slate-500">{count}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  )
}
