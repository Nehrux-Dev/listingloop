import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchListings, type Listing } from '../api/listings.ts'
import { Alert } from '../components/FormControls.tsx'
import { VerificationBadge } from '../components/VerificationBadge.tsx'
import { ApiError } from '../lib/apiClient.ts'

function formatPrice(price: string | null): string {
  if (!price) return '—'
  const value = Number(price)
  return Number.isFinite(value)
    ? value.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
    : price
}

export default function ListingsPage() {
  const [listings, setListings] = useState<Listing[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'verified' | 'unverified'>('all')

  useEffect(() => {
    const params = filter === 'all' ? undefined : { verification_status: filter }
    fetchListings(params)
      .then((page) => setListings(page.results))
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : 'Could not load listings.'),
      )
  }, [filter])

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
          to="/listings/import"
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          Import from URL
        </Link>
        <Link
          to="/listings/new"
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
        >
          New listing
        </Link>
      </div>

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
              <Link
                to={`/listings/${listing.id}`}
                className="flex gap-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-slate-300"
              >
                <div className="flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-md bg-slate-100">
                  {listing.photos[0]?.image_url ? (
                    <img
                      src={listing.photos[0].image_url}
                      alt=""
                      className="size-full object-cover"
                    />
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
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
