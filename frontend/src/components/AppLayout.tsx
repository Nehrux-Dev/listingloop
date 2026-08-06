import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext.tsx'
import { ROLES } from '../auth/types.ts'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition ${
    isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
  }`

export default function AppLayout() {
  const { user, logout, hasRoleAtLeast, hasRole } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    void navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center gap-2 px-6 py-3">
          <span className="mr-4 text-sm font-semibold tracking-tight">Real Estate</span>

          <nav className="flex items-center gap-1">
            <NavLink to="/" end className={linkClass}>
              Dashboard
            </NavLink>

            <NavLink to="/listings" className={linkClass}>
              Listings
            </NavLink>
            <NavLink to="/calendar" className={linkClass}>
              Calendar
            </NavLink>
            <NavLink to="/templates" className={linkClass}>
              Templates
            </NavLink>
            <NavLink to="/designs" className={linkClass}>
              Designs
            </NavLink>
            <NavLink to="/enquiries" className={linkClass}>
              Enquiries
            </NavLink>

            {/* Only agents have a profile and a personal brand kit. */}
            {hasRole(ROLES.AGENT) && (
              <>
                <NavLink to="/profile" className={linkClass}>
                  My profile
                </NavLink>
                <NavLink to="/brand-kit" className={linkClass}>
                  Brand kit
                </NavLink>
              </>
            )}

            {/* Nav links are filtered by role purely so users are not shown
                doors they cannot open. The routes themselves are guarded, and
                the API enforces the real boundary. */}
            {(hasRoleAtLeast(ROLES.BROKERAGE_ADMIN) ||
              user?.administers_brokerage) && (
              <NavLink to="/brokerage" className={linkClass}>
                Brokerage
              </NavLink>
            )}
            {hasRole(ROLES.NEHRUX_ADMIN) && (
              <NavLink to="/platform" className={linkClass}>
                Platform
              </NavLink>
            )}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <span className="text-right text-xs leading-tight text-slate-500">
              <span className="block font-medium text-slate-700">{user?.email}</span>
              {user?.role_display}
            </span>
            <button
              type="button"
              onClick={() => void handleLogout()}
              className="rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-10">
        <Outlet />
      </main>
    </div>
  )
}
