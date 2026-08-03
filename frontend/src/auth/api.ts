/** Calls against the /api/auth/ endpoints. */

import { apiRequest } from '../lib/apiClient.ts'
import { setAccessToken } from './tokenStore.ts'
import type { Credentials, LoginResponse, User } from './types.ts'

export async function login(credentials: Credentials): Promise<LoginResponse> {
  const data = await apiRequest<LoginResponse>('/api/auth/login/', {
    method: 'POST',
    body: credentials,
    // A 401 here means "bad credentials", not "expired token" — refreshing
    // and retrying would be pointless.
    skipAuthRefresh: true,
  })

  // The response body carries only the access token. The refresh token
  // arrived as a Set-Cookie header the browser stored for us; this code never
  // sees it, which is the entire point.
  setAccessToken(data.access)
  return data
}

export async function register(payload: {
  email: string
  full_name?: string
  password: string
  password_confirm: string
}): Promise<LoginResponse> {
  const data = await apiRequest<LoginResponse>('/api/auth/register/', {
    method: 'POST',
    body: payload,
    skipAuthRefresh: true,
  })
  setAccessToken(data.access)
  return data
}

/**
 * End the session server-side.
 *
 * The server blacklists the refresh token and sends an expired Set-Cookie to
 * remove it. Clearing the in-memory access token is the caller's job — done
 * in the auth provider, which owns that state.
 */
export async function logout(): Promise<void> {
  await apiRequest<null>('/api/auth/logout/', {
    method: 'POST',
    skipAuthRefresh: true,
  })
}

export async function fetchCurrentUser(): Promise<User> {
  return apiRequest<User>('/api/auth/me/')
}
