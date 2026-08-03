import { useEffect, useState, type FormEvent } from 'react'

import {
  DESIGN_STYLES,
  fetchMyBrandKit,
  updateBrandKit,
  type BrandKit,
  type DesignStyle,
} from '../api/profiles.ts'
import {
  Alert,
  Card,
  ColorField,
  SelectField,
  SubmitButton,
  TextField,
  fieldErrors,
} from '../components/FormControls.tsx'
import { ApiError } from '../lib/apiClient.ts'

type Form = {
  primary_color: string
  secondary_color: string
  accent_color: string
  heading_font: string
  body_font: string
  design_style: DesignStyle
}

/** An agent editing their own brand kit. */
export default function BrandKitPage() {
  const [kit, setKit] = useState<BrandKit | null>(null)
  const [form, setForm] = useState<Form | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    // GET /mine/ creates the kit with sensible defaults if it does not exist,
    // so the form never has to handle a create-or-update fork.
    fetchMyBrandKit()
      .then((data) => {
        setKit(data)
        setForm({
          primary_color: data.primary_color,
          secondary_color: data.secondary_color,
          accent_color: data.accent_color,
          heading_font: data.heading_font,
          body_font: data.body_font,
          design_style: data.design_style,
        })
      })
      .catch((error: unknown) =>
        setLoadError(
          error instanceof ApiError ? error.message : 'Could not load your brand kit.',
        ),
      )
  }, [])

  function update<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => (current ? { ...current, [key]: value } : current))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!kit || !form) return

    setSaving(true)
    setErrors({})
    setMessage(null)

    try {
      const updated = await updateBrandKit(kit.id, form)
      setKit(updated)
      setMessage('Brand kit saved.')
    } catch (error) {
      const parsed = fieldErrors(error)
      setErrors(parsed)
      if (Object.keys(parsed).length === 0) {
        setErrors({ detail: 'Could not save your brand kit. Please try again.' })
      }
    } finally {
      setSaving(false)
    }
  }

  if (loadError) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold tracking-tight">Brand kit</h1>
        <Alert kind="error">{loadError}</Alert>
      </div>
    )
  }

  if (!form || !kit) {
    return <p className="text-sm text-slate-500">Loading…</p>
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Brand kit</h1>
        <p className="mt-1 text-sm text-slate-500">
          Colours, fonts and style used when generating your marketing material.
        </p>
      </div>

      {message && <Alert kind="success">{message}</Alert>}
      {errors.detail && <Alert kind="error">{errors.detail}</Alert>}

      <form onSubmit={(event) => void handleSubmit(event)} className="space-y-6">
        <Card title="Colours">
          <div className="grid gap-4 sm:grid-cols-3">
            <ColorField
              label="Primary"
              value={form.primary_color}
              onChange={(value) => update('primary_color', value)}
              error={errors.primary_color}
            />
            <ColorField
              label="Secondary"
              value={form.secondary_color}
              onChange={(value) => update('secondary_color', value)}
              error={errors.secondary_color}
            />
            <ColorField
              label="Accent"
              value={form.accent_color}
              onChange={(value) => update('accent_color', value)}
              error={errors.accent_color}
            />
          </div>

          <div className="flex items-center gap-2 pt-1">
            <span className="text-xs text-slate-500">Preview</span>
            <div className="flex h-8 flex-1 overflow-hidden rounded-md border border-slate-200">
              {[form.primary_color, form.secondary_color, form.accent_color].map(
                (color, index) => (
                  <div
                    key={index}
                    className="flex-1"
                    style={{ backgroundColor: color }}
                    aria-hidden="true"
                  />
                ),
              )}
            </div>
          </div>
        </Card>

        <Card title="Typography and style">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Heading font"
              value={form.heading_font}
              onChange={(value) => update('heading_font', value)}
              error={errors.heading_font}
            />
            <TextField
              label="Body font"
              value={form.body_font}
              onChange={(value) => update('body_font', value)}
              error={errors.body_font}
            />
          </div>
          <SelectField
            label="Preferred design style"
            value={form.design_style}
            options={DESIGN_STYLES}
            onChange={(value) => update('design_style', value)}
            error={errors.design_style}
          />
        </Card>

        <SubmitButton saving={saving} />
      </form>
    </div>
  )
}
