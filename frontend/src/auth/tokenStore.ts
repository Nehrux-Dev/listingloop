/**
 * In-memory access token store.
 *
 * SECURITY: the access token lives in this module-level variable and NOWHERE
 * else. It is deliberately never written to localStorage or sessionStorage:
 *
 *   - Anything in web storage is readable by any script running on the origin.
 *     One XSS bug and the attacker walks away with a credential they can use
 *     from their own machine.
 *   - A JS variable dies with the page. An attacker who gets script execution
 *     can still act while their code runs, but there is nothing durable to
 *     steal.
 *
 * The cost is that a page reload loses the token — which is exactly what the
 * refresh flow is for. On boot, the auth provider calls /api/auth/refresh/,
 * the browser attaches the httpOnly refresh cookie automatically, and a new
 * access token comes back. The user never notices.
 *
 * The refresh token itself never appears in JavaScript at all: it is an
 * httpOnly cookie, so `document.cookie` cannot see it and neither can this
 * module. See backend/apps/accounts/cookies.py.
 */

let accessToken: string | null = null

export function getAccessToken(): string | null {
  return accessToken
}

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function clearAccessToken(): void {
  accessToken = null
}
