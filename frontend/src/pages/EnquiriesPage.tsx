import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { apiRequest } from '../lib/apiClient.ts'
import type { Paginated } from '../api/profiles.ts'
import { Alert } from '../components/FormControls.tsx'
import { ApiError } from '../lib/apiClient.ts'

type EnquiryStatus = 'new' | 'read' | 'replied' | 'archived' | 'spam'

type Enquiry = {
  id: number
  listing: number
  listing_address: string | null
  listing_slug: string | null
  name: string
  email: string
  phone: string
  message: string
  status: EnquiryStatus
  is_spam: boolean
  contact_summary: string
  spam_reasons: string[]
  read_at: string | null
  created_at: string
}

const STATUS_STYLE: Record<EnquiryStatus, string> = {
  new: 'bg-slate-900 text-white',
  read: 'bg-slate-100 text-slate-600',
  replied: 'bg-emerald-100 text-emerald-700',
  archived: 'bg-slate-100 text-slate-400',
  spam: 'bg-rose-100 text-rose-700',
}

export default function EnquiriesPage() {
  const [enquiries, setEnquiries] = useState<Enquiry[] | null>(null)
  const [summary, setSummary] = useState<{ total: number; new: number; spam: number } | null>(null)
  const [showSpam, setShowSpam] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const query = showSpam ? '?include_spam=true' : ''
      const [page, totals] = await Promise.all([
        apiRequest<Paginated<Enquiry>>(`/api/enquiries/${query}`),
        apiRequest<{ total: number; new: number; spam: number }>('/api/enquiries/summary/'),
      ])
      setEnquiries(page.results)
      setSummary(totals)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load enquiries.')
    }
  }, [showSpam])

  useEffect(() => {
    void load()
  }, [load])

  async function setStatus(id: number, status: EnquiryStatus) {
    await apiRequest(`/api/enquiries/${id}/status/`, { method: 'POST', body: { status } })
    await load()
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h1 className="text-xl font-semibold tracking-tight">Enquiries</h1>
          <p className="mt-1 text-sm text-slate-500">
            Messages sent through your public listing pages.
          </p>
        </div>
        {summary && (
          <div className="flex gap-4 text-sm">
            <span>
              <strong>{summary.new}</strong> new
            </span>
            <span className="text-slate-400">{summary.total} total</span>
            {summary.spam > 0 && (
              <span className="text-slate-400">{summary.spam} spam</span>
            )}
          </div>
        )}
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      <label className="flex items-center gap-2 text-sm text-slate-600">
        <input
          type="checkbox"
          checked={showSpam}
          onChange={(event) => setShowSpam(event.target.checked)}
          className="accent-slate-900"
        />
        Include messages flagged as spam
      </label>

      {!enquiries && !error && <p className="text-sm text-slate-500">Loading…</p>}

      {enquiries && enquiries.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">
          No enquiries yet. They arrive here when someone uses the form on a public
          listing page.
        </div>
      )}

      {enquiries && enquiries.length > 0 && (
        <ul className="space-y-3">
          {enquiries.map((enquiry) => (
            <li
              key={enquiry.id}
              className={`rounded-lg border bg-white p-4 shadow-sm ${
                enquiry.is_spam ? 'border-rose-200' : 'border-slate-200'
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-800">{enquiry.name}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
                    STATUS_STYLE[enquiry.status]
                  }`}
                >
                  {enquiry.status}
                </span>
                <span className="ml-auto text-xs text-slate-400">
                  {new Date(enquiry.created_at).toLocaleString()}
                </span>
              </div>

              <p className="mt-1 text-sm text-slate-500">{enquiry.contact_summary}</p>

              {enquiry.listing_address && (
                <p className="mt-0.5 text-xs text-slate-400">
                  About:{' '}
                  {enquiry.listing_slug ? (
                    <Link
                      to={`/p/${enquiry.listing_slug}`}
                      target="_blank"
                      className="underline underline-offset-2"
                    >
                      {enquiry.listing_address}
                    </Link>
                  ) : (
                    enquiry.listing_address
                  )}
                </p>
              )}

              <p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">
                {enquiry.message}
              </p>

              {enquiry.is_spam && enquiry.spam_reasons.length > 0 && (
                <div className="mt-3 rounded-md bg-rose-50 px-3 py-2">
                  <p className="text-xs font-medium text-rose-700">
                    Flagged as spam because:
                  </p>
                  <ul className="mt-1 list-inside list-disc text-xs text-rose-600">
                    {enquiry.spam_reasons.map((reason, index) => (
                      <li key={index}>{reason}</li>
                    ))}
                  </ul>
                  <p className="mt-1 text-[11px] text-rose-500">
                    If this is genuine, mark it as read — the message was kept, not
                    deleted.
                  </p>
                </div>
              )}

              <div className="mt-3 flex flex-wrap gap-2">
                {enquiry.email && (
                  <a
                    href={`mailto:${enquiry.email}?subject=${encodeURIComponent(
                      `Re: ${enquiry.listing_address ?? 'your enquiry'}`,
                    )}`}
                    className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-slate-800"
                  >
                    Reply by email
                  </a>
                )}
                {(['read', 'replied', 'archived', 'spam'] as EnquiryStatus[])
                  .filter((status) => status !== enquiry.status)
                  .map((status) => (
                    <button
                      key={status}
                      type="button"
                      onClick={() => void setStatus(enquiry.id, status)}
                      className="rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium capitalize text-slate-600 transition hover:bg-slate-50"
                    >
                      Mark {status}
                    </button>
                  ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
