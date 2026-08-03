/**
 * Route guards.
 *
 * IMPORTANT: these guards control what the browser *renders*. They are not a
 * security boundary — anyone can edit client-side JavaScript. Every protected
 * resource is independently enforced by a DRF permission class on the server
 * (see backend/apps/accounts/permissions.py). The guards exist so users are
 * not shown doors they cannot open.
 */

import type { ReactNode } from 'react'
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
  children?: ReactNode
}

/**
 * Requires an authenticated user holding one of `roles` (or `minimumRole` and
 * above). Unauthenticated users go to /login; authenticated users with the
 * wrong role get /forbidden — the distinction matters, since bouncing a
 * logged-in user to the login page is confusing and looks like a bug.
 */
export function RequireRole({ roles, minimumRole, children }: RequireRoleProps) {
  const { status, user, hasRole, hasRoleAtLeast } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <AuthLoading />

  if (status !== 'authenticated' || !user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  const allowed = minimumRole
    ? hasRoleAtLeast(minimumRole)
    : roles
      ? hasRole(...roles)
      : false

  if (!allowed) {
    return <Navigate to="/forbidden" replace />
  }

  return children ? <>{children}</> : <Outlet />
}

/** Renders `children` only when the user holds one of `roles`. UX only. */
export function RoleGate({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { hasRole } = useAuth()
  return hasRole(...roles) ? <>{children}</> : null
}
