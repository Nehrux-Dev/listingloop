/**
 * Route guards.
 *
 * IMPORTANT: these guards control what the browser *renders*. They are not a
 * security boundary — anyone can edit client-side JavaScript. Every protected
 * resource is independently enforced by a DRF permission class on the server
 * (see backend/apps/accounts/permissions.py). The guards exist so users are
 * not shown doors they cannot open.
 */

import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from './AuthContext.tsx'
import type { Role } from './types.ts'

function AuthLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
      Restoring session&hellip;
    </div>
  )
}

/**
 * Requires an authenticated user; otherwise redirects to /login.
 *
 * Renders as a layout route (`<Outlet />`) or as a wrapper around `children`.
 *
 * The `status === 'loading'` branch is essential: on a page reload the access
 * token is gone from memory and the provider is mid-refresh. Redirecting
 * during that window would kick out a perfectly valid session.
 */
export function ProtectedRoute({ children }: { children?: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <AuthLoading />

  if (status !== 'authenticated') {
    // `state.from` lets the login page send the user back where they were
    // headed. `replace` keeps the guarded URL out of the history stack.
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return children ? <>{children}</> : <Outlet />
}

type RequireRoleProps = {
  /** Exact roles allowed. Use this or `minimumRole`, not both. */
  roles?: Role[]
  /** Lowest role allowed, following the role hierarchy. */
  minimumRole?: Role
  /**
   * Also admit anyone who administers a brokerage, whatever their role.
   *
   * Needed for /brokerage: an agent who added their firm from Settings may
   * edit it, but holds the Agent role. Without this the export gate would tell
   * them to fix the brokerage logo on a screen they are bounced off.
   */
  orBrokerageAdministrator?: boolean
  children?: ReactNode
}

/**
 * Requires an authenticated user holding one of `roles` (or `minimumRole` and
 * above). Unauthenticated users go to /login; authenticated users with the
 * wrong role get /forbidden — the distinction matters, since bouncing a
 * logged-in user to the login page is confusing and looks like a bug.
 */
export function RequireRole({
  roles,
  minimumRole,
  orBrokerageAdministrator = false,
  children,
}: RequireRoleProps) {
  const { status, user, hasRole, hasRoleAtLeast, revalidate } = useAuth()
  const location = useLocation()
  const [revalidated, setRevalidated] = useState(false)

  const byRole = minimumRole
    ? hasRoleAtLeast(minimumRole)
    : roles
      ? hasRole(...roles)
      : false
  const allowed =
    byRole || (orBrokerageAdministrator && (user?.administers_brokerage ?? false))

  // Before turning anyone away, make sure we are not judging them on a stale
  // copy of themselves.
  //
  // `user` is a snapshot taken at sign-in. Anything that changes a user's
  // rights mid-session — creating a brokerage, an admin granting a role —
  // leaves that snapshot behind, and the guard then refuses someone the server
  // would have allowed. That is worse than a slow page: the export gate sends
  // an agent to /brokerage and this bounces them to /forbidden.
  //
  // One re-fetch, once per mount, and only on the failing path.
  useEffect(() => {
    if (status === 'authenticated' && !allowed && !revalidated) {
      setRevalidated(true)
      void revalidate()
    }
  }, [status, allowed, revalidated, revalidate])

  if (status === 'loading') return <AuthLoading />

  if (status !== 'authenticated' || !user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  if (!allowed) {
    // Still waiting on the re-check: showing the loader beats a /forbidden
    // flash that turns out to be wrong a moment later.
    if (!revalidated) return <AuthLoading />
    return <Navigate to="/forbidden" replace />
  }

  return children ? <>{children}</> : <Outlet />
}

/** Renders `children` only when the user holds one of `roles`. UX only. */
export function RoleGate({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { hasRole } = useAuth()
  return hasRole(...roles) ? <>{children}</> : null
}
