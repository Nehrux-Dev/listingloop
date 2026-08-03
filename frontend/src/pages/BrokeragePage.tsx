import { useEffect, useState, type FormEvent } from 'react'

import {
  fetchAgents,
  fetchBrokerages,
  updateBrokerage,
  type AgentProfile,
  type Brokerage,
} from '../api/profiles.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import {
  Alert,
  Card,
  ImageField,
  SubmitButton,
  TextAreaField,
  TextField,
  fieldErrors,
} from '../components/FormControls.tsx'
import { ApiError } from '../lib/apiClient.ts'

type Form = {
  name: string
  required_disclaimer: string
  website: string
  phone: string
}

/**
 * Brokerage administration.
 *
 * The list endpoint is already scoped server-side: a Brokerage Admin only ever
 * receives the brokerages they administer, so there is no client-side filter
 * to get wrong. A Nehrux Admin sees all of them and picks one.
 */
export default function BrokeragePage() {
  const { hasRole } = useAuth()
  const [brokerages, setBrokerages] = useState<Brokerage[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [form, setForm] = useState<Form | null>(null)
  const [logo, setLogo] = useState<File | null>(null)
  const [agents, setAgents] = useState<AgentProfile[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    Promise.all([fetchBrokerages(), fetchAgents()])
      .then(([brokeragePage, agentPage]) => {
        setBrokerages(brokeragePage.results)
        setAgents(agentPage.results)
        const first = brokeragePage.results[0]
        if (first) {
          setSelectedId(first.id)
          setForm(pickForm(first))
        }
      })
      .catch((error: unknown) =>
        setLoadError(
          error instanceof ApiError ? error.message : 'Could not load brokerages.',
        ),
      )
  }, [])

  const selected = brokerages.find((item) => item.id === selectedId) ?? null

  function pickForm(brokerage: Brokerage): Form {
    return {
      name: brokerage.name,
      required_disclaimer: brokerage.required_disclaimer,
      website: brokerage.website,
      phone: brokerage.phone,
    }
  }

  function select(id: number) {
    const brokerage = brokerages.find((item) => item.id === id)
    if (!brokerage) return
    setSelectedId(id)
    setForm(pickForm(brokerage))
    setLogo(null)
    setErrors({})
    setMessage(null)
  }

  function update<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => (current ? { ...current, [key]: value } : current))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selected || !form) return

    setSaving(true)
    setErrors({})
    setMessage(null)

    try {
      const updated = await updateBrokerage(
        selected.id,
        logo ? { ...form, logo } : form,
      )
      setBrokerages((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      )
      setLogo(null)
      setMessage('Brokerage saved.')
    } catch (error) {
      const parsed = fieldErrors(error)
      setErrors(parsed)
      if (Object.keys(parsed).length === 0) {
        setErrors({ detail: 'Could not save the brokerage. Please try again.' })
      }
    } finally {
      setSaving(false)
    }
  }

  if (loadError) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold tracking-tight">Brokerage</h1>
        <Alert kind="error">{loadError}</Alert>
      </div>
    )
  }

  if (!selected || !form) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold tracking-tight">Brokerage</h1>
        <p className="text-sm text-slate-500">
          You are not assigned to a brokerage yet.
          {hasRole('nehrux_admin') && ' Create one in the Django admin.'}
        </p>
      </div>
    )
  }

  const brokerageAgents = agents.filter((agent) => agent.brokerage === selected.id)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Brokerage</h1>
        <p className="mt-1 text-sm text-slate-500">
          Organisation details applied to every agent's marketing material.
        </p>
      </div>

      {brokerages.length > 1 && (
        <select
          value={selected.id}
          onChange={(event) => select(Number(event.target.value))}
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm sm:w-72"
        >
          {brokerages.map((brokerage) => (
            <option key={brokerage.id} value={brokerage.id}>
              {brokerage.name}
            </option>
          ))}
        </select>
      )}

      {message && <Alert kind="success">{message}</Alert>}
      {errors.detail && <Alert kind="error">{errors.detail}</Alert>}

      <form onSubmit={(event) => void handleSubmit(event)} className="space-y-6">
        <Card title="Details">
          <ImageField
            label="Logo"
            currentUrl={selected.logo_url}
            onSelect={setLogo}
            error={errors.logo}
          />
          <TextField
            label="Name"
            value={form.name}
            onChange={(value) => update('name', value)}
            error={errors.name}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Website"
              type="url"
              value={form.website}
              onChange={(value) => update('website', value)}
              error={errors.website}
              placeholder="https://"
            />
            <TextField
              label="Phone"
              type="tel"
              value={form.phone}
              onChange={(value) => update('phone', value)}
              error={errors.phone}
            />
          </div>
        </Card>

        <Card
          title="Required disclaimer"
          description="Regulatory text that must appear on material produced for this brokerage."
        >
          <TextAreaField
            label="Disclaimer text"
            value={form.required_disclaimer}
            onChange={(value) => update('required_disclaimer', value)}
            error={errors.required_disclaimer}
            rows={5}
          />
        </Card>

        <SubmitButton saving={saving} />
      </form>

      <Card title={`Agents (${brokerageAgents.length})`}>
        {brokerageAgents.length === 0 ? (
          <p className="text-sm text-slate-500">No agents assigned yet.</p>
        ) : (
          <ul className="divide-y divide-slate-100 text-sm">
            {brokerageAgents.map((agent) => (
              <li key={agent.id} className="flex items-center gap-3 py-2">
                <div className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-slate-100">
                  {agent.photo_url ? (
                    <img src={agent.photo_url} alt="" className="size-full object-cover" />
                  ) : (
                    <span className="text-[10px] text-slate-400">—</span>
                  )}
                </div>
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-700">{agent.name}</p>
                  <p className="truncate text-xs text-slate-500">{agent.user_email}</p>
                </div>
                <span className="ml-auto shrink-0 text-xs text-slate-500">
                  {agent.job_title}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
