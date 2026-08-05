/**
 * Public listing page API.
 *
 * These are the only calls in the app that work without a session, so they
 * bypass the authenticated client: `apiRequest` attaches a bearer token and
 * retries on 401 by refreshing, and doing that on a public page would fire a
 * pointless refresh for every anonymous visitor.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export type PublicPhoto = {
  id: number
  image_url: string | null
  caption: string
  order: number
}

export type PublicAgent = {
  name: string
  job_title: string
  phone: string
  email: string
  tagline: string
  photo_url: string | null
}

export type PublicBrokerage = {
  name: string
  phone: string
  website: string
  required_disclaimer: string
  logo_url: string | null
}

export type PublicLocation = {
  latitude: number | null
  longitude: number | null
  has_pin: boolean
  label: string
}

export type PublicListing = {
  public_slug: string
  address: string
  city: string
  state: string
  postcode: string
  country: string
  full_address: string
  location: PublicLocation
  price: string | null
  bedrooms: number | null
  bathrooms: string | null
  square_footage: number | null
  property_type: string
  property_type_display: string
  features: string[]
  description: string
  status: string
  status_display: string
  photos: PublicPhoto[]
  agent: PublicAgent
  brokerage: PublicBrokerage | null
  /** Proves the form was actually loaded before being submitted. */
  enquiry_form_token: string
}

export class PublicApiError extends Error {
  readonly status: number
  readonly data: unknown

  constructor(status: number, message: string, data: unknown = null) {
    super(message)
    this.name = 'PublicApiError'
    this.status = status
    this.data = data
  }
}

async function publicRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
  })

  const text = await response.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = text
  }

  if (!response.ok) {
    const record = body as Record<string, unknown> | null
    const detail =
      typeof record?.detail === 'string' ? record.detail : `Request failed (${response.status})`
    throw new PublicApiError(response.status, detail, body)
  }
  return body as T
}

export function fetchPublicListing(slug: string): Promise<PublicListing> {
  return publicRequest<PublicListing>(`/api/public/listings/${slug}/`)
}

export type EnquiryInput = {
  name: string
  email: string
  phone: string
  message: string
  form_token: string
  /** Honeypot — must stay empty. Hidden from real users. */
  website: string
}

export function submitEnquiry(
  slug: string,
  payload: EnquiryInput,
): Promise<{ detail: string }> {
  return publicRequest(`/api/public/listings/${slug}/enquire/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
