import { useCallback, useEffect, useState } from 'react'

import { fetchHealth, type HealthResponse } from './api/health.ts'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'loaded'; data: HealthResponse }
  | { kind: 'failed'; message: string }

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block size-2.5 rounded-full ${ok ? 'bg-emerald-500' : 'bg-rose-500'}`}
      aria-hidden="true"
    />
  )
}

export default function App() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    try {
      const data = await fetchHealth()
      setState({ kind: 'loaded', data })
    } catch (error) {
      setState({
        kind: 'failed',
        message: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <main className="min-h-screen bg-slate-50 px-6 py-16 text-slate-900">
      <div className="mx-auto max-w-xl">
        <h1 className="text-2xl font-semibold tracking-tight">Real Estate</h1>
        <p className="mt-1 text-sm text-slate-500">
          Skeleton app &mdash; React + TypeScript + Vite + Tailwind, talking to Django.
        </p>

        <section className="mt-8 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-700">Backend health</h2>
            <button
              type="button"
              onClick={() => void load()}
              className="rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
            >
              Refresh
            </button>
          </div>

          <div className="mt-4 text-sm">
            {state.kind === 'loading' && <p className="text-slate-500">Checking&hellip;</p>}

            {state.kind === 'failed' && (
              <p className="text-rose-600">
                Could not reach the API: {state.message}
              </p>
            )}

            {state.kind === 'loaded' && (
              <ul className="divide-y divide-slate-100">
                {Object.entries(state.data.checks).map(([name, check]) => (
                  <li key={name} className="flex items-center gap-2 py-2">
                    <StatusDot ok={check.status === 'ok'} />
                    <span className="font-medium capitalize">{name}</span>
                    <span className="ml-auto text-slate-500">
                      {check.status === 'ok' ? 'ok' : (check.detail ?? 'error')}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </main>
  )
}
