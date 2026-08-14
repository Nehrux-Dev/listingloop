import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext.tsx'
import { ROLES } from '../auth/types.ts'
import { ComplianceBell, ComplianceNoticeProvider } from './ComplianceNotice.tsx'
import {
  IconBrandKit,
  IconBrokerage,
  IconCalendar,
  IconChevronLeft,
  IconChevronDown,
  IconDashboard,
  IconDesigns,
  IconEnquiries,
  IconListings,
  IconLogout,
  IconMoon,
  IconPlatform,
  IconReports,
  IconSettings,
  IconTemplates,
} from './icons.tsx'

/**
 * The application shell: a full-height navigation rail beside the routed
 * page.
 *
 * Previously a horizontal header above a centred column. That worked for the
 * reading-width pages but gave the editor a band of chrome across the top of
 * an already-tall workspace, and it capped the whole app at one row of links.
 * A rail scales to the ten destinations this product actually has and hands
 * the editor the full height of the viewport.
 *
 * Role gating is unchanged and deliberately preserved: links are filtered so
 * nobody is shown a door they cannot open, while the routes stay guarded and
 * the API enforces the real boundary.
 */

/** Multi-column workspaces that take the viewport as-is: the editor, and the
 *  template gallery with its filter sidebar beside a four-column grid.
 *  Every other page keeps the centred reading column. */
const WIDE_ROUTES = [/^\/designs\/\d+/, /^\/templates/]

const RAIL_WIDTH = 'w-[204px]'

type NavItem = {
  to: string
  label: string
  Icon: (props: { className?: string }) => React.ReactElement
  end?: boolean
}

function initialsOf(name: string, email: string): string {
  const source = name.trim() || email.trim()
  if (!source) return '?'
  const parts = source.replace(/@.*/, '').split(/[\s._-]+/).filter(Boolean)
  const letters = parts.slice(0, 2).map((part) => part[0])
  return (letters.join('') || source[0]).toUpperCase()
}

export default function AppLayout() {
  // The provider sits above the shell so the rail's compliance bell and the
  // routed page below it are looking at the same report.
  return (
    <ComplianceNoticeProvider>
      <AppShell />
    </ComplianceNoticeProvider>
  )
}

function AppShell() {
  const { user, logout, hasRoleAtLeast, hasRole } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const wide = WIDE_ROUTES.some((pattern) => pattern.test(pathname))

  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [menuOpen])

  // Collapsing the account menu on navigation stops it hanging open over the
  // page the user just asked for.
  useEffect(() => setMenuOpen(false), [pathname])

  async function handleLogout() {
    await logout()
    void navigate('/login', { replace: true })
  }

  const primary: NavItem[] = [
    { to: '/', label: 'Dashboard', Icon: IconDashboard, end: true },
    { to: '/listings', label: 'Listings', Icon: IconListings },
    { to: '/calendar', label: 'Calendar', Icon: IconCalendar },
    { to: '/templates', label: 'Templates', Icon: IconTemplates },
    { to: '/designs', label: 'Designs', Icon: IconDesigns },
    { to: '/enquiries', label: 'Enquiries', Icon: IconEnquiries },
  ]

  return (
    <div className="flex min-h-screen bg-app text-ink">
      <aside
        className={`sticky top-0 flex h-screen ${RAIL_WIDTH} shrink-0 flex-col border-r border-line bg-surface`}
      >
        <div className="flex items-center gap-2.5 px-4 py-5">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-control bg-brand-soft text-brand">
            <IconDashboard className="size-5" />
          </span>
          <span className="text-[13px] font-semibold uppercase leading-[1.15] tracking-wide">
            Real
            <br />
            Estate
          </span>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2.5 pb-2">
          {primary.map((item) => (
            <RailLink key={item.to} {...item} />
          ))}

          {hasRole(ROLES.AGENT) && <RailLink to="/brand-kit" label="Brand Kit" Icon={IconBrandKit} />}

          {(hasRoleAtLeast(ROLES.BROKERAGE_ADMIN) || user?.administers_brokerage) && (
            <RailLink to="/brokerage" label="Brokerage" Icon={IconBrokerage} />
          )}

          {/* Present because the product's navigation calls for it, disabled
              because there is no reports page yet. A link that 404s would be
              worse than one that plainly says it is not ready. */}
          <span
            title="Reports are not available yet"
            aria-disabled="true"
            className="flex cursor-not-allowed items-center gap-2.5 rounded-control px-2.5 py-2 text-[13px] font-medium text-muted/55"
          >
            <IconReports className="size-[18px]" />
            Reports
            <span className="ml-auto rounded-full bg-subtle px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-muted">
              Soon
            </span>
          </span>

          {hasRole(ROLES.AGENT) && <RailLink to="/profile" label="Settings" Icon={IconSettings} />}

          {hasRole(ROLES.NEHRUX_ADMIN) && (
            <RailLink to="/platform" label="Platform" Icon={IconPlatform} />
          )}
        </nav>

        <div ref={menuRef} className="relative border-t border-line p-2.5">
          {menuOpen && (
            <div className="absolute bottom-full left-2.5 right-2.5 mb-1.5 overflow-hidden rounded-panel border border-line bg-surface shadow-pop">
              <button
                type="button"
                onClick={() => void handleLogout()}
                className="flex w-full items-center gap-2 px-3 py-2.5 text-[13px] font-medium text-ink transition hover:bg-hover"
              >
                <IconLogout className="size-[17px] text-muted" />
                Sign out
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            className="flex w-full items-center gap-2.5 rounded-control p-1.5 text-left transition hover:bg-hover"
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand text-[11px] font-semibold text-white">
              {initialsOf(user?.full_name ?? '', user?.email ?? '')}
            </span>
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate text-[12px] font-semibold">
                {user?.full_name || user?.email}
              </span>
              <span className="block truncate text-[11px] text-muted">{user?.role_display}</span>
            </span>
            <IconChevronDown
              className={`size-3.5 shrink-0 text-muted transition ${menuOpen ? 'rotate-180' : ''}`}
            />
          </button>

          <div className="mt-1.5 flex items-center gap-1 px-1.5">
            <span className="rounded-full border border-line bg-subtle px-2 py-0.5 text-[10px] font-semibold text-muted">
              Free plan
            </span>
            <div className="ml-auto flex items-center gap-0.5">
              <RailUtility title="Theme (coming soon)" disabled>
                <IconMoon className="size-[15px]" />
              </RailUtility>
              {/* Compliance lives here rather than pinned open in the editor's
                  right panel: it is something to check before exporting, not
                  something to stare at while designing. */}
              <ComplianceBell />
              <RailUtility title="Collapse (coming soon)" disabled>
                <IconChevronLeft className="size-[15px]" />
              </RailUtility>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {wide ? (
          <Outlet />
        ) : (
          <main className="mx-auto w-full max-w-4xl px-8 py-10">
            <Outlet />
          </main>
        )}
      </div>
    </div>
  )
}

function RailLink({ to, label, Icon, end }: NavItem) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-2.5 rounded-control px-2.5 py-2 text-[13px] font-medium transition ${
          isActive
            ? 'bg-active text-brand'
            : 'text-muted hover:bg-hover hover:text-ink'
        }`
      }
    >
      {({ isActive }) => (
        <>
          <Icon className={`size-[18px] ${isActive ? 'text-brand' : ''}`} />
          {label}
        </>
      )}
    </NavLink>
  )
}

/** The rail's small utility buttons. Rendered disabled where the feature
 *  behind them does not exist yet, rather than wired to nothing. */
function RailUtility({
  title,
  disabled,
  children,
}: {
  title: string
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      disabled={disabled}
      className="flex size-6 items-center justify-center rounded-control text-muted transition hover:bg-hover hover:text-ink disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  )
}
