export type CheckResult = {
  status: 'ok' | 'error'
  detail?: string
}

export type HealthResponse = {
  status: 'ok' | 'error'
  checks: Record<string, CheckResult>
}

// Requests go to /api/... and are proxied to Django by the Vite dev server,
// so there is no CORS round trip in development.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/api/health/`, {
    headers: { Accept: 'application/json' },
  })

  const body = (await response.json()) as HealthResponse
  return body
}
