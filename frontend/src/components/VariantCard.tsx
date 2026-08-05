/**
 * One content variant: read it, edit it, approve or discard it.
 *
 * Each variant is reviewed on its own because they fail independently — the
 * LinkedIn caption is where a model reaches for investment framing, while the
 * Instagram one is fine. Approving the pack wholesale would mean approving
 * copy nobody looked at.
 */

import { useState } from 'react'

import {
  editVariant,
  reviewVariant,
  type ContentVariant,
} from '../api/aiContent.ts'
import { ApiError } from '../lib/apiClient.ts'

const VALIDATION_STYLE: Record<string, string> = {
  passed: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  flagged: 'bg-amber-50 text-amber-700 ring-amber-200',
  rejected: 'bg-rose-50 text-rose-700 ring-rose-200',
  pending: 'bg-slate-100 text-slate-600 ring-slate-200',
}

const VALIDATION_LABEL: Record<string, string> = {
  passed: 'Checked',
  flagged: 'Check warnings',
  rejected: 'Failed fact check',
  pending: 'Not checked',
}

const REVIEW_STYLE: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-600',
  approved: 'bg-emerald-600 text-white',
  rejected: 'bg-slate-200 text-slate-500',
}

export function VariantCard({
  variant,
  onChanged,
}: {
  variant: ContentVariant
  onChanged: (updated: ContentVariant) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draftText, setDraftText] = useState(variant.text || variant.rejected_text)
  const [draftTags, setDraftTags] = useState(
    (variant.items.length > 0 ? variant.items : variant.rejected_items).join(' '),
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isHashtags = variant.kind === 'hashtags'
  const rejected = variant.validation_status === 'rejected'

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const payload = isHashtags
        ? {
            items: draftTags
              .split(/[\s,]+/)
              .map((tag) => tag.trim())
              .filter(Boolean)
              .map((tag) => (tag.startsWith('#') ? tag : `#${tag}`)),
          }
        : { text: draftText }
      onChanged(await editVariant(variant.id, payload))
      setEditing(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save that edit.')
    } finally {
      setBusy(false)
    }
  }

  async function decide(decision: 'approved' | 'rejected') {
    setBusy(true)
    setError(null)
    try {
      onChanged(await reviewVariant(variant.id, decision))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not record that decision.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2 rounded-md border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-800">{variant.kind_display}</span>
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${
            VALIDATION_STYLE[variant.validation_status]
          }`}
        >
          {VALIDATION_LABEL[variant.validation_status]}
        </span>
        {variant.is_edited && (
          <span className="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700 ring-1 ring-sky-200">
            Edited by you
          </span>
        )}
        <span
          className={`ml-auto rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${
            REVIEW_STYLE[variant.review_status]
          }`}
        >
          {variant.review_status}
        </span>
      </div>

      {error && <p className="text-xs text-rose-700">{error}</p>}

      {rejected && !variant.is_edited && (
        <p className="rounded-md bg-rose-50 px-2 py-1 text-xs text-rose-700">
          Not stored as usable. Shown so you can see what went wrong — edit it or
          regenerate, but do not publish it as it stands.
        </p>
      )}

      {editing ? (
        <div className="space-y-2">
          {isHashtags ? (
            <input
              type="text"
              value={draftTags}
              onChange={(event) => setDraftTags(event.target.value)}
              placeholder="#Manly #oceanviews"
              className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
            />
          ) : (
            <textarea
              rows={variant.kind === 'property_description' ? 7 : 3}
              value={draftText}
              onChange={(event) => setDraftText(event.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
            />
          )}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void save()}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-slate-800 disabled:opacity-50"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p
          className={`whitespace-pre-wrap text-sm ${
            rejected && !variant.is_edited ? 'text-slate-400' : 'text-slate-800'
          } ${isHashtags ? 'font-mono text-xs' : ''}`}
        >
          {variant.display_text || '(empty)'}
        </p>
      )}

      {variant.validation_issues.length > 0 && (
        <ul className="space-y-0.5">
          {variant.validation_issues.map((issue, index) => (
            <li
              key={index}
              className={`text-[11px] ${
                issue.severity === 'error' ? 'text-rose-700' : 'text-amber-700'
              }`}
            >
              {issue.message}
            </li>
          ))}
        </ul>
      )}

      {variant.is_edited && variant.error_count > 0 && (
        <p className="text-[11px] text-slate-500">
          These are your words now, so this is advice rather than a block — you can
          still approve it.
        </p>
      )}

      {!editing && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setDraftText(variant.text || variant.rejected_text)
              setDraftTags(
                (variant.items.length > 0 ? variant.items : variant.rejected_items).join(' '),
              )
              setEditing(true)
            }}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50"
          >
            Edit
          </button>

          {variant.display_text && (
            <button
              type="button"
              onClick={() => void navigator.clipboard?.writeText(variant.display_text)}
              disabled={!variant.is_usable}
              title={variant.is_usable ? undefined : 'Failed the fact check'}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-40"
            >
              Copy
            </button>
          )}

          {variant.review_status === 'draft' && (
            <>
              <button
                type="button"
                disabled={busy || !variant.is_usable}
                onClick={() => void decide('approved')}
                title={variant.is_usable ? undefined : 'Failed the fact check — edit it first'}
                className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Approve
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void decide('rejected')}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
              >
                Discard
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
