/** Small shared form primitives, so the three forms stay readable. */

import { useId, useState, type ReactNode } from 'react'

import { ApiError } from '../lib/apiClient.ts'

const inputClass =
  'mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-slate-900 focus:ring-1 focus:ring-slate-900 disabled:bg-slate-50 disabled:text-slate-400'

/**
 * Turn a DRF error body into `{field: message}`.
 *
 * DRF returns `{"photo": ["File is too large (6.0 MB)..."]}` for field errors
 * and `{"detail": "..."}` for everything else, so the upload and permission
 * messages the server produces are shown verbatim next to the field that
 * caused them rather than replaced with a generic "something went wrong".
 */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !error.data || typeof error.data !== 'object') {
    return {}
  }

  const result: Record<string, string> = {}
  for (const [key, value] of Object.entries(error.data as Record<string, unknown>)) {
    if (typeof value === 'string') result[key] = value
    else if (Array.isArray(value) && typeof value[0] === 'string') result[key] = value[0]
  }
  return result
}

type FieldProps = {
  label: string
  error?: string
  hint?: string
  children: (id: string) => ReactNode
}

export function Field({ label, error, hint, children }: FieldProps) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-700">
        {label}
      </label>
      {children(id)}
      {hint && !error && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      {error && (
        <p role="alert" className="mt-1 text-xs text-rose-600">
          {error}
        </p>
      )}
    </div>
  )
}

type TextFieldProps = {
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
  hint?: string
  type?: string
  disabled?: boolean
  placeholder?: string
  maxLength?: number
}

export function TextField({
  label,
  value,
  onChange,
  error,
  hint,
  type = 'text',
  disabled,
  placeholder,
  maxLength,
}: TextFieldProps) {
  return (
    <Field label={label} error={error} hint={hint}>
      {(id) => (
        <input
          id={id}
          type={type}
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          maxLength={maxLength}
          onChange={(event) => onChange(event.target.value)}
          className={inputClass}
        />
      )}
    </Field>
  )
}

export function TextAreaField({
  label,
  value,
  onChange,
  error,
  hint,
  rows = 4,
  disabled,
}: Omit<TextFieldProps, 'type' | 'maxLength'> & { rows?: number }) {
  return (
    <Field label={label} error={error} hint={hint}>
      {(id) => (
        <textarea
          id={id}
          rows={rows}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          className={inputClass}
        />
      )}
    </Field>
  )
}

export function SelectField<T extends string>({
  label,
  value,
  options,
  onChange,
  error,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
  error?: string
}) {
  return (
    <Field label={label} error={error}>
      {(id) => (
        <select
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value as T)}
          className={inputClass}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  )
}

/** Colour picker paired with a hex text input, kept in sync. */
export function ColorField({
  label,
  value,
  onChange,
  error,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
}) {
  return (
    <Field label={label} error={error}>
      {(id) => (
        <div className="mt-1 flex items-center gap-2">
          <input
            id={id}
            type="color"
            // <input type="color"> only accepts 6-digit hex; fall back so a
            // half-typed value in the text box does not crash it.
            value={/^#[0-9a-fA-F]{6}$/.test(value) ? value : '#000000'}
            onChange={(event) => onChange(event.target.value.toUpperCase())}
            className="size-9 shrink-0 cursor-pointer rounded-md border border-slate-300 bg-white p-1"
          />
          <input
            type="text"
            value={value}
            spellCheck={false}
            onChange={(event) => onChange(event.target.value.toUpperCase())}
            className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm uppercase outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
          />
        </div>
      )}
    </Field>
  )
}

/**
 * Image picker with a live preview.
 *
 * Client-side size and type checks here are a courtesy — they save a round
 * trip and give instant feedback. The server validates every upload
 * independently (apps/core/validators.py); nothing here is trusted.
 */
export function ImageField({
  label,
  currentUrl,
  onSelect,
  error,
  maxMb = 5,
  accept = 'image/png,image/jpeg,image/webp',
}: {
  label: string
  currentUrl: string | null
  onSelect: (file: File | null) => void
  error?: string
  maxMb?: number
  accept?: string
}) {
  const [preview, setPreview] = useState<string | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)

  function handleChange(file: File | null) {
    setLocalError(null)

    if (!file) {
      setPreview(null)
      onSelect(null)
      return
    }

    if (file.size > maxMb * 1024 * 1024) {
      setLocalError(`That file is ${(file.size / 1024 / 1024).toFixed(1)} MB. The limit is ${maxMb} MB.`)
      onSelect(null)
      return
    }
    if (!accept.split(',').includes(file.type)) {
      setLocalError('Please choose a PNG, JPEG or WebP image.')
      onSelect(null)
      return
    }

    setPreview(URL.createObjectURL(file))
    onSelect(file)
  }

  const shown = preview ?? currentUrl

  return (
    <Field label={label} error={error ?? localError ?? undefined}>
      {(id) => (
        <div className="mt-1 flex items-center gap-4">
          <div className="flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-full border border-slate-200 bg-slate-100">
            {shown ? (
              <img src={shown} alt="" className="size-full object-cover" />
            ) : (
              <span className="text-xs text-slate-400">None</span>
            )}
          </div>
          <input
            id={id}
            type="file"
            accept={accept}
            onChange={(event) => handleChange(event.target.files?.[0] ?? null)}
            className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-800"
          />
        </div>
      )}
    </Field>
  )
}

export function Alert({ kind, children }: { kind: 'error' | 'success'; children: ReactNode }) {
  const styles =
    kind === 'error'
      ? 'border-rose-200 bg-rose-50 text-rose-700'
      : 'border-emerald-200 bg-emerald-50 text-emerald-700'
  return (
    <div role="alert" className={`rounded-md border px-3 py-2 text-sm ${styles}`}>
      {children}
    </div>
  )
}

export function SubmitButton({
  saving,
  children = 'Save changes',
}: {
  saving: boolean
  children?: ReactNode
}) {
  return (
    <button
      type="submit"
      disabled={saving}
      className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {saving ? 'Saving…' : children}
    </button>
  )
}

export function Card({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
      {description && <p className="mt-1 text-xs text-slate-500">{description}</p>}
      <div className="mt-5 space-y-4">{children}</div>
    </section>
  )
}
