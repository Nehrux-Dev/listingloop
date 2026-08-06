import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { registerAgent } from '../api/onboarding.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { ApiError } from '../lib/apiClient.ts'

/**
 * Step 1 of agent registration.
 *
 * Deliberately matches LoginPage: same card, same field styling, same
 * button — this is the other half of one front door, not a different product.
 *
 * On success the API returns a session (access token + httpOnly refresh
 * cookie), so onboarding continues straight into step 2 rather than bouncing
 * the new agent to a sign-in form they just implicitly passed.
 */
export default function RegisterPage() {
  const { status, refresh } = useAuth()
  const navigate = useNavigate()

  const [form, setForm] = useState({
    first_name: '',
    last_name: '',
    email: '',
    password: '',
    password_confirm: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)

  if (status === 'authenticated') {
    return <Navigate to="/onboarding" replace />
  }

  function update(key: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    // Guard against a double-click queueing two accounts.
    if (submitting) return

    setSubmitting(true)
    setErrors({})

    // Checked here for a fast, friendly message — and again on the server,
    // which is the check that actually counts.
    if (form.password !== form.password_confirm) {
      setErrors({ password_confirm: 'The two passwords do not match.' })
      setSubmitting(false)
      return
    }

    try {
      await registerAgent(form)
      await refresh()
      void navigate('/onboarding', { replace: true })
    } catch (error) {
      if (error instanceof ApiError && error.data && typeof error.data === 'object') {
        const parsed: Record<string, string> = {}
        for (const [key, value] of Object.entries(error.data as Record<string, unknown>)) {
          parsed[key] = Array.isArray(value) ? String(value[0]) : String(value)
        }
        setErrors(parsed)
      } else {
        setErrors({ detail: 'Could not create your account. Please try again.' })
      }
      setSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6 py-12">
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          Create your agent account
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Step 1 of 4 — we'll set up your profile and branding next.
        </p>

        <form
          onSubmit={(event) => void handleSubmit(event)}
          className="mt-8 space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
          noValidate
        >
          {errors.detail && (
            <div
              role="alert"
              className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
            >
              {errors.detail}
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="First name" error={errors.first_name}>
              <input
                type="text"
                autoComplete="given-name"
                required
                value={form.first_name}
                onChange={(event) => update('first_name', event.target.value)}
                className={inputClass}
              />
            </Field>
            <Field label="Last name" error={errors.last_name}>
              <input
                type="text"
                autoComplete="family-name"
                required
                value={form.last_name}
                onChange={(event) => update('last_name', event.target.value)}
                className={inputClass}
              />
            </Field>
          </div>

          <Field label="Email address" error={errors.email}>
            <input
              type="email"
              autoComplete="email"
              required
              value={form.email}
              onChange={(event) => update('email', event.target.value)}
              className={inputClass}
            />
          </Field>

          <Field
            label="Password"
            error={errors.password}
            hint="At least 10 characters, and not a common password."
          >
            <input
              type="password"
              autoComplete="new-password"
              required
              value={form.password}
              onChange={(event) => update('password', event.target.value)}
              className={inputClass}
            />
          </Field>

          <Field label="Confirm password" error={errors.password_confirm}>
            <input
              type="password"
              autoComplete="new-password"
              required
              value={form.password_confirm}
              onChange={(event) => update('password_confirm', event.target.value)}
              className={inputClass}
            />
          </Field>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? 'Creating your account…' : 'Create account'}
          </button>

          <p className="text-center text-sm text-slate-500">
            Already have an account?{' '}
            <Link to="/login" className="font-medium text-slate-800 underline underline-offset-2">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </main>
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
