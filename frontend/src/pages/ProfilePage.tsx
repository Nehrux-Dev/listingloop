import { useEffect, useState, type FormEvent } from 'react'

import {
  fetchMyProfile,
  updateMyProfile,
  type AgentProfile,
} from '../api/profiles.ts'
import {
  Alert,
  Card,
  ImageField,
  SubmitButton,
  TextField,
  fieldErrors,
} from '../components/FormControls.tsx'
import { ApiError } from '../lib/apiClient.ts'

type Form = {
  name: string
  phone: string
  email: string
  job_title: string
  tagline: string
}

const EMPTY: Form = { name: '', phone: '', email: '', job_title: '', tagline: '' }

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

  useEffect(() => {
    fetchMyProfile()
      .then((data) => {
        setProfile(data)
        setForm({
          name: data.name,
          phone: data.phone,
          email: data.email,
          job_title: data.job_title,
          tagline: data.tagline,
        })
      })
      .catch((error: unknown) =>
        setLoadError(
          error instanceof ApiError ? error.message : 'Could not load your profile.',
        ),
      )
  }, [])

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
        </Card>

        <Card
          title="Brokerage"
          description="Set by your brokerage administrator — contact them to change it."
        >
          <div className="flex items-center gap-3">
            {profile.brokerage_detail?.logo_url && (
              <img
                src={profile.brokerage_detail.logo_url}
                alt=""
                className="size-10 rounded object-contain"
              />
            )}
            <p className="text-sm text-slate-700">
              {profile.brokerage_detail?.name ?? 'Not assigned to a brokerage yet.'}
            </p>
          </div>
          {profile.brokerage_detail?.required_disclaimer && (
            <p className="rounded-md bg-slate-50 p-3 text-xs text-slate-500">
              {profile.brokerage_detail.required_disclaimer}
            </p>
          )}
        </Card>

        <SubmitButton saving={saving} />
      </form>
    </div>
  )
}
