import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  completeOnboarding,
  createBrokerage,
  fetchOnboardingStatus,
  joinBrokerage,
  searchBrokerages,
  type BrokerageMatch,
  type OnboardingStatus,
} from '../api/onboarding.ts'
import { DESIGN_STYLES, fetchMyBrandKit, updateBrandKit, updateMyProfile } from '../api/profiles.ts'
import { Alert } from '../components/FormControls.tsx'
import { ApiError } from '../lib/apiClient.ts'

type StepKey = 'profile' | 'brokerage' | 'brand' | 'done'

const STEPS: { key: StepKey; label: string }[] = [
  { key: 'profile', label: 'Your profile' },
  { key: 'brokerage', label: 'Brokerage' },
  { key: 'brand', label: 'Brand kit' },
  { key: 'done', label: 'Finish' },
]

/**
 * Steps 2–4 of registration.
 *
 * Each step saves to the API as the agent leaves it, rather than holding
 * everything until the end. Two reasons: a dropped connection on step 4 does
 * not lose steps 2 and 3, and an agent who abandons onboarding halfway can
 * resume — the server already knows how far they got, which is what
 * `/onboarding/status/` reports.
 *
 * These write through the SAME endpoints the settings pages use. Onboarding is
 * a guided path through existing functionality, not a parallel one.
 */
export default function OnboardingPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState<StepKey>('profile')
  const [status, setStatus] = useState<OnboardingStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await fetchOnboardingStatus()
      setStatus(data)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load your progress.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (error && !status) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-12">
        <Alert kind="error">{error}</Alert>
      </main>
    )
  }

  if (!status) {
    return <p className="px-6 py-12 text-center text-sm text-slate-500">Loading…</p>
  }

  const stepIndex = STEPS.findIndex((item) => item.key === step)

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          Set up your marketing profile
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Enter this once — every design you make will use it automatically.
        </p>
      </header>

      <ol className="mt-8 flex items-center gap-2">
        {STEPS.map((item, index) => {
          const done = index < stepIndex
          const current = index === stepIndex
          return (
            <li key={item.key} className="flex flex-1 items-center gap-2">
              <span
                className={`flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                  current
                    ? 'bg-slate-900 text-white'
                    : done
                      ? 'bg-emerald-600 text-white'
                      : 'bg-slate-200 text-slate-500'
                }`}
              >
                {done ? '✓' : index + 1}
              </span>
              <span
                className={`hidden text-xs font-medium sm:block ${
                  current ? 'text-slate-900' : 'text-slate-500'
                }`}
              >
                {item.label}
              </span>
              {index < STEPS.length - 1 && (
                <span className="h-px flex-1 bg-slate-200" aria-hidden="true" />
              )}
            </li>
          )
        })}
      </ol>

      {error && (
        <div className="mt-6">
          <Alert kind="error">{error}</Alert>
        </div>
      )}

      <div className="mt-6">
        {step === 'profile' && (
          <ProfileStep
            status={status}
            busy={busy}
            setBusy={setBusy}
            setError={setError}
            onDone={async () => {
              await load()
              setStep('brokerage')
            }}
          />
        )}
        {step === 'brokerage' && (
          <BrokerageStep
            status={status}
            busy={busy}
            setBusy={setBusy}
            setError={setError}
            onBack={() => setStep('profile')}
            onDone={async () => {
              await load()
              setStep('brand')
            }}
          />
        )}
        {step === 'brand' && (
          <BrandStep
            busy={busy}
            setBusy={setBusy}
            setError={setError}
            onBack={() => setStep('brokerage')}
            onDone={async () => {
              await load()
              setStep('done')
            }}
          />
        )}
        {step === 'done' && (
          <FinishStep
            status={status}
            busy={busy}
            onBack={() => setStep('brand')}
            onFinish={async () => {
              setBusy(true)
              try {
                await completeOnboarding()
                void navigate('/', { replace: true })
              } finally {
                setBusy(false)
              }
            }}
            onFix={(target) => setStep(target)}
          />
        )}
      </div>
    </main>
  )
}

// ---------------------------------------------------------------------------

const inputClass =
  'mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900'

function Card({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
      {description && <p className="mt-1 text-xs text-slate-500">{description}</p>}
      <div className="mt-5 space-y-4">{children}</div>
    </section>
  )
}

function Field({ label, error, hint, children }: { label: string; error?: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
      {error && <span className="mt-1 block text-xs text-rose-600">{error}</span>}
    </label>
  )
}

function Controls({
  onBack,
  busy,
  label = 'Continue',
}: {
  onBack?: () => void
  busy: boolean
  label?: string
}) {
  return (
    <div className="flex items-center gap-2 pt-2">
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          Previous
        </button>
      )}
      <button
        type="submit"
        disabled={busy}
        className="ml-auto rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {busy ? 'Saving…' : label}
      </button>
    </div>
  )
}

type StepProps = {
  status: OnboardingStatus
  busy: boolean
  setBusy: (value: boolean) => void
  setError: (value: string | null) => void
  onDone: () => Promise<void>
  onBack?: () => void
}

function ProfileStep({ status, busy, setBusy, setError, onDone }: StepProps) {
  const profile = status.profile
  const [form, setForm] = useState({
    name: profile?.name ?? '',
    phone: profile?.phone ?? '',
    email: profile?.email ?? '',
    job_title: profile?.job_title ?? '',
    tagline: profile?.tagline ?? '',
    licence_number: profile?.licence_number ?? '',
  })
  const [photo, setPhoto] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(profile?.photo_url ?? null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  function update(key: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    setErrors({})
    try {
      await updateMyProfile(photo ? { ...form, photo } : form)
      await onDone()
    } catch (err) {
      if (err instanceof ApiError && err.data && typeof err.data === 'object') {
        const parsed: Record<string, string> = {}
        for (const [key, value] of Object.entries(err.data as Record<string, unknown>)) {
          parsed[key] = Array.isArray(value) ? String(value[0]) : String(value)
        }
        setErrors(parsed)
      } else {
        setError('Could not save your profile.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4" noValidate>
      <Card
        title="Your professional details"
        description="This appears on every marketing asset you create."
      >
        <div className="flex items-center gap-4">
          <div className="flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-full border border-slate-200 bg-slate-100">
            {preview ? (
              <img src={preview} alt="" className="size-full object-cover" />
            ) : (
              <span className="text-xs text-slate-400">Photo</span>
            )}
          </div>
          <label className="flex-1">
            <span className="block text-sm font-medium text-slate-700">Profile photo</span>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null
                setPhoto(file)
                setPreview(file ? URL.createObjectURL(file) : preview)
              }}
              className="mt-1 block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-800"
            />
            {errors.photo && <span className="mt-1 block text-xs text-rose-600">{errors.photo}</span>}
          </label>
        </div>

        <Field label="Full name" error={errors.name}>
          <input type="text" required value={form.name} onChange={(e) => update('name', e.target.value)} className={inputClass} />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Job title" error={errors.job_title} hint="e.g. REALTOR®">
            <input type="text" value={form.job_title} onChange={(e) => update('job_title', e.target.value)} className={inputClass} />
          </Field>
          <Field label="Professional phone" error={errors.phone}>
            <input type="tel" value={form.phone} onChange={(e) => update('phone', e.target.value)} className={inputClass} />
          </Field>
        </div>

        <Field label="Professional email" error={errors.email} hint="Can differ from your sign-in address.">
          <input type="email" value={form.email} onChange={(e) => update('email', e.target.value)} className={inputClass} />
        </Field>

        <Field label="Tagline" error={errors.tagline} hint="e.g. Your Toronto Home Expert">
          <input type="text" maxLength={255} value={form.tagline} onChange={(e) => update('tagline', e.target.value)} className={inputClass} />
        </Field>

        <Field
          label="Licence number"
          error={errors.licence_number}
          hint="Where your jurisdiction requires it on marketing material."
        >
          <input type="text" value={form.licence_number} onChange={(e) => update('licence_number', e.target.value)} className={inputClass} />
        </Field>
      </Card>

      <Controls busy={busy} />
    </form>
  )
}

function BrokerageStep({ status, busy, setBusy, setError, onDone, onBack }: StepProps) {
  const [mode, setMode] = useState<'search' | 'create'>('search')
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<BrokerageMatch[]>([])
  const [searching, setSearching] = useState(false)
  const [fields, setFields] = useState({
    name: '',
    required_disclaimer: '',
    phone: '',
    website: '',
    licence_number: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Debounced: a request per keystroke would hammer the directory.
  useEffect(() => {
    if (query.trim().length < 2) {
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
  }, [query])

  async function join(id: number) {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await joinBrokerage(id)
      await onDone()
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
      await onDone()
    } catch (err) {
      if (err instanceof ApiError && err.data && typeof err.data === 'object') {
        const data = err.data as Record<string, unknown>
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

  if (status.brokerage) {
    return (
      <div className="space-y-4">
        <Card title="Brokerage" description="You can change this later in settings.">
          <div className="flex items-center gap-3">
            {status.brokerage.logo_url && (
              <img src={status.brokerage.logo_url} alt="" className="size-10 object-contain" />
            )}
            <div>
              <p className="text-sm font-medium text-slate-800">{status.brokerage.name}</p>
              {!status.brokerage.logo_url && (
                <p className="text-xs text-amber-700">
                  No logo yet — add one in Brokerage settings before exporting.
                </p>
              )}
            </div>
          </div>
        </Card>
        <div className="flex items-center gap-2 pt-2">
          <button type="button" onClick={onBack} className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50">
            Previous
          </button>
          <button
            type="button"
            onClick={() => void onDone()}
            className="ml-auto rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            Continue
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-1">
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
        <Card
          title="Find your brokerage"
          description="Search first — joining the existing record keeps your firm's logo and disclaimer in one place."
        >
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
              <button type="button" onClick={() => { setMode('create'); setFields((f) => ({ ...f, name: query.trim() })) }} className="font-medium underline underline-offset-2">
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
                      <span className="block truncate text-sm font-medium text-slate-800">{match.name}</span>
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
        </Card>
      ) : (
        <form onSubmit={(event) => void create(event)} noValidate>
          <Card title="Add your brokerage" description="You'll be able to manage its details afterwards.">
            <Field label="Brokerage name" error={errors.name}>
              <input type="text" required value={fields.name} onChange={(e) => setFields({ ...fields, name: e.target.value })} className={inputClass} />
            </Field>
            <Field
              label="Required disclaimer"
              error={errors.required_disclaimer}
              hint="The compliance text that must appear on your marketing material."
            >
              <textarea rows={3} value={fields.required_disclaimer} onChange={(e) => setFields({ ...fields, required_disclaimer: e.target.value })} className={inputClass} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Phone" error={errors.phone}>
                <input type="tel" value={fields.phone} onChange={(e) => setFields({ ...fields, phone: e.target.value })} className={inputClass} />
              </Field>
              <Field label="Licence number" error={errors.licence_number}>
                <input type="text" value={fields.licence_number} onChange={(e) => setFields({ ...fields, licence_number: e.target.value })} className={inputClass} />
              </Field>
            </div>
            <p className="text-xs text-slate-500">
              You can upload the brokerage logo on the next screens or in settings.
            </p>
          </Card>
          <Controls onBack={onBack} busy={busy} />
        </form>
      )}

      {mode === 'search' && (
        <div className="flex items-center gap-2 pt-2">
          <button type="button" onClick={onBack} className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50">
            Previous
          </button>
        </div>
      )}
    </div>
  )
}

function BrandStep({
  busy,
  setBusy,
  setError,
  onDone,
  onBack,
}: Omit<StepProps, 'status'>) {
  const [form, setForm] = useState({
    primary_color: '#0F172A',
    secondary_color: '#475569',
    accent_color: '#2563EB',
    heading_font: 'Inter',
    body_font: 'Inter',
    design_style: 'modern',
  })
  const [kitId, setKitId] = useState<number | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    // GET /mine/ creates the kit with defaults if it does not exist, so this
    // step always has something to bind to.
    fetchMyBrandKit()
      .then((kit) => {
        setKitId(kit.id)
        setForm({
          primary_color: kit.primary_color,
          secondary_color: kit.secondary_color,
          accent_color: kit.accent_color,
          heading_font: kit.heading_font,
          body_font: kit.body_font,
          design_style: kit.design_style,
        })
      })
      .catch(() => setKitId(null))
  }, [])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (busy || kitId === null) return
    setBusy(true)
    setError(null)
    setErrors({})
    try {
      await updateBrandKit(kitId, form as never)
      await onDone()
    } catch (err) {
      if (err instanceof ApiError && err.data && typeof err.data === 'object') {
        const parsed: Record<string, string> = {}
        for (const [key, value] of Object.entries(err.data as Record<string, unknown>)) {
          parsed[key] = Array.isArray(value) ? String(value[0]) : String(value)
        }
        setErrors(parsed)
      } else {
        setError('Could not save your brand kit.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4" noValidate>
      <Card title="Your brand" description="Applied automatically to every design you create.">
        <div className="grid gap-4 sm:grid-cols-3">
          {(['primary_color', 'secondary_color', 'accent_color'] as const).map((key) => (
            <Field
              key={key}
              label={key.replace('_color', '').replace(/^\w/, (c) => c.toUpperCase())}
              error={errors[key]}
            >
              <div className="mt-1 flex items-center gap-2">
                <input
                  type="color"
                  value={/^#[0-9a-fA-F]{6}$/.test(form[key]) ? form[key] : '#000000'}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value.toUpperCase() })}
                  className="size-9 shrink-0 cursor-pointer rounded-md border border-slate-300 bg-white p-1"
                />
                <input
                  type="text"
                  value={form[key]}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value.toUpperCase() })}
                  className="w-full rounded-md border border-slate-300 px-2 py-2 font-mono text-xs uppercase outline-none focus:border-slate-900"
                />
              </div>
            </Field>
          ))}
        </div>

        <div className="flex h-8 overflow-hidden rounded-md border border-slate-200">
          {[form.primary_color, form.secondary_color, form.accent_color].map((colour, index) => (
            <div key={index} className="flex-1" style={{ backgroundColor: colour }} aria-hidden="true" />
          ))}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Heading font" error={errors.heading_font}>
            <input type="text" value={form.heading_font} onChange={(e) => setForm({ ...form, heading_font: e.target.value })} className={inputClass} />
          </Field>
          <Field label="Body font" error={errors.body_font}>
            <input type="text" value={form.body_font} onChange={(e) => setForm({ ...form, body_font: e.target.value })} className={inputClass} />
          </Field>
        </div>

        <Field label="Preferred design style" error={errors.design_style}>
          <select
            value={form.design_style}
            onChange={(e) => setForm({ ...form, design_style: e.target.value })}
            className={inputClass}
          >
            {DESIGN_STYLES.map((style) => (
              <option key={style.value} value={style.value}>
                {style.label}
              </option>
            ))}
          </select>
        </Field>
      </Card>

      <Controls onBack={onBack} busy={busy} />
    </form>
  )
}

function FinishStep({
  status,
  busy,
  onBack,
  onFinish,
  onFix,
}: {
  status: OnboardingStatus
  busy: boolean
  onBack: () => void
  onFinish: () => Promise<void>
  onFix: (step: StepKey) => void
}) {
  const missing = status.missing_required

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-800">Profile completion</h2>
          <span className="text-lg font-semibold text-slate-900">
            {status.completion_percent}%
          </span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
          <div
            className={`h-full transition-all ${
              status.ready_for_marketing ? 'bg-emerald-600' : 'bg-amber-500'
            }`}
            style={{ width: `${status.completion_percent}%` }}
          />
        </div>

        {status.ready_for_marketing ? (
          <p className="mt-4 text-sm text-emerald-700">
            You have everything needed to generate marketing material.
          </p>
        ) : (
          <div className="mt-4">
            <p className="text-sm text-slate-700">
              You can finish now, but these are needed before you can export a design:
            </p>
            <ul className="mt-2 space-y-1">
              {missing.map((field) => (
                <li key={field.key} className="flex items-center gap-2 text-sm">
                  <span className="text-amber-600" aria-hidden="true">
                    ●
                  </span>
                  <span className="text-slate-700">{field.label}</span>
                  <button
                    type="button"
                    onClick={() => onFix(field.step)}
                    className="ml-auto text-xs font-medium text-slate-600 underline underline-offset-2"
                  >
                    Fix in {field.step_label}
                  </button>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-slate-500">
              You can also add these later from your profile settings — you will not
              need to register again.
            </p>
          </div>
        )}
      </section>

      <div className="flex items-center gap-2 pt-2">
        <button
          type="button"
          onClick={onBack}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onFinish()}
          className="ml-auto rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
        >
          {busy ? 'Finishing…' : 'Go to dashboard'}
        </button>
      </div>
    </div>
  )
}
