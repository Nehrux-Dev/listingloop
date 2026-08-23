/**
 * The chrome every dashboard shares: a full-height rail beside the routed page.
 *
 * WHY THIS IS A COMPONENT AND NOT ONE LAYOUT WITH ROLE FLAGS
 * ---------------------------------------------------------------------------
 * There are three audiences here and they are not degrees of each other. An
 * agent makes marketing for their listings. A brokerage admin runs the agency
 * that bought the product. Nehrux runs the platform the agencies buy. One rail
 * that grew and shrank by role meant everybody was looking at a menu built for
 * somebody else with the wrong parts hidden — and it made "what does a
 * brokerage admin actually see?" a question you answered by tracing four
 * conditionals.
 *
 * So each audience gets its own shell (AppLayout, AdminLayout, PlatformLayout)
 * with its own explicit list of destinations, and this holds the parts that are
 * genuinely common: the rail, the account menu, the sign-out.
 *
 * The rail is presentation. Every route is guarded by role and every endpoint
 * re-checks; nothing here is a security boundary.
 */

import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext.tsx'
import {
  IconChevronDown,
  IconChevronLeft,
  IconClose,
  IconLogout,
  IconMenu,
  IconMoon,
} from './icons.tsx'

const RAIL_WIDTH = 'w-[204px]'

export type NavItem = {
  to: string
  label: string
  Icon: (props: { className?: string }) => React.ReactElement
  end?: boolean
  /** Rendered greyed out and unclickable — for a destination the product's
   *  navigation calls for but which does not exist yet. A link that 404s is
   *  worse than one that plainly says it is not ready. */
  soon?: boolean
}

export type ShellBrand = {
  /** Two short lines in the rail's header. */
  title: string
  subtitle: string
  Icon: (props: { className?: string }) => React.ReactElement
  /** Names which product this is. Shown under the account name so somebody
   *  with two roles can tell at a glance which dashboard they are in. */
  badge: string
}

function initialsOf(name: string, email: string): string {
  const source = name.trim() || email.trim()
  if (!source) return '?'
  const parts = source.replace(/@.*/, '').split(/[\s._-]+/).filter(Boolean)
  const letters = parts.slice(0, 2).map((part) => part[0])
  return (letters.join('') || source[0]).toUpperCase()
}

export default function DashboardShell({
  brand,
  items,
  wideRoutes = [],
  utilities,
}: {
  brand: ShellBrand
  items: NavItem[]
  /** Paths that take the viewport as-is instead of the centred reading column:
   *  a filter sidebar beside a grid needs the width. */
  wideRoutes?: RegExp[]
  /** Extra buttons for the rail's footer strip — the compliance bell only
   *  belongs on the shell whose users export marketing material. */
  utilities?: React.ReactNode
}) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const wide = wideRoutes.some((pattern) => pattern.test(pathname))

  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  /**
   * Below `md` the rail becomes a drawer behind a hamburger. It is the same
   * element in both worlds — fixed and slid off-canvas on phones, sticky on
   * desktop — rather than two copies of the markup, because the account menu
   * inside it carries state and refs that must not exist twice.
   */
  const [railOpen, setRailOpen] = useState(false)

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [menuOpen])

  // Collapsing the account menu and the drawer on navigation stops them
  // hanging open over the page the user just asked for.
  useEffect(() => {
    setMenuOpen(false)
    setRailOpen(false)
  }, [pathname])

  async function handleLogout() {
    await logout()
    void navigate('/login', { replace: true })
  }

  return (
    // Wide pages manage their own scroll, so the shell pins to the viewport
    // (`h-dvh`, which tracks the real visible height on mobile browsers where
    // the URL bar comes and goes); reading pages scroll as a document.
    <div className={`flex ${wide ? 'h-dvh' : 'min-h-screen'} bg-app text-ink`}>
      {/* Tapping the page behind the drawer is the universal "close". */}
      {railOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          aria-hidden="true"
          onClick={() => setRailOpen(false)}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex h-full ${RAIL_WIDTH} shrink-0 flex-col border-r border-line bg-surface transition-transform duration-200 md:sticky md:top-0 md:z-auto md:h-screen md:translate-x-0 md:transition-none ${
          railOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center gap-2.5 px-4 py-5">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-control bg-brand-soft text-brand">
            <brand.Icon className="size-5" />
          </span>
          <span className="text-[13px] font-semibold uppercase leading-[1.15] tracking-wide">
            {brand.title}
            <br />
            {brand.subtitle}
          </span>
          <button
            type="button"
            onClick={() => setRailOpen(false)}
            aria-label="Close menu"
            className="ml-auto flex size-8 items-center justify-center rounded-control text-muted transition hover:bg-hover hover:text-ink md:hidden"
          >
            <IconClose className="size-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2.5 pb-2">
          {items.map((item) =>
            item.soon ? (
              <span
                key={item.label}
                title={`${item.label} is not available yet`}
                aria-disabled="true"
                className="flex cursor-not-allowed items-center gap-2.5 rounded-control px-2.5 py-2 text-[13px] font-medium text-muted/55"
              >
                <item.Icon className="size-[18px]" />
                {item.label}
                <span className="ml-auto rounded-full bg-subtle px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-muted">
                  Soon
                </span>
              </span>
            ) : (
              <RailLink key={item.to} {...item} />
            ),
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
              <span className="block truncate text-[11px] text-muted">{brand.badge}</span>
            </span>
            <IconChevronDown
              className={`size-3.5 shrink-0 text-muted transition ${menuOpen ? 'rotate-180' : ''}`}
            />
          </button>

          <div className="mt-1.5 flex items-center gap-1 px-1.5">
            <span className="rounded-full border border-line bg-subtle px-2 py-0.5 text-[10px] font-semibold text-muted">
              {user?.role_display}
            </span>
            <div className="ml-auto flex items-center gap-0.5">
              <RailUtility title="Theme (coming soon)" disabled>
                <IconMoon className="size-[15px]" />
              </RailUtility>
              {utilities}
              <RailUtility title="Collapse (coming soon)" disabled>
                <IconChevronLeft className="size-[15px]" />
              </RailUtility>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* The phone's way into the drawer. Sticky so navigation is always a
            thumb-reach away however far the page has scrolled. */}
        <header className="sticky top-0 z-20 flex shrink-0 items-center gap-3 border-b border-line bg-surface px-4 py-3 md:hidden">
          <button
            type="button"
            onClick={() => setRailOpen(true)}
            aria-label="Open menu"
            className="flex size-9 items-center justify-center rounded-control border border-line text-muted transition hover:bg-hover hover:text-ink"
          >
            <IconMenu className="size-5" />
          </button>
          <span className="flex size-8 items-center justify-center rounded-control bg-brand-soft text-brand">
            <brand.Icon className="size-4" />
          </span>
          <span className="text-[12px] font-semibold uppercase tracking-wide">
            {brand.title} {brand.subtitle}
          </span>
        </header>

        {wide ? (
          <div className="min-h-0 flex-1">
            <Outlet />
          </div>
        ) : (
          <main className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-6 md:px-8 md:py-10">
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
          isActive ? 'bg-active text-brand' : 'text-muted hover:bg-hover hover:text-ink'
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
export function RailUtility({
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
