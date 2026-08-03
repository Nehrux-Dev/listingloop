import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { importListing, type ListingImportResult } from '../api/listings.ts'
import { Alert, Card, TextField } from '../components/FormControls.tsx'
import { ApiError } from '../lib/apiClient.ts'

/**
 * One-off import: the agent pastes a URL, the server fetches that page once.
 *
 * The result is always an unverified draft. This page is deliberately explicit
 * about what was and was not read from the page, because the next step is the
 * agent checking it — and they can only check what they know is uncertain.
 */
export default function ListingImportPage() {
  const navigate = useNavigate()
  const [url, setUrl] = useState('')
  const [result, setResult] = useState<ListingImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setImporting(true)
    setError(null)
    setResult(null)

    try {
      setResult(await importListing(url.trim()))
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : 'The import could not be completed. You can still add the listing manually.',
      )
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Import a listing</h1>
        <p className="mt-1 text-sm text-slate-500">
          Paste the URL of a public listing page. We fetch it once and pre-fill what
          we can read — nothing is guessed, and nothing is verified until you say so.
        </p>
      </div>

      {error && (
        <Alert kind="error">
          {error} You can{' '}
          <button
            type="button"
            onClick={() => void navigate('/listings/new')}
            className="underline underline-offset-2"
          >
            enter it manually
          </button>{' '}
          instead.
        </Alert>
      )}

      <form onSubmit={(event) => void handleSubmit(event)} className="space-y-6">
        <Card title="Listing URL">
          <TextField
            label="URL"
            type="url"
            value={url}
            onChange={setUrl}
            placeholder="https://"
            hint="Public http:// or https:// pages only."
          />
          <button
            type="submit"
            disabled={importing || url.trim() === ''}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {importing ? 'Fetching…' : 'Import'}
          </button>
        </Card>
      </form>

      {result && (
        <Card
          title="Draft created"
          description="Review every field before verifying — the source page is not authoritative."
        >
          <div className="rounded-md border border-slate-200 p-3 text-sm">
            <p className="font-medium text-slate-800">
              {result.listing.full_address || 'No address could be read'}
            </p>
            <p className="mt-1 text-slate-500">
              {result.photo_count} photo{result.photo_count === 1 ? '' : 's'} imported
            </p>
          </div>

          {result.extracted_fields.length > 0 ? (
            <div>
              <p className="text-xs font-medium text-slate-700">Read from the page</p>
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {result.extracted_fields.map((field) => (
                  <li
                    key={field}
                    className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700 ring-1 ring-emerald-200"
                  >
                    {field.replace(/_/g, ' ')}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-slate-600">
              Nothing could be read from that page automatically. The draft is empty —
              please fill it in by hand.
            </p>
          )}

          {result.warnings.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
              <p className="text-xs font-medium text-amber-800">
                Left blank rather than guessed
              </p>
              <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs text-amber-700">
                {result.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </div>
          )}

          <button
            type="button"
            onClick={() => void navigate(`/listings/${result.listing.id}`)}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            Review and complete the draft
          </button>
        </Card>
      )}
    </div>
  )
}
