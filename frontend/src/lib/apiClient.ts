/**
 * Thin fetch wrapper that handles authentication.
 *
 * Two things happen here that make the httpOnly-cookie scheme work:
 *
 *  1. `credentials: 'include'` — tells the browser to send (and accept) the
 *     refresh cookie. Without it, fetch drops cookies on cross-origin calls
 *     and the refresh endpoint would never see one.
 *
 *  2. Transparent re-auth — access tokens expire after a few minutes, so a
 *     401 is a routine event, not an error. On a 401 we call the refresh
 *     endpoint once, then replay the original request with the new token.
 *     The refresh token itself is never touched by this code; the browser
 *     attaches the cookie on its own.
 */

import { clearAccessToken, getAccessToken, setAccessToken } from '../auth/tokenStore.ts'

// Empty by default so requests go to the same origin (/api/...) and are
// forwarded to Django by the Vite dev proxy.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  readonly status: number
  readonly data: unknown

  constructor(status: number, message: string, data: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

/** Pull a readable message out of a DRF error body. */
function extractErrorMessage(status: number, body: unknown): string {
  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>

    const detail = record.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && typeof detail[0] === 'string') return detail[0]

    // Field errors: {"email": ["A user with this email already exists."]}
    for (const value of Object.values(record)) {
      if (typeof value === 'string') return value
      if (Array.isArray(value) && typeof value[0] === 'string') return value[0]
    }
  }
  return `Request failed with status ${status}`
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204 || response.status === 205) return null
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text) as unknown
  } catch {
    return text
  }
}

type RequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown
  /** Skip the automatic refresh-and-retry (used by the refresh call itself). */
  skipAuthRefresh?: boolean
}

async function rawRequest(path: string, options: RequestOptions = {}): Promise<Response> {
  const { body, skipAuthRefresh: _skip, headers, ...rest } = options

  const isFormData = body instanceof FormData

  const finalHeaders = new Headers(headers)
  finalHeaders.set('Accept', 'application/json')
  if (body !== undefined && !isFormData) {
    finalHeaders.set('Content-Type', 'application/json')
  }
  // For FormData the Content-Type is deliberately NOT set: the browser has to
  // generate it so it can append the multipart boundary. Setting it by hand
  // produces a body the server cannot parse.

  // The access token travels in the Authorization header, never in a cookie —
  // a header cannot be attached automatically by the browser, so it carries no
  // CSRF risk.
  const token = getAccessToken()
  if (token) {
    finalHeaders.set('Authorization', `Bearer ${token}`)
  }

  let payload: BodyInit | undefined
  if (body !== undefined) {
    payload = isFormData ? body : JSON.stringify(body)
  }

  return fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: finalHeaders,
    body: payload,
    // Required for the httpOnly refresh cookie to be sent and stored.
    credentials: 'include',
  })
}

/**
 * Exchange the refresh cookie for a fresh access token.
 *
 * Note the empty body: the credential is the cookie, which the browser adds
 * automatically. JavaScript cannot read it and does not need to.
 */
export async function refreshAccessToken(): Promise<string | null> {
  const response = await rawRequest('/api/auth/refresh/', {
    method: 'POST',
    skipAuthRefresh: true,
  })

  if (!response.ok) {
    clearAccessToken()
    return null
  }

  const data = (await response.json()) as { access: string }
  setAccessToken(data.access)
  return data.access
}

// A single in-flight refresh shared by all callers. Without this, five
// concurrent 401s would fire five refreshes — and since refresh tokens rotate
// and are single-use, four of them would fail and log the user out.
let refreshInFlight: Promise<string | null> | null = null

function refreshOnce(): Promise<string | null> {
  refreshInFlight ??= refreshAccessToken().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

/** Perform an API request, refreshing the access token once on a 401. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response = await rawRequest(path, options)

  if (response.status === 401 && !options.skipAuthRefresh) {
    const token = await refreshOnce()
    if (token) {
      // Retry the original request with the new access token.
      response = await rawRequest(path, options)
    }
  }

  const body = await parseBody(response)

  if (!response.ok) {
    throw new ApiError(response.status, extractErrorMessage(response.status, body), body)
  }

  return body as T
}
