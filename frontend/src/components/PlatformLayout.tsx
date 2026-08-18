/**
 * Dashboard 3 of 3 — Nehrux's own.
 *
 * The platform owner. Not a bigger agent and not a bigger agency admin: the
 * job here is supplying the product rather than using it. The whole rail is
 * things no customer can do — publishing templates into every agency's gallery,
 * and looking across all of them.
 *
 * Nehrux Admins only, guarded on the route and re-checked on every endpoint.
 */

import DashboardShell, { type NavItem } from './DashboardShell.tsx'
import { IconPlatform, IconUpload } from './icons.tsx'

/**
 * One destination, on purpose.
 *
 * An overview, a library browser and an accounts table were all here and are
 * all gone. None of them was the job: this dashboard exists to turn a PDF into
 * a template and put it in front of the agents, and a rail offering four other
 * places to go made that the fifth thing you saw.
 *
 * The rail stays for the account menu and sign-out, and because the single
 * entry names where you are.
 */
const ITEMS: NavItem[] = [
  { to: '/platform', label: 'Upload template', Icon: IconUpload, end: true },
]

export default function PlatformLayout() {
  return (
    <DashboardShell
      brand={{
        title: 'Nehrux',
        subtitle: 'Platform',
        Icon: IconPlatform,
        badge: 'Platform owner',
      }}
      items={ITEMS}
    />
  )
}
