import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext.tsx'
import { ApiError } from '../lib/apiClient.ts'
import { landingPathFor } from '../lib/routes.ts'

type LocationState = { from?: { pathname?: string } }

export default function LoginPage() {
  const { login, status, user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Where the user was headed before the guard intercepted them. Honoured
  // only if the account that just signed in can actually open it — see
  // `landingPathFor`.
  const intended = (location.state as LocationState | null)?.from?.pathname ?? null

  // Already signed in?
  //
  // Only bounce when a guard sent them here — that is the case where they were
  // going somewhere, got intercepted, and already have the session they need.
  //
  // Arriving at /login deliberately means the opposite: they want to sign in as
  // somebody else. Redirecting them then makes switching accounts impossible
  // without finding Sign out first, and the redirect lands on whichever
  // dashboard the OLD account owns — so trying to sign in as the platform
  // owner while an agency session is open silently reopens the agency
  // dashboard, and it looks like the password was ignored.
  if (status === 'authenticated' && intended) {
    return <Navigate to={landingPathFor(user, intended)} replace />
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)

    try {
      const signedIn = await login({ email, password })
      // On success the access token is in memory and the refresh token is in
      // an httpOnly cookie the browser stored for us. Nothing to persist here.
      //
      // Routed off the user `login` returned rather than the context's, which
      // this render was captured before and would still read as null.
      void navigate(landingPathFor(signedIn, intended), { replace: true })
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : 'Could not reach the server. Please try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6 py-12">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Sign in</h1>
        <p className="mt-1 text-sm text-slate-500">Real Estate platform</p>

        {/* Signing in here replaces the session that is already open. Said out
            loud because the alternative is silent: you type a different
            username, land on the previous account's dashboard, and conclude
            the password was wrong. */}
        {status === 'authenticated' && user && (
          <p className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
            Signed in as <span className="font-medium">{user.email}</span>.
            Signing in below switches to a different account.{' '}
            <Link to={landingPathFor(user, null)} className="underline underline-offset-2">
              Stay signed in
            </Link>
          </p>
        )}

        <form
          onSubmit={(event) => void handleSubmit(event)}
          className="mt-8 space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
          noValidate
        >
          {error && (
            <div
              role="alert"
              className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
            >
              {error}
            </div>
          )}

          <div>
            <label htmlFor="email" className="block text-sm font-medium text-slate-700">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-slate-700">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
            />
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>

          <p className="text-center text-sm text-slate-500">
            New here?{' '}
            <Link
              to="/register"
              className="font-medium text-slate-800 underline underline-offset-2"
            >
              Register as an agent
            </Link>
          </p>
        </form>
      </div>
    </main>
  )
}
