/**
 * AI caption panel for a listing.
 *
 * GENERATION ONLY EVER HAPPENS ON A CLICK.
 * The effect below fetches *existing* content when the panel mounts. It does
 * not generate. `requestGeneration` is called from exactly one place — the
 * button handler — because an expensive external call that fires on render is
 * a bill that grows with page views, and a re-render loop away from a very
 * large one.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  fetchContent,
  fetchContentForListing,
  fetchContentStatus,
  requestGeneration,
  reviewContent,
  type GeneratedContent,
} from '../api/aiContent.ts'
import { ApiError } from '../lib/apiClient.ts'
import { Alert, Card } from './FormControls.tsx'

const POLL_INTERVAL_MS = 2000
const POLL_TIMEOUT_MS = 120000

const VALIDATION_BADGE: Record<string, string> = {
  passed: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  flagged: 'bg-amber-50 text-amber-700 ring-amber-200',
  rejected: 'bg-rose-50 text-rose-700 ring-rose-200',
  pending: 'bg-slate-100 text-slate-600 ring-slate-200',
}

const VALIDATION_LABEL: Record<string, string> = {
  passed: 'Fact check passed',
  flagged: 'Passed with warnings',
  rejected: 'Rejected — unverifiable claims',
  pending: 'Not checked',
}

export function AiContentPanel({
  listingId,
  isVerified,
}: {
  listingId: number
  isVerified: boolean
}) {
  const [items, setItems] = useState<GeneratedContent[]>([])
  const [tone, setTone] = useState('')
  const [busy, setBusy] = useState(false)
  const [pollingId, setPollingId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timers = useRef<number[]>([])

  const load = useCallback(async () => {
    // Reads existing records only. Nothing here starts a job.
    const page = await fetchContentForListing(listingId)
    setItems(page.results)
  }, [listingId])

  useEffect(() => {
    void load().catch(() => setItems([]))
  }, [load])

  // Clear any outstanding poll timers if the panel unmounts mid-job.
  useEffect(
    () => () => {
      timers.current.forEach((handle) => window.clearTimeout(handle))
      timers.current = []
    },
    [],
  )

  const poll = useCallback(
    (id: number, startedAt: number) => {
      const handle = window.setTimeout(async () => {
        try {
          const status = await fetchContentStatus(id)
          if (status.job_status === 'ready' || status.job_status === 'failed') {
            const full = await fetchContent(id)
            setItems((current) => [full, ...current.filter((item) => item.id !== id)])
            setPollingId(null)
            if (status.job_status === 'failed') {
              setError(status.error_message || 'Generation failed.')
            }
            return
          }
          if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
            setPollingId(null)
            setError('This is taking longer than expected. Refresh to check again.')
            return
          }
          poll(id, startedAt)
        } catch {
          setPollingId(null)
          setError('Lost contact with the server while waiting for the result.')
        }
      }, POLL_INTERVAL_MS)
      timers.current.push(handle)
    },
    [],
  )

  async function handleGenerate() {
    setBusy(true)
    setError(null)
    try {
      const queued = await requestGeneration(listingId, tone.trim() || undefined)
      setItems((current) => [queued, ...current])
      setPollingId(queued.id)
      poll(queued.id, Date.now())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start generation.')
    } finally {
      setBusy(false)
    }
  }

  async function handleReview(id: number, decision: 'approved' | 'rejected') {
    try {
      const updated = await reviewContent(id, decision)
      setItems((current) => current.map((item) => (item.id === id ? updated : item)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not record that decision.')
    }
  }

  if (!isVerified) {
    return (
      <Card title="AI caption">
        <p className="text-sm text-slate-500">
          Verify this listing first. Copy is only generated from facts an agent has
          confirmed.
        </p>
      </Card>
    )
  }

  const hasAny = items.length > 0

  return (
    <Card
      title="AI caption"
      description="Written only from the verified fields below, then fact-checked against them."
    >
      {error && <Alert kind="error">{error}</Alert>}

      <div className="space-y-2">
        <input
          type="text"
          value={tone}
          maxLength={200}
          placeholder="Optional tone note, e.g. “calm and understated”"
          onChange={(event) => setTone(event.target.value)}
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
        />
        <button
          type="button"
          disabled={busy || pollingId !== null}
          onClick={() => void handleGenerate()}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-50"
        >
          {pollingId !== null
            ? 'Generating…'
            : busy
              ? 'Starting…'
              : hasAny
                ? 'Regenerate'
                : 'Generate caption'}
        </button>
        {pollingId !== null && (
          <p className="text-xs text-slate-500">
            Running in the background — this page will update when it finishes.
          </p>
        )}
      </div>

      {items.map((item) => (
        <GenerationCard key={item.id} item={item} onReview={handleReview} />
      ))}
    </Card>
  )
}

function GenerationCard({
  item,
  onReview,
}: {
  item: GeneratedContent
  onReview: (id: number, decision: 'approved' | 'rejected') => void
}) {
  const rejected = item.validation_status === 'rejected'
  const caption = item.caption || item.rejected_output?.caption || ''
  const hashtags = item.hashtags.length > 0 ? item.hashtags : (item.rejected_output?.hashtags ?? [])

  if (item.job_status === 'queued' || item.job_status === 'running') {
    return (
      <div className="rounded-md border border-slate-200 p-3 text-sm text-slate-500">
        Queued…
      </div>
    )
  }

  if (item.job_status === 'failed') {
    return (
      <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
        Generation failed: {item.error_message || 'unknown error'}
      </div>
    )
  }

  return (
    <div className="space-y-2 rounded-md border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${
            VALIDATION_BADGE[item.validation_status]
          }`}
        >
          {VALIDATION_LABEL[item.validation_status]}
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
          {item.review_status}
        </span>
        <span className="ml-auto text-[11px] text-slate-400">
          {item.model_name} · {item.total_tokens} tokens · ${item.estimated_cost_usd}
        </span>
      </div>

      {rejected && (
        <p className="rounded-md bg-rose-50 px-2 py-1 text-xs text-rose-700">
          This copy was not stored as usable. It is shown so you can see what went
          wrong — do not publish it.
        </p>
      )}

      <p className={`text-sm ${rejected ? 'text-slate-400 line-through' : 'text-slate-800'}`}>
        {caption || '(no caption)'}
      </p>

      {hashtags.length > 0 && (
        <p className={`text-xs ${rejected ? 'text-slate-400' : 'text-slate-500'}`}>
          {hashtags.join(' ')}
        </p>
      )}

      {item.validation_issues.length > 0 && (
        <ul className="space-y-1">
          {item.validation_issues.map((issue, index) => (
            <li
              key={index}
              className={`text-xs ${
                issue.severity === 'error' ? 'text-rose-700' : 'text-amber-700'
              }`}
            >
              <span className="font-medium uppercase">{issue.severity}</span> — {issue.message}
            </li>
          ))}
        </ul>
      )}

      {item.review_status === 'draft' && (
        <div className="flex gap-2">
          <button
            type="button"
            disabled={!item.is_usable}
            onClick={() => onReview(item.id, 'approved')}
            title={item.is_usable ? undefined : 'Content that failed the fact check cannot be approved'}
            className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={() => onReview(item.id, 'rejected')}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
          >
            Discard
          </button>
        </div>
      )}
    </div>
  )
}
