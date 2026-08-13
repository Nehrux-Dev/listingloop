import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  importListing,
  importListingFromHtml,
  type ListingImportResult,
} from '../api/listings.ts'
import { Alert, Card, TextField } from '../components/FormControls.tsx'
import { ApiError } from '../lib/apiClient.ts'

/**
 * One-off import: the agent pastes a URL, the server fetches that page once.
 *
 * The result is always an unverified draft. This page is deliberately explicit
 * about what was and was not read from the page, because the next step is the
 * agent checking it — and they can only check what they know is uncertain.
 *
 * WHEN THE SITE SAYS NO
 * ---------------------
 * Some portals serve a challenge page to anything that is not an interactive
 * browser. We do not pretend to be one. Instead the agent — who can open the
 * page perfectly well — pastes the source, and the same parser runs on it. The
 * paste box only appears once a site has actually refused us, so the common
 * case stays a single URL field.
 */
export default function ListingImportPage() {
  const navigate = useNavigate()
  const [url, setUrl] = useState('')
  const [result, setResult] = useState<ListingImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  const [blocked, setBlocked] = useState(false)
  const [html, setHtml] = useState('')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setImporting(true)
    setError(null)
    setResult(null)
    setBlocked(false)

    try {
      setResult(await importListing(url.trim()))
    } catch (err) {
      // 422 with blocked_by_site means retrying is pointless — the site has
      // declined. Offer the paste route rather than a dead end.
      if (err instanceof ApiError && err.status === 422) {
        const data = err.data as { blocked_by_site?: boolean } | null
        if (data?.blocked_by_site) {
          setBlocked(true)
          setError(err.message)
          return
        }
      }
      setError(
        err instanceof ApiError
          ? err.message
          : 'The import could not be completed. You can still add the listing manually.',
      )
    } finally {
      setImporting(false)
    }
  }

  async function handlePaste(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setImporting(true)
    setError(null)

    try {
      setResult(await importListingFromHtml(html, url.trim()))
      setBlocked(false)
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : 'That page source could not be read.',
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

      {error && !blocked && (
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

      {blocked && !result && (
        <form onSubmit={(event) => void handlePaste(event)} className="space-y-4">
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-5">
            <h2 className="text-sm font-medium text-amber-900">
              This website does not allow automatic importing
            </h2>
            <p className="mt-1 text-sm text-amber-800">{error}</p>
            <ol className="mt-3 list-inside list-decimal space-y-1 text-sm text-amber-800">
              <li>
                Open{' '}
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="font-medium underline underline-offset-2"
                >
                  the listing page
                </a>{' '}
                in a new tab.
              </li>
              <li>
                Press <kbd className="rounded bg-white px-1 ring-1 ring-amber-300">Ctrl</kbd>
                +<kbd className="rounded bg-white px-1 ring-1 ring-amber-300">U</kbd> to
                view the page source.
              </li>
              <li>
                Select all (<kbd className="rounded bg-white px-1 ring-1 ring-amber-300">Ctrl</kbd>
                +<kbd className="rounded bg-white px-1 ring-1 ring-amber-300">A</kbd>), copy,
                and paste it below.
              </li>
            </ol>

            <label className="mt-4 block">
              <span className="block text-sm font-medium text-amber-900">Page source</span>
              <textarea
                rows={8}
                value={html}
                onChange={(event) => setHtml(event.target.value)}
                placeholder="<!DOCTYPE html> …"
                spellCheck={false}
                className="mt-1 w-full rounded-md border border-amber-300 bg-white px-3 py-2 font-mono text-xs outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500"
              />
            </label>

            <p className="mt-1 text-xs text-amber-700">
              Photos are not downloaded on this route — upload them on the draft.
              Everything else is read exactly as it would be from a URL, and
              still nothing is guessed.
            </p>

            <button
              type="submit"
              disabled={importing || html.trim() === ''}
              className="mt-3 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {importing ? 'Reading…' : 'Import from pasted source'}
            </button>
          </div>
        </form>
      )}

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
