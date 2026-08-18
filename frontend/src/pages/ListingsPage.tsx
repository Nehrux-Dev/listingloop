/**
 * The agent's properties — and, when they arrived here from a design, the
 * place they choose which one that design is about.
 *
 * TWO MODES, ONE SCREEN
 * ---------------------------------------------------------------------------
 * Reached from the rail, this is a plain list. Reached from the editor's
 * "Import listing" button, the URL carries `?for=<design id>` and every row
 * grows an "Apply to design" button that attaches the property and returns to
 * the editor.
 *
 * It is the same screen in both cases on purpose. The agent who needs a
 * property for a design frequently does not have one yet — so they need the
 * import-from-URL and new-listing buttons that already live here, and a
 * separate picker dialog would have to grow its own copies of both.
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { fetchListings, type Listing } from '../api/listings.ts'
import { attachListingToDesign, fetchDesign, type Design } from '../api/templates.ts'
import { Alert } from '../components/FormControls.tsx'
import { VerificationBadge } from '../components/VerificationBadge.tsx'
import { ApiError } from '../lib/apiClient.ts'
import { designEditorPath, designIdFromParams, FOR_DESIGN_PARAM } from '../lib/routes.ts'

function formatPrice(price: string | null): string {
  if (!price) return '—'
  const value = Number(price)
  return Number.isFinite(value)
    ? value.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
    : price
}

export default function ListingsPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const forDesign = designIdFromParams(params)

  const [listings, setListings] = useState<Listing[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'verified' | 'unverified'>('all')

  /** The design being filled in, once its name is known — the banner says
   *  which design is waiting rather than just that one is. */
  const [design, setDesign] = useState<Design | null>(null)
  const [applying, setApplying] = useState<number | null>(null)

  useEffect(() => {
    const params = filter === 'all' ? undefined : { verification_status: filter }
    fetchListings(params)
      .then((page) => setListings(page.results))
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : 'Could not load listings.'),
      )
  }, [filter])

  useEffect(() => {
    if (forDesign === null) {
      setDesign(null)
      return
    }
    // A design that cannot be read is a stale link — most likely the design
    // was deleted in another tab. The list still works; it just stops
    // claiming to be filling anything in.
    fetchDesign(forDesign).then(setDesign).catch(() => setDesign(null))
  }, [forDesign])

  async function applyTo(listing: Listing) {
    if (forDesign === null || applying !== null) return
    setApplying(listing.id)
    setError(null)
    try {
      await attachListingToDesign(forDesign, listing.id)
      // Straight back to the canvas. The editor re-reads the design on mount,
      // so the price, the address and the photos are already in place by the
      // time it paints — nothing here has to tell it what changed.
      void navigate(designEditorPath(forDesign), { replace: true })
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : 'That property could not be applied to the design.',
      )
      setApplying(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h1 className="text-xl font-semibold tracking-tight">Listings</h1>
          <p className="mt-1 text-sm text-slate-500">
            Only verified listings can be used to generate marketing material.
          </p>
        </div>
        <Link
          to={forDesign === null ? '/listings/import' : `/listings/import?${FOR_DESIGN_PARAM}=${forDesign}`}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          Import from URL
        </Link>
        <Link
          to={forDesign === null ? '/listings/new' : `/listings/new?${FOR_DESIGN_PARAM}=${forDesign}`}
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
        >
          New listing
        </Link>
      </div>

      {/* The reason they are on this screen, kept in front of them: the trip
          here has three possible detours (import, create, verify) and it is
          easy to forget there is a design waiting at the end of it. */}
      {forDesign !== null && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-300 bg-slate-50 px-4 py-3">
          <p className="mr-auto text-sm text-slate-700">
            Choose a property for{' '}
            <span className="font-medium">{design?.name ?? 'your design'}</span>. Not
            listed yet? Import it from a URL or add it by hand, then come back to this
            list.
          </p>
          <Link
            to={designEditorPath(forDesign)}
            className="shrink-0 text-sm font-medium text-slate-600 underline underline-offset-2 transition hover:text-slate-900"
          >
            Back to the design
          </Link>
        </div>
      )}

      {error && <Alert kind="error">{error}</Alert>}

      <div className="flex gap-1">
        {(['all', 'unverified', 'verified'] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setFilter(option)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium capitalize transition ${
              filter === option
                ? 'bg-slate-900 text-white'
                : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            {option}
          </button>
        ))}
      </div>

      {!listings && !error && <p className="text-sm text-slate-500">Loading…</p>}

      {listings && listings.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center">
          <p className="text-sm text-slate-500">
            {filter === 'all'
              ? 'No listings yet. Create one or import from a URL.'
              : `No ${filter} listings.`}
          </p>
        </div>
      )}

      {listings && listings.length > 0 && (
        <ul className="space-y-3">
          {listings.map((listing) => (
            <li key={listing.id}>
              <ListingRow
                listing={listing}
                forDesign={forDesign !== null}
                applying={applying === listing.id}
                disabled={applying !== null}
                onApply={() => void applyTo(listing)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * One property.
 *
 * The whole row stays a link to the listing itself in both modes — an agent
 * choosing a property still needs to be able to open one and check it. The
 * apply button sits beside that link rather than replacing it, which is why
 * this is a div containing a Link rather than a Link containing a button:
 * nesting an interactive control inside an anchor is invalid HTML and the
 * click target it produces is ambiguous to a keyboard.
 */
function ListingRow({
  listing,
  forDesign,
  applying,
  disabled,
  onApply,
}: {
  listing: Listing
  forDesign: boolean
  applying: boolean
  disabled: boolean
  onApply: () => void
}) {
  // The server refuses to build a design on unverified data, so the button
  // says why it cannot be used rather than failing after the click.
  const usable = listing.verification_status === 'verified'

  return (
    <div className="flex gap-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-slate-300">
      <Link
        to={`/listings/${listing.id}`}
        className="flex min-w-0 flex-1 gap-4"
      >
        <div className="flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-md bg-slate-100">
          {listing.photos[0]?.image_url ? (
            <img src={listing.photos[0].image_url} alt="" className="size-full object-cover" />
          ) : (
            <span className="text-xs text-slate-400">No photo</span>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <p className="min-w-0 flex-1 truncate font-medium text-slate-800">
              {listing.full_address || 'Untitled listing'}
            </p>
            <VerificationBadge listing={listing} />
          </div>
          <p className="mt-1 text-sm text-slate-500">
            {formatPrice(listing.price)}
            {listing.bedrooms !== null && ` · ${listing.bedrooms} bed`}
            {listing.bathrooms !== null && ` · ${listing.bathrooms} bath`}
            {listing.square_footage !== null &&
              ` · ${listing.square_footage.toLocaleString()} sq ft`}
          </p>
          <p className="mt-1 text-xs capitalize text-slate-400">
            {listing.status.replace(/_/g, ' ')}
            {listing.source === 'import' && ' · imported'}
          </p>
        </div>
      </Link>

      {forDesign && (
        <div className="flex shrink-0 items-center">
          {usable ? (
            <button
              type="button"
              onClick={onApply}
              disabled={disabled}
              className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
            >
              {applying ? 'Applying…' : 'Apply to design'}
            </button>
          ) : (
            <Link
              to={`/listings/${listing.id}`}
              className="rounded-md border border-amber-300 px-3 py-2 text-sm font-medium text-amber-800 transition hover:bg-amber-50"
            >
              Verify first
            </Link>
          )}
        </div>
      )}
    </div>
  )
}
