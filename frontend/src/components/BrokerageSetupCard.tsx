import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  createBrokerage,
  joinBrokerage,
  searchBrokerages,
  type BrokerageMatch,
} from '../api/profileSetup.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { ApiError } from '../lib/apiClient.ts'

/**
 * Only what this card displays. Structural rather than importing `Brokerage`:
 * the profile endpoint returns a summary, and widening the prop to the full
 * record would force callers to fetch fields nothing here reads.
 */
type BrokerageBadge = {
  name: string
  logo_url: string | null
}

/**
 * Naming the brokerage you work for. Lives in Settings, not at sign-up.
 *
 * This was the wizard's step 3. Nothing about the interaction changed — search
 * before creating, so two rows never end up describing one firm — only when it
 * is asked for. An agent reaches it when they want to, or when the export gate
 * links them here because something they are publishing needs it.
 *
 * The screen for *administering* a brokerage is /brokerage. This is the step
 * before that: an agent who belongs to nothing cannot go there, because there
 * is nothing yet to administer.
 */
export default function BrokerageSetupCard({
  brokerage,
  onChanged,
}: {
  brokerage: BrokerageBadge | null
  onChanged: () => void | Promise<void>
}) {
  // Creating a brokerage makes you its administrator, and that fact lives on
  // the auth user (`administers_brokerage`), not on the profile. Re-fetching
  // only the profile left the nav and the /brokerage route guard reading a
  // stale user, so the agent was sent to /forbidden on the very screen the
  // export gate had just told them to visit.
  const { refresh: refreshUser } = useAuth()
  const [mode, setMode] = useState<'search' | 'create'>('search')
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<BrokerageMatch[]>([])
  const [searching, setSearching] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [fields, setFields] = useState({
    name: '',
    required_disclaimer: '',
    phone: '',
    website: '',
    licence_number: '',
  })

  // Debounced: a request per keystroke would hammer the directory.
  useEffect(() => {
    if (brokerage || query.trim().length < 2) {
      setMatches([])
      return
    }
    setSearching(true)
    const timer = window.setTimeout(() => {
      searchBrokerages(query.trim())
        .then(setMatches)
        .catch(() => setMatches([]))
        .finally(() => setSearching(false))
    }, 300)
    return () => window.clearTimeout(timer)
  }, [query, brokerage])

  async function join(id: number) {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await joinBrokerage(id)
      await refreshUser()
      await onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not join that brokerage.')
    } finally {
      setBusy(false)
    }
  }

  async function create(event: React.FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    setErrors({})
    try {
      await createBrokerage(fields)
      await refreshUser()
      await onChanged()
    } catch (err) {
      if (err instanceof ApiError && err.data && typeof err.data === 'object') {
        const data = err.data as Record<string, unknown>
        // The serializer nests create errors under `create`; unwrap so the
        // message lands on the field it belongs to.
        const nested = (data.create ?? data) as Record<string, unknown>
        const parsed: Record<string, string> = {}
        for (const [key, value] of Object.entries(nested)) {
          parsed[key] = Array.isArray(value) ? String(value[0]) : String(value)
        }
        setErrors(parsed)
      } else {
        setError('Could not create that brokerage.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (brokerage) {
    return (
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-medium text-slate-700">Brokerage</h2>
        <div className="mt-3 flex items-center gap-3">
          {brokerage.logo_url ? (
            <img src={brokerage.logo_url} alt="" className="size-10 object-contain" />
          ) : (
            <span className="size-10 rounded bg-slate-100" />
          )}
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-800">{brokerage.name}</p>
            <p className="text-xs text-slate-500">
              Its logo and disclaimer are managed in{' '}
              <Link to="/brokerage" className="underline underline-offset-2">
                Brokerage settings
              </Link>
              .
            </p>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-medium text-slate-700">Brokerage</h2>
      <p className="mt-1 text-xs text-slate-500">
        Optional. You'll need it before you can export marketing material, since
        that has to say who published it — but not before then.
      </p>

      {error && (
        <p role="alert" className="mt-3 text-sm text-rose-600">
          {error}
        </p>
      )}

      <div className="mt-4 flex gap-1">
        {(['search', 'create'] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setMode(option)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
              mode === option ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            {option === 'search' ? 'Find my brokerage' : 'Add a new one'}
          </button>
        ))}
      </div>

      {mode === 'search' ? (
        <div className="mt-4 space-y-3">
          <p className="text-xs text-slate-500">
            Search first — joining the existing record keeps your firm's logo and
            disclaimer in one place.
          </p>
          <input
            type="text"
            value={query}
            placeholder="Start typing the brokerage name…"
            onChange={(event) => setQuery(event.target.value)}
            className={inputClass}
          />

          {searching && <p className="text-xs text-slate-500">Searching…</p>}

          {!searching && query.trim().length >= 2 && matches.length === 0 && (
            <p className="text-sm text-slate-500">
              No match.{' '}
              <button
                type="button"
                onClick={() => {
                  setMode('create')
                  setFields((current) => ({ ...current, name: query.trim() }))
                }}
                className="font-medium underline underline-offset-2"
              >
                Add “{query.trim()}” instead
              </button>
              .
            </p>
          )}

          {matches.length > 0 && (
            <ul className="space-y-2">
              {matches.map((match) => (
                <li key={match.id}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void join(match.id)}
                    className="flex w-full items-center gap-3 rounded-md border border-slate-200 p-3 text-left transition hover:border-slate-400 disabled:opacity-60"
                  >
                    {match.logo_url ? (
                      <img src={match.logo_url} alt="" className="size-8 object-contain" />
                    ) : (
                      <span className="size-8 rounded bg-slate-100" />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-slate-800">
                        {match.name}
                      </span>
                      <span className="block text-xs text-slate-500">
                        {match.agent_count} agent{match.agent_count === 1 ? '' : 's'}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs font-medium text-slate-600">Join</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <form onSubmit={(event) => void create(event)} noValidate className="mt-4 space-y-4">
          <Field label="Brokerage name" error={errors.name}>
            <input
              type="text"
              required
              value={fields.name}
              onChange={(event) => setFields({ ...fields, name: event.target.value })}
              className={inputClass}
            />
          </Field>
          <Field
            label="Required disclaimer"
            error={errors.required_disclaimer}
            hint="The compliance text that must appear on your marketing material."
          >
            <textarea
              rows={3}
              value={fields.required_disclaimer}
              onChange={(event) =>
                setFields({ ...fields, required_disclaimer: event.target.value })
              }
              className={inputClass}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Phone" error={errors.phone}>
              <input
                type="tel"
                value={fields.phone}
                onChange={(event) => setFields({ ...fields, phone: event.target.value })}
                className={inputClass}
              />
            </Field>
            <Field label="Licence number" error={errors.licence_number}>
              <input
                type="text"
                value={fields.licence_number}
                onChange={(event) =>
                  setFields({ ...fields, licence_number: event.target.value })
                }
                className={inputClass}
              />
            </Field>
          </div>
          <p className="text-xs text-slate-500">
            You'll be able to upload the logo and edit these afterwards, since
            creating a brokerage makes you its administrator.
          </p>
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? 'Adding…' : 'Add brokerage'}
          </button>
        </form>
      )}
    </section>
  )
}

const inputClass =
  'mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900'

function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string
  error?: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
      {error && (
        <span role="alert" className="mt-1 block text-xs text-rose-600">
          {error}
        </span>
      )}
    </label>
  )
}
