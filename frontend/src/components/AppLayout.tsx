/**
 * Dashboard 1 of 3 — the agent's.
 *
 * The person who lists properties and makes the marketing for them. Everything
 * here is about one agent's own work: their listings, the templates they start
 * from, the designs they have in progress.
 *
 * There is deliberately nothing administrative on this rail. A brokerage admin
 * gets AdminLayout and Nehrux gets PlatformLayout; this used to be one shell
 * that grew and shrank by role, which meant every audience was reading a menu
 * built for somebody else.
 */

import { Navigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext.tsx'
import { ROLES } from '../auth/types.ts'
import { ComplianceBell, ComplianceNoticeProvider } from './ComplianceNotice.tsx'
import DashboardShell, { type NavItem } from './DashboardShell.tsx'
import {
  IconBrandKit,
  IconCalendar,
  IconDashboard,
  IconDesigns,
  IconEnquiries,
  IconListings,
  IconReports,
  IconSettings,
  IconTemplates,
} from './icons.tsx'

/** Multi-column workspaces that take the viewport as-is: the template gallery
 *  with its filter sidebar beside a four-column grid, and the designs panel,
 *  which is the same shape of screen. Every other page keeps the centred
 *  reading column.
 *
 *  The editor is not listed because it is not inside this shell at all — it
 *  renders full screen, outside the layout entirely. `/designs` is anchored so
 *  it cannot match `/designs/12/edit`. */
const WIDE_ROUTES = [/^\/templates/, /^\/designs$/]

// Templates and Designs are two destinations, and the order is the workflow:
// Templates is the catalogue you start from, Designs is what you started.
const ITEMS: NavItem[] = [
  { to: '/', label: 'Dashboard', Icon: IconDashboard, end: true },
  { to: '/listings', label: 'Listings', Icon: IconListings },
  { to: '/calendar', label: 'Calendar', Icon: IconCalendar },
  { to: '/templates', label: 'Templates', Icon: IconTemplates },
  { to: '/designs', label: 'Designs', Icon: IconDesigns },
  { to: '/enquiries', label: 'Enquiries', Icon: IconEnquiries },
  { to: '/brand-kit', label: 'Brand Kit', Icon: IconBrandKit },
  { to: '/reports', label: 'Reports', Icon: IconReports, soon: true },
  { to: '/profile', label: 'Settings', Icon: IconSettings },
]

export default function AppLayout() {
  const { user } = useAuth()

  // Same rule as AdminLayout: staff accounts have their own dashboards and are
  // sent to them rather than being shown an agent's workspace they cannot use.
  if (user?.role === ROLES.NEHRUX_ADMIN) return <Navigate to="/platform" replace />
  if (user?.role === ROLES.BROKERAGE_ADMIN) return <Navigate to="/admin" replace />

  // The provider sits above the shell so the rail's compliance bell and the
  // routed page below it are looking at the same report.
  return (
    <ComplianceNoticeProvider>
      <DashboardShell
        brand={{
          title: 'Real',
          subtitle: 'Estate',
          Icon: IconDashboard,
          badge: 'Agent workspace',
        }}
        items={ITEMS}
        wideRoutes={WIDE_ROUTES}
        // Compliance belongs on this shell alone: it is something to check
        // before exporting, and this is the only audience that exports.
        utilities={<ComplianceBell />}
      />
    </ComplianceNoticeProvider>
  )
}
