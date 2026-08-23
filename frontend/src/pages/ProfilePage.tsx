import { useCallback, useEffect, useState, type FormEvent } from 'react'

import {
  fetchMyProfile,
  updateMyProfile,
  type AgentProfile,
} from '../api/profiles.ts'
import BrokerageSetupCard from '../components/BrokerageSetupCard.tsx'
import {
  Alert,
  Card,
  ImageField,
  SubmitButton,
  TextField,
  fieldErrors,
} from '../components/FormControls.tsx'
import { ApiError, apiRequest } from '../lib/apiClient.ts'

type Form = {
  name: string
  phone: string
  email: string
  job_title: string
  tagline: string
  licence_number: string
}

const EMPTY: Form = {
  name: '',
  phone: '',
  email: '',
  job_title: '',
  tagline: '',
  licence_number: '',
}

/**
 * An agent editing their own profile.
 *
 * Everything goes through /api/agents/me/, which resolves the profile from the
 * access token. There is no profile id in the URL or the payload, so this form
 * structurally cannot be pointed at someone else's record.
 */
export default function ProfilePage() {
  const [profile, setProfile] = useState<AgentProfile | null>(null)
  const [form, setForm] = useState<Form>(EMPTY)
  const [photo, setPhoto] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // Also called after the brokerage card changes anything, so the read-only
  // view of it below reflects the join or create without a page reload.
  const reload = useCallback(
    () =>
      fetchMyProfile()
        .then((data) => {
          setProfile(data)
          setForm({
            name: data.name,
            phone: data.phone,
            email: data.email,
            job_title: data.job_title,
            tagline: data.tagline,
            licence_number: data.licence_number,
          })
        })
        .catch((error: unknown) =>
          setLoadError(
            error instanceof ApiError ? error.message : 'Could not load your profile.',
          ),
        ),
    [],
  )

  useEffect(() => {
    void reload()
  }, [reload])

  function update<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setErrors({})
    setMessage(null)

    try {
      // The photo is only included when one was picked, so saving text fields
      // does not re-upload the existing image.
      const updated = await updateMyProfile(photo ? { ...form, photo } : form)
      setProfile(updated)
      setPhoto(null)
      setMessage('Profile saved.')
    } catch (error) {
      const parsed = fieldErrors(error)
      setErrors(parsed)
      if (Object.keys(parsed).length === 0) {
        setErrors({ detail: 'Could not save your profile. Please try again.' })
      }
    } finally {
      setSaving(false)
    }
  }

  if (loadError) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold tracking-tight">My profile</h1>
        <Alert kind="error">{loadError}</Alert>
      </div>
    )
  }

  if (!profile) {
    return <p className="text-sm text-slate-500">Loading…</p>
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">My profile</h1>
        <p className="mt-1 text-sm text-slate-500">
          This is how you appear on marketing material.
        </p>
      </div>

      {message && <Alert kind="success">{message}</Alert>}
      {errors.detail && <Alert kind="error">{errors.detail}</Alert>}

      <form onSubmit={(event) => void handleSubmit(event)} className="space-y-6">
        <Card title="Details">
          <ImageField
            label="Photo"
            currentUrl={profile.photo_url}
            onSelect={setPhoto}
            error={errors.photo}
          />
          <TextField
            label="Display name"
            value={form.name}
            onChange={(value) => update('name', value)}
            error={errors.name}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Job title"
              value={form.job_title}
              onChange={(value) => update('job_title', value)}
              error={errors.job_title}
            />
            <TextField
              label="Phone"
              type="tel"
              value={form.phone}
              onChange={(value) => update('phone', value)}
              error={errors.phone}
            />
          </div>
          <TextField
            label="Public email"
            type="email"
            value={form.email}
            onChange={(value) => update('email', value)}
            error={errors.email}
            hint="Shown on listings. Can differ from your sign-in address."
          />
          <TextField
            label="Tagline"
            value={form.tagline}
            onChange={(value) => update('tagline', value)}
            error={errors.tagline}
            maxLength={255}
          />
          <TextField
            label="Licence number"
            value={form.licence_number}
            onChange={(value) => update('licence_number', value)}
            error={errors.licence_number}
            hint="Where your jurisdiction requires it on marketing material."
          />
        </Card>

        <SubmitButton saving={saving} />
      </form>

      {/* Outside the form above: creating a brokerage submits its own, and a
          nested <form> is invalid HTML. */}
      <BrokerageSetupCard
        brokerage={profile.brokerage_detail ?? null}
        onChanged={reload}
      />

      <SystemStatusCard />
    </div>
  )
}

type HealthResponse = {
  status: 'ok' | 'error'
  checks: Record<string, { status: 'ok' | 'error'; detail?: string }>
}

/**
 * Backend health, relocated from the dashboard.
 *
 * It lives in Settings because it is diagnostic, not actionable: an agent
 * cannot fix a failing Redis, but "is it me or the service?" is a question
 * this page can answer when something misbehaves — the same reason status
 * pages exist.
 */
function SystemStatusCard() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    apiRequest<HealthResponse>('/api/health/')
      .then(setHealth)
      .catch(() => setFailed(true))
  }, [])

  return (
    <Card title="System status">
      {failed ? (
        <p className="text-sm text-slate-500">
          Could not reach the service — that itself is the status.
        </p>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm">
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
      )}
    </Card>
  )
}
