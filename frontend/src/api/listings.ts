/** Types and calls for listings and listing photos. */

import { apiRequest } from '../lib/apiClient.ts'
import type { Paginated } from './profiles.ts'

export type PropertyType =
  | 'house'
  | 'apartment'
  | 'townhouse'
  | 'condo'
  | 'duplex'
  | 'land'
  | 'commercial'
  | 'other'

export const PROPERTY_TYPES: { value: PropertyType; label: string }[] = [
  { value: 'house', label: 'House' },
  { value: 'apartment', label: 'Apartment' },
  { value: 'townhouse', label: 'Townhouse' },
  { value: 'condo', label: 'Condo' },
  { value: 'duplex', label: 'Duplex' },
  { value: 'land', label: 'Land' },
  { value: 'commercial', label: 'Commercial' },
  { value: 'other', label: 'Other' },
]

export type ListingStatus = 'draft' | 'active' | 'under_offer' | 'sold' | 'withdrawn'

export const LISTING_STATUSES: { value: ListingStatus; label: string }[] = [
  { value: 'draft', label: 'Draft' },
  { value: 'active', label: 'Active' },
  { value: 'under_offer', label: 'Under offer' },
  { value: 'sold', label: 'Sold' },
  { value: 'withdrawn', label: 'Withdrawn' },
]

export type VerificationStatus = 'unverified' | 'verified'

export type ListingPhoto = {
  id: number
  listing: number
  image_url: string | null
  /** The raw storage key behind image_url — what an image_key override
   *  actually needs. overrides.py refuses a URL there on purpose (see
   *  _validate_image_key), so image_url alone can't be used to pick this
   *  photo for a design element. */
  image_key: string
  caption: string
  order: number
  source_url: string
  created_at: string
}

export type Listing = {
  id: number
  agent: number
  agent_name: string
  address: string
  city: string
  state: string
  postcode: string
  country: string
  full_address: string
  latitude: string | null
  longitude: string | null
  /** Stable public URL segment; generated once and never changed. */
  public_slug: string | null
  price: string | null
  bedrooms: number | null
  bathrooms: string | null
  square_footage: number | null
  property_type: PropertyType | ''
  features: string[]
  description: string
  status: ListingStatus
  verification_status: VerificationStatus
  is_verified: boolean
  verified_at: string | null
  verified_by: number | null
  /** Still-empty fields that block verification. */
  missing_required_fields: string[]
  source: 'manual' | 'import'
  source_url: string
  /** Fields an import actually populated — everything else was left blank. */
  imported_fields: string[]
  import_warnings: string[]
  photos: ListingPhoto[]
  created_at: string
  updated_at: string
}

export type ListingImportResult = {
  listing: Listing
  extracted_fields: string[]
  warnings: string[]
  photo_count: number
}

/** Values the listing form sends. Everything is optional except via the UI. */
export type ListingInput = {
  address: string
  city: string
  state: string
  postcode: string
  country: string
  latitude: string
  longitude: string
  price: string
  bedrooms: string
  bathrooms: string
  square_footage: string
  property_type: PropertyType | ''
  features: string[]
  description: string
  status: ListingStatus
}

/**
 * Turn form strings into the JSON the API expects.
 *
 * Empty numeric inputs become `null`, not `0` or `""` — a blank field means
 * "not known", and writing a zero would be inventing data the agent never
 * entered.
 */
export function toListingPayload(input: ListingInput): Record<string, unknown> {
  const numeric = (value: string) => (value.trim() === '' ? null : value.trim())

  return {
    address: input.address.trim(),
    city: input.city.trim(),
    state: input.state.trim(),
    postcode: input.postcode.trim(),
    country: input.country.trim(),
    latitude: numeric(input.latitude),
    longitude: numeric(input.longitude),
    price: numeric(input.price),
    bedrooms: numeric(input.bedrooms),
    bathrooms: numeric(input.bathrooms),
    square_footage: numeric(input.square_footage),
    property_type: input.property_type,
    features: input.features.filter((feature) => feature.trim() !== ''),
    description: input.description.trim(),
    status: input.status,
  }
}

export function emptyListingInput(): ListingInput {
  return {
    address: '',
    city: '',
    state: '',
    postcode: '',
    country: '',
    latitude: '',
    longitude: '',
    price: '',
    bedrooms: '',
    bathrooms: '',
    square_footage: '',
    property_type: '',
    features: [],
    description: '',
    status: 'draft',
  }
}

export function listingToInput(listing: Listing): ListingInput {
  return {
    address: listing.address,
    city: listing.city,
    state: listing.state,
    postcode: listing.postcode,
    country: listing.country,
    latitude: listing.latitude ?? '',
    longitude: listing.longitude ?? '',
    price: listing.price ?? '',
    bedrooms: listing.bedrooms?.toString() ?? '',
    bathrooms: listing.bathrooms ?? '',
    square_footage: listing.square_footage?.toString() ?? '',
    property_type: listing.property_type,
    features: listing.features,
    description: listing.description,
    status: listing.status,
  }
}

// -- listings ---------------------------------------------------------------

export function fetchListings(params?: Record<string, string>): Promise<Paginated<Listing>> {
  const query = params ? `?${new URLSearchParams(params).toString()}` : ''
  return apiRequest<Paginated<Listing>>(`/api/listings/${query}`)
}

export function fetchListing(id: number): Promise<Listing> {
  return apiRequest<Listing>(`/api/listings/${id}/`)
}

export function createListing(input: ListingInput): Promise<Listing> {
  return apiRequest<Listing>('/api/listings/', {
    method: 'POST',
    body: toListingPayload(input),
  })
}

export function updateListing(id: number, input: ListingInput): Promise<Listing> {
  return apiRequest<Listing>(`/api/listings/${id}/`, {
    method: 'PATCH',
    body: toListingPayload(input),
  })
}

export function deleteListing(id: number): Promise<null> {
  return apiRequest<null>(`/api/listings/${id}/`, { method: 'DELETE' })
}

/**
 * The review step. `confirmed: true` is required by the server so
 * verification can never be an accidental empty POST.
 */
export function verifyListing(id: number): Promise<Listing> {
  return apiRequest<Listing>(`/api/listings/${id}/verify/`, {
    method: 'POST',
    body: { confirmed: true },
  })
}

export function unverifyListing(id: number): Promise<Listing> {
  return apiRequest<Listing>(`/api/listings/${id}/unverify/`, { method: 'POST' })
}

/** One-off, agent-triggered fetch of a public listing page. */
export function importListing(url: string): Promise<ListingImportResult> {
  return apiRequest<ListingImportResult>('/api/listings/import-url/', {
    method: 'POST',
    body: { url },
  })
}

/**
 * Import from page source the agent copied out of their own browser.
 *
 * For sites that refuse automated requests. Same parser, same refusal to
 * invent a value — the only difference is who fetched the page.
 */
export function importListingFromHtml(
  html: string,
  url: string,
): Promise<ListingImportResult> {
  return apiRequest<ListingImportResult>('/api/listings/import-html/', {
    method: 'POST',
    body: { html, url },
  })
}

/** The 422 body returned when a site blocks automated fetching. */
export type BlockedBySite = {
  detail: string
  blocked_by_site: boolean
  warnings: string[]
}

// -- photos -----------------------------------------------------------------

export function uploadListingPhoto(
  listingId: number,
  file: File,
  order: number,
): Promise<ListingPhoto> {
  const body = new FormData()
  body.append('listing', String(listingId))
  body.append('image', file)
  body.append('order', String(order))
  return apiRequest<ListingPhoto>('/api/listing-photos/', { method: 'POST', body })
}

export function deleteListingPhoto(id: number): Promise<null> {
  return apiRequest<null>(`/api/listing-photos/${id}/`, { method: 'DELETE' })
}
