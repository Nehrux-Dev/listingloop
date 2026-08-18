/**
 * Dashboard 2 of 3 — the buying agency's.
 *
 * This is the customer: the brokerage that pays for the product and whose
 * agents use it. Their concerns are the firm's, not one listing's — who is on
 * the team, what the agency's brand is, what its people are publishing, and
 * what the compliance wording has to say.
 *
 * Everything here is scoped to their own brokerage server-side. A brokerage
 * admin cannot see another firm's agents, listings or designs, and the rail
 * being separate is presentation — `BrokeragePermission` and the querysets
 * behind each endpoint are what actually hold the line.
 */

import { Navigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext.tsx'
import { ROLES } from '../auth/types.ts'
import DashboardShell, { type NavItem } from './DashboardShell.tsx'
import {
  IconBrandKit,
  IconBrokerage,
  IconDashboard,
  IconDesigns,
  IconEnquiries,
  IconListings,
  IconReports,
} from './icons.tsx'

const ITEMS: NavItem[] = [
  { to: '/admin', label: 'Overview', Icon: IconDashboard, end: true },
  { to: '/admin/brokerage', label: 'Brokerage', Icon: IconBrokerage },
  { to: '/admin/listings', label: 'Listings', Icon: IconListings },
  { to: '/admin/designs', label: 'Designs', Icon: IconDesigns },
  { to: '/admin/enquiries', label: 'Enquiries', Icon: IconEnquiries },
  { to: '/admin/brand-kit', label: 'Brand Kit', Icon: IconBrandKit },
  { to: '/admin/reports', label: 'Reports', Icon: IconReports, soon: true },
]

const WIDE_ROUTES = [/^\/admin\/designs$/]

export default function AdminLayout() {
  const { user } = useAuth()

  // The platform owner does not belong in the customer's dashboard.
  //
  // The route guard admits "brokerage admin or above", and Nehrux Admin is
  // above — so it lets them in and then leaves them there, whatever sent them.
  // Being senior to a role is not the same as holding it: this is the agency's
  // own screen, and the platform owner has their own.
  if (user?.role === ROLES.NEHRUX_ADMIN) return <Navigate to="/platform" replace />

  return (
    <DashboardShell
      brand={{
        title: 'Agency',
        subtitle: 'Admin',
        Icon: IconBrokerage,
        badge: 'Agency administration',
      }}
      items={ITEMS}
      wideRoutes={WIDE_ROUTES}
    />
  )
}
