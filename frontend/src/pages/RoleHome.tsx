/**
 * "/" — whichever dashboard belongs to whoever just signed in.
 *
 * There are three front doors and no user should have to know which one is
 * theirs. Signing in as the platform owner and landing on an agent's dashboard
 * — complete with a "finish your profile" checklist aimed at somebody who
 * exports marketing material — is the confusing version of this, and it is
 * what this replaces.
 *
 * The agent's dashboard renders here rather than redirecting, because "/" is
 * genuinely its home; the other two are elsewhere and get sent there.
 */

import { Navigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext.tsx'
import { ROLES } from '../auth/types.ts'
import DashboardPage from './DashboardPage.tsx'

export default function RoleHome() {
  const { user } = useAuth()

  if (user?.role === ROLES.NEHRUX_ADMIN) return <Navigate to="/platform" replace />
  if (user?.role === ROLES.BROKERAGE_ADMIN) return <Navigate to="/admin" replace />

  // Agents — including an agent who administers their own firm, who keeps the
  // agent dashboard as home and reaches the agency one from Settings.
  return <DashboardPage />
}
