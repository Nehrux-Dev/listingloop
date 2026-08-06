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
  fetchContentLanguages,
  fetchContentStatus,
  requestGeneration,
  reviewAllVariants,
  type ContentLanguage,
  type ContentVariant,
  type GeneratedContent,
} from '../api/aiContent.ts'
import { ApiError } from '../lib/apiClient.ts'
import { Alert, Card } from './FormControls.tsx'
import { VariantCard } from './VariantCard.tsx'

const POLL_INTERVAL_MS = 2000
const POLL_TIMEOUT_MS = 120000

const VALIDATION_BADGE: Record<string, string> = {
  passed: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  flagged: 'bg-amber-50 text-amber-700 ring-amber-200',
  rejected: 'bg-rose-50 text-rose-700 ring-rose-200',
  pending: 'bg-slate-100 text-slate-600 ring-slate-200',
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
  const [available, setAvailable] = useState<ContentLanguage[]>([])
  const [languages, setLanguages] = useState<string[]>(['en'])

  useEffect(() => {
    // Reading the language list does not start anything.
    fetchContentLanguages().then(setAvailable).catch(() => setAvailable([]))
  }, [])

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
      const queued = await requestGeneration(listingId, {
        tone: tone.trim() || undefined,
        languages,
      })
      setItems((current) => [...queued, ...current])
      // One job per language; poll the first and refresh the rest when it
      // lands, rather than running several timers against the same endpoint.
      if (queued[0]) {
        setPollingId(queued[0].id)
        poll(queued[0].id, Date.now())
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start generation.')
    } finally {
      setBusy(false)
    }
  }

  function handleVariantChanged(generationId: number, updated: ContentVariant) {
    setItems((current) =>
      current.map((item) =>
        item.id === generationId
          ? {
              ...item,
              variants: item.variants.map((variant) =>
                variant.id === updated.id ? updated : variant,
              ),
              usable_variant_count: item.variants.filter((variant) =>
                variant.id === updated.id ? updated.is_usable : variant.is_usable,
              ).length,
            }
          : item,
      ),
    )
  }

  async function handleReviewAll(id: number, decision: 'approved' | 'rejected') {
    try {
      const result = await reviewAllVariants(id, decision)
      setItems((current) =>
        current.map((item) => (item.id === id ? result.generation : item)),
      )
      if (result.skipped > 0) {
        setError(
          `${result.applied} approved. ${result.skipped} skipped — those failed the ` +
            `fact check and need editing or regenerating.`,
        )
      }
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

        {available.length > 1 && (
          <LanguagePicker
            available={available}
            selected={languages}
            onChange={setLanguages}
          />
        )}

        <button
          type="button"
          disabled={busy || pollingId !== null || languages.length === 0}
          onClick={() => void handleGenerate()}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-50"
        >
          {pollingId !== null
            ? 'Generating…'
            : busy
              ? 'Starting…'
              : `${hasAny ? 'Regenerate' : 'Generate'}${
                  languages.length > 1 ? ` in ${languages.length} languages` : ''
                }`}
        </button>
        {pollingId !== null && (
          <p className="text-xs text-slate-500">
            Running in the background — this page will update when it finishes.
          </p>
        )}
      </div>

      {items.map((item) => (
        <GenerationCard
          key={item.id}
          item={item}
          onVariantChanged={(variant) => handleVariantChanged(item.id, variant)}
          onReviewAll={(decision) => void handleReviewAll(item.id, decision)}
        />
      ))}
    </Card>
  )
}

/**
 * Language selector.
 *
 * Languages whose fact check is only partial say so *here*, before the agent
 * commits, rather than in a warning after the copy arrives. Choosing to
 * publish in a language the system cannot fully verify is a legitimate
 * decision — making it uninformed is not.
 */
function LanguagePicker({
  available,
  selected,
  onChange,
}: {
  available: ContentLanguage[]
  selected: string[]
  onChange: (codes: string[]) => void
}) {
  const partial = available.filter(
    (language) => selected.includes(language.code) && !language.fully_validated,
  )

  function toggle(code: string) {
    onChange(
      selected.includes(code)
        ? selected.filter((item) => item !== code)
        : [...selected, code],
    )
  }

  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-slate-600">Languages</p>
      <div className="flex flex-wrap gap-1.5">
        {available.map((language) => {
          const active = selected.includes(language.code)
          return (
            <button
              key={language.code}
              type="button"
              onClick={() => toggle(language.code)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                active
                  ? 'bg-slate-900 text-white'
                  : 'border border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}
            >
              {language.name}
              {!language.fully_validated && (
                <span
                  title="The automatic fact check only partly understands this language"
                  className={active ? 'ml-1 text-amber-300' : 'ml-1 text-amber-600'}
                >
                  ●
                </span>
              )}
            </button>
          )
        })}
      </div>

      {partial.length > 0 && (
        <p className="text-[11px] text-amber-700">
          Numbers and prices are checked in every language. For{' '}
          {partial.map((language) => language.name).join(', ')}, the claim and
          feature checks do not run — read that copy through before approving it.
        </p>
      )}

      <p className="text-[11px] text-slate-400">
        Each language is a separate request and is billed separately.
      </p>
    </div>
  )
}

function GenerationCard({
  item,
  onVariantChanged,
  onReviewAll,
}: {
  item: GeneratedContent
  onVariantChanged: (variant: ContentVariant) => void
  onReviewAll: (decision: 'approved' | 'rejected') => void
}) {
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

  const usable = item.usable_variant_count
  const total = item.variants.length

  return (
    <div className="space-y-3 rounded-md border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${
            VALIDATION_BADGE[item.validation_status]
          }`}
        >
          {usable} of {total} ready to use
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
          {item.language_name}
        </span>
        {item.has_partial_validation && (
          <span
            title="Claim and feature checks do not run in this language"
            className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-amber-200"
          >
            Partly checked
          </span>
        )}
        <span className="text-[11px] text-slate-400">
          {new Date(item.created_at).toLocaleString()}
        </span>
        <span className="ml-auto text-[11px] text-slate-400">
          {item.model_name} · {item.total_tokens} tokens · ${item.estimated_cost_usd}
        </span>
      </div>

      {/* One call produced all of these — the cost above covers the whole pack. */}
      <div className="space-y-2">
        {item.variants.map((variant) => (
          <VariantCard key={variant.id} variant={variant} onChanged={onVariantChanged} />
        ))}
      </div>

      {item.variants.some((variant) => variant.review_status === 'draft') && (
        <div className="flex gap-2 border-t border-slate-100 pt-2">
          <button
            type="button"
            onClick={() => onReviewAll('approved')}
            className="rounded-md border border-emerald-300 px-3 py-1.5 text-xs font-medium text-emerald-700 transition hover:bg-emerald-50"
          >
            Approve all that passed
          </button>
          <button
            type="button"
            onClick={() => onReviewAll('rejected')}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
          >
            Discard all
          </button>
        </div>
      )}
    </div>
  )
}
