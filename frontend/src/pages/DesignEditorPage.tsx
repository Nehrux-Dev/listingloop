import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  deleteDesign,
  duplicateDesign,
  exportDesign,
  fetchDesign,
  fetchRenderDimensions,
  fetchResolvedDesign,
  fetchTemplate,
  previewDesign,
  renameDesign,
  saveDesignOverrides,
  type Design,
  type Overrides,
  type RenderDimension,
  type ResolvedDesign,
  type TemplateDetail,
} from '../api/templates.ts'
import { fetchDesignCompliance, type ComplianceReport } from '../api/compliance.ts'
import { CompliancePanel } from '../components/CompliancePanel.tsx'
import { Alert, Card } from '../components/FormControls.tsx'
import { ElementControls } from '../components/ElementControls.tsx'
import { ApiError } from '../lib/apiClient.ts'

export default function DesignEditorPage() {
  const { id } = useParams<{ id: string }>()
  const designId = Number(id)
  const navigate = useNavigate()

  const [design, setDesign] = useState<Design | null>(null)
  const [template, setTemplate] = useState<TemplateDetail | null>(null)
  const [resolved, setResolved] = useState<ResolvedDesign | null>(null)
  const [dimensions, setDimensions] = useState<RenderDimension[]>([])

  const [overrides, setOverrides] = useState<Overrides>({})
  const [dimension, setDimension] = useState('instagram_post')
  const [preview, setPreview] = useState<string | null>(null)
  const [previewMs, setPreviewMs] = useState<number | null>(null)

  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)

  const [exportDims, setExportDims] = useState<string[]>(['instagram_post'])
  const [exportFormat, setExportFormat] = useState<'png' | 'jpg'>('png')
  const [compliance, setCompliance] = useState<ComplianceReport | null>(null)
  const [checkingCompliance, setCheckingCompliance] = useState(true)

  const checkCompliance = useCallback(async () => {
    setCheckingCompliance(true)
    try {
      setCompliance(await fetchDesignCompliance(designId))
    } catch {
      setCompliance(null)
    } finally {
      setCheckingCompliance(false)
    }
  }, [designId])

  const load = useCallback(async () => {
    try {
      const loaded = await fetchDesign(designId)
      setDesign(loaded)
      setOverrides(loaded.overrides ?? {})
      const [detail, resolvedDesign] = await Promise.all([
        fetchTemplate(loaded.template),
        fetchResolvedDesign(designId, dimension),
      ])
      setTemplate(detail)
      setResolved(resolvedDesign)
    } catch (error) {
      setLoadError(
        error instanceof ApiError ? error.message : 'Could not open this design.',
      )
    }
  }, [designId, dimension])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    void checkCompliance()
  }, [checkCompliance])

  useEffect(() => {
    fetchRenderDimensions().then(setDimensions).catch(() => setDimensions([]))
  }, [])

  function changeField(elementKey: string, field: string, value: unknown) {
    setDirty(true)
    setMessage(null)
    setOverrides((current) => ({
      ...current,
      [elementKey]: { ...(current[elementKey] ?? {}), [field]: value },
    }))
  }

  function clearElement(elementKey: string) {
    setDirty(true)
    setOverrides((current) => {
      const next = { ...current }
      delete next[elementKey]
      return next
    })
  }

  async function save() {
    setBusy(true)
    setErrors({})
    setMessage(null)
    try {
      const saved = await saveDesignOverrides(designId, overrides)
      setDesign(saved)
      setOverrides(saved.overrides ?? {})
      setDirty(false)
      setMessage('Design saved.')
      setResolved(await fetchResolvedDesign(designId, dimension))
      // The edit may have introduced or fixed a compliance issue.
      void checkCompliance()
    } catch (error) {
      // The server returns errors keyed by element, so they land on the
      // control that caused them.
      if (error instanceof ApiError && error.data && typeof error.data === 'object') {
        const parsed: Record<string, string> = {}
        for (const [key, value] of Object.entries(error.data as Record<string, unknown>)) {
          parsed[key] = Array.isArray(value) ? String(value[0]) : String(value)
        }
        setErrors(parsed)
      } else {
        setErrors({ detail: 'Could not save this design.' })
      }
    } finally {
      setBusy(false)
    }
  }

  async function runPreview() {
    setBusy(true)
    setErrors({})
    try {
      const result = await previewDesign(designId, dimension)
      setPreview(result.image)
      setPreviewMs(result.render_ms)
    } catch (error) {
      setErrors({
        detail: error instanceof ApiError ? error.message : 'Could not render a preview.',
      })
    } finally {
      setBusy(false)
    }
  }

  async function runExport() {
    if (exportDims.length === 0) return
    setBusy(true)
    setErrors({})
    setMessage(null)
    try {
      const result = await exportDesign(designId, exportDims, exportFormat)
      setDesign(await fetchDesign(designId))
      setCompliance(result.compliance)
      setMessage(`Exported ${exportDims.length} image${exportDims.length === 1 ? '' : 's'}.`)
    } catch (error) {
      // A 409 means compliance stopped it. The report comes back in the error
      // body, so the agent is told which rule and why rather than just "no".
      if (error instanceof ApiError && error.status === 409) {
        const data = error.data as { compliance?: ComplianceReport } | null
        if (data?.compliance) setCompliance(data.compliance)
        setErrors({
          detail:
            'This design does not meet the compliance rules yet — see the flags below.',
        })
      } else {
        setErrors({
          detail: error instanceof ApiError ? error.message : 'Could not export this design.',
        })
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleRename() {
    const name = window.prompt('Design name', design?.name ?? '')
    if (!name) return
    setDesign(await renameDesign(designId, name))
  }

  async function handleDuplicate() {
    const copy = await duplicateDesign(designId)
    void navigate(`/designs/${copy.id}`)
  }

  async function handleDelete() {
    if (!window.confirm('Delete this design? Its exports go with it.')) return
    await deleteDesign(designId)
    void navigate('/designs', { replace: true })
  }

  if (loadError) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold tracking-tight">Design</h1>
        <Alert kind="error">{loadError}</Alert>
      </div>
    )
  }

  if (!design || !template || !resolved) {
    return <p className="text-sm text-slate-500">Loading…</p>
  }

  const editableByKey = new Map(
    template.elements.map((element) => [element.key, element.editable_fields]),
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start gap-3">
        <div className="mr-auto min-w-0">
          <h1 className="truncate text-xl font-semibold tracking-tight">{design.name}</h1>
          <p className="mt-1 text-sm text-slate-500">
            {design.template_detail.name}
            {design.listing_address && ` · ${design.listing_address}`}
          </p>
        </div>
        <div className="flex gap-2">
          <SecondaryButton onClick={() => void handleRename()}>Rename</SecondaryButton>
          <SecondaryButton onClick={() => void handleDuplicate()}>Duplicate</SecondaryButton>
          <SecondaryButton onClick={() => void handleDelete()} danger>
            Delete
          </SecondaryButton>
        </div>
      </div>

      {message && <Alert kind="success">{message}</Alert>}
      {errors.detail && <Alert kind="error">{errors.detail}</Alert>}
      {Object.keys(errors).some((key) => key !== 'detail') && (
        <Alert kind="error">
          Some changes were rejected. See the highlighted elements below.
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        {/* Controls */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy || !dirty}
              onClick={() => void save()}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-50"
            >
              {busy ? 'Working…' : dirty ? 'Save changes' : 'Saved'}
            </button>
            <SecondaryButton onClick={() => void runPreview()}>
              Update preview
            </SecondaryButton>
          </div>

          <ul className="space-y-3">
            {resolved.elements.map((element) => (
              <ElementControls
                key={element.key}
                element={element}
                editableFields={editableByKey.get(element.key) ?? []}
                override={overrides[element.key] ?? {}}
                onChange={(field, value) => changeField(element.key, field, value)}
                onClear={() => clearElement(element.key)}
                error={errors[element.key]}
              />
            ))}
          </ul>
        </div>

        {/* Preview and export */}
        <div className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          <Card title="Preview">
            <div className="flex flex-wrap gap-1">
              {dimensions.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => setDimension(option.key)}
                  className={`rounded-md px-2 py-1 text-xs font-medium transition ${
                    dimension === option.key
                      ? 'bg-slate-900 text-white'
                      : 'text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>

            <div className="flex min-h-48 items-center justify-center rounded-md border border-slate-200 bg-slate-50 p-2">
              {preview ? (
                <img src={preview} alt="Design preview" className="max-h-96 w-auto" />
              ) : (
                <p className="p-6 text-center text-xs text-slate-500">
                  Select “Update preview” to render this design.
                </p>
              )}
            </div>
            {previewMs !== null && (
              <p className="text-[11px] text-slate-400">Rendered in {previewMs} ms</p>
            )}
          </Card>

          <Card
            title="Compliance"
            description="Checked against the current rule set before export."
          >
            <CompliancePanel report={compliance} loading={checkingCompliance} />
          </Card>

          <Card title="Export" description="One design, every platform size.">
            <div className="space-y-1.5">
              {dimensions.map((option) => (
                <label key={option.key} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={exportDims.includes(option.key)}
                    onChange={(event) =>
                      setExportDims((current) =>
                        event.target.checked
                          ? [...current, option.key]
                          : current.filter((key) => key !== option.key),
                      )
                    }
                    className="accent-slate-900"
                  />
                  <span>{option.label}</span>
                  <span className="ml-auto text-xs text-slate-400">
                    {option.width}×{option.height}
                  </span>
                </label>
              ))}
            </div>

            <div className="flex items-center gap-2">
              {(['png', 'jpg'] as const).map((format) => (
                <button
                  key={format}
                  type="button"
                  onClick={() => setExportFormat(format)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium uppercase transition ${
                    exportFormat === format
                      ? 'bg-slate-900 text-white'
                      : 'text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  {format}
                </button>
              ))}
              <button
                type="button"
                disabled={busy || exportDims.length === 0}
                onClick={() => void runExport()}
                className="ml-auto rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:opacity-50"
              >
                Export
              </button>
            </div>
          </Card>

          {design.exports.length > 0 && (
            <Card title={`Exports (${design.exports.length})`}>
              <ul className="space-y-2 text-sm">
                {design.exports.map((item) => (
                  <li key={item.id} className="flex items-center gap-2">
                    {item.image_url && (
                      <img
                        src={item.image_url}
                        alt=""
                        className="size-9 rounded border border-slate-200 object-cover"
                      />
                    )}
                    <span className="min-w-0 flex-1 truncate">
                      {item.dimension_label}
                      <span className="ml-1 text-xs uppercase text-slate-400">
                        {item.export_format}
                      </span>
                    </span>
                    {item.image_url && (
                      <a
                        href={item.image_url}
                        download
                        className="shrink-0 text-xs font-medium text-slate-600 underline underline-offset-2 hover:text-slate-900"
                      >
                        Download
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function SecondaryButton({
  children,
  onClick,
  danger,
}: {
  children: React.ReactNode
  onClick: () => void
  danger?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border px-3 py-2 text-sm font-medium transition ${
        danger
          ? 'border-rose-200 text-rose-600 hover:bg-rose-50'
          : 'border-slate-300 text-slate-700 hover:bg-slate-50'
      }`}
    >
      {children}
    </button>
  )
}
