import type { Listing } from '../api/listings.ts'

/** Small status pill. Verified is the exception, so it is the one that stands out. */
export function VerificationBadge({ listing }: { listing: Listing }) {
  const verified = listing.is_verified
  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
        verified
          ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200'
          : 'bg-amber-50 text-amber-700 ring-1 ring-amber-200'
      }`}
    >
      {verified ? 'Verified' : 'Needs review'}
    </span>
  )
}
