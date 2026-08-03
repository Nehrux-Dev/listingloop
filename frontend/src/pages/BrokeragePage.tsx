import { useEffect, useState } from 'react'

import { apiRequest } from '../lib/apiClient.ts'

type BrokerageOverview = {
  scope: string
  requested_by: string
  role: string
}

/** Brokerage Admins and above — Nehrux Admins inherit access. */
export default function BrokeragePage() {
  const [data, setData] = useState<BrokerageOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiRequest<BrokerageOverview>('/api/admin/brokerage-overview/')
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed'))
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Brokerage administration</h1>
        <p className="mt-1 text-sm text-slate-500">
          Requires Brokerage Admin access or higher.
        </p>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm text-sm">
        {error && <p className="text-rose-600">{error}</p>}
        {!error && !data && <p className="text-slate-500">Loading&hellip;</p>}
        {data && (
          <dl className="space-y-2">
            <div className="flex justify-between">
              <dt className="text-slate-500">Scope</dt>
              <dd className="font-medium">{data.scope}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Requested by</dt>
              <dd className="font-medium">{data.requested_by}</dd>
            </div>
          </dl>
        )}
      </section>
    </div>
  )
}
