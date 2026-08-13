/**
 * Authentication provider.
 *
 * Owns the two pieces of session state the app cares about:
 *   - `user`: who is logged in (fetched from the server, never trusted from
 *     client storage)
 *   - the access token, which lives in `tokenStore` (memory only)
 *
 * SESSION RESTORE ON PAGE LOAD
 * ----------------------------
 * Because the access token is in memory, a reload starts with no credentials.
 * `bootstrap()` therefore makes one call to /api/auth/refresh/ on mount. The
 * browser attaches the httpOnly refresh cookie automatically, and if it is
 * still valid we get a fresh access token and restore the session. If it is
 * not, `status` becomes 'unauthenticated' and the router sends the user to
 * the login page.
 *
 * The `status === 'loading'` state matters: without it, the protected-route
 * wrapper would see "no user" for a moment on every reload and bounce an
 * authenticated user to /login before the refresh completed.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { refreshOnce } from '../lib/apiClient.ts'
import { fetchCurrentUser, login as loginRequest, logout as logoutRequest } from './api.ts'
import { clearAccessToken } from './tokenStore.ts'
import { hasRoleAtLeast, type Credentials, type Role, type User } from './types.ts'

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

type AuthContextValue = {
  user: User | null
  status: AuthStatus
  isAuthenticated: boolean
  login: (credentials: Credentials) => Promise<User>
  logout: () => Promise<void>
  /**
   * Adopt a session created outside `login` — registration, which returns a
   * token and sets the refresh cookie itself. Without this the provider would
   * still say 'unauthenticated' and the route guard would bounce a newly
   * registered agent straight back to the sign-in page.
   */
  refresh: () => Promise<void>
  /**
   * Re-read the current user without risking the session.
   *
   * For permission re-checks: `user` is a snapshot from sign-in, so anything
   * that changes a user's rights mid-session leaves it stale. Unlike
   * `refresh`, a failure here is swallowed and the existing user kept.
   */
  revalidate: () => Promise<void>
  /** Exact-role check, for conditional UI. */
  hasRole: (...roles: Role[]) => boolean
  /** Hierarchical check, mirroring the backend's "or above" permissions. */
  hasRoleAtLeast: (minimum: Role) => boolean
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')

  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      // One refresh attempt on boot. A 401 here is the normal "not logged in"
      // case, not an error worth surfacing.
      //
      // `refreshOnce`, not `refreshAccessToken`: StrictMode runs this effect
      // twice in development, and two overlapping refreshes would rotate the
      // token out from under each other — the second gets a 401 on a session
      // that is perfectly valid. Sharing the in-flight promise means both
      // mounts observe the same single request.
      const token = await refreshOnce()
      if (cancelled) return

      if (!token) {
        setUser(null)
        setStatus('unauthenticated')
        return
      }

      try {
        const currentUser = await fetchCurrentUser()
        if (cancelled) return
        setUser(currentUser)
        setStatus('authenticated')
      } catch {
        if (cancelled) return
        clearAccessToken()
        setUser(null)
        setStatus('unauthenticated')
      }
    }

    void bootstrap()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (credentials: Credentials) => {
    const { user: loggedIn } = await loginRequest(credentials)
    setUser(loggedIn)
    setStatus('authenticated')
    return loggedIn
  }, [])

  const refresh = useCallback(async () => {
    try {
      const currentUser = await fetchCurrentUser()
      setUser(currentUser)
      setStatus('authenticated')
    } catch {
      clearAccessToken()
      setUser(null)
      setStatus('unauthenticated')
    }
  }, [])

  const revalidate = useCallback(async () => {
    try {
      const currentUser = await fetchCurrentUser()
      setUser(currentUser)
      setStatus('authenticated')
    } catch {
      // Deliberately silent, and deliberately NOT `refresh`. This is a
      // permission re-check, not a sign-in: a transient failure here means we
      // simply keep the user we already had. Signing someone out because a
      // background check hiccuped is a far worse outcome than showing them the
      // /forbidden page they were heading to anyway.
    }
  }, [])

  const logout = useCallback(async () => {
    try {
      // Server-side revocation: blacklists the refresh token and expires the
      // cookie. Without this call the cookie would keep working for days.
      await logoutRequest()
    } finally {
      // Local state is cleared even if the network call failed, so the user is
      // never left looking logged in when they asked to leave.
      clearAccessToken()
      setUser(null)
      setStatus('unauthenticated')
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      isAuthenticated: status === 'authenticated' && user !== null,
      login,
      logout,
      refresh,
      revalidate,
      // Client-side role checks decide what to *render*. They are a UX
      // affordance, never a security boundary — the server re-checks the role
      // on every request, because anything in the browser can be edited.
      hasRole: (...roles: Role[]) => (user ? roles.includes(user.role) : false),
      hasRoleAtLeast: (minimum: Role) =>
        user ? hasRoleAtLeast(user.role, minimum) : false,
    }),
    [user, status, login, logout, refresh, revalidate],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used inside an <AuthProvider>')
  }
  return context
}
