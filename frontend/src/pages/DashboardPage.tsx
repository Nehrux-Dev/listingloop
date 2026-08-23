/**
 * The agent's front door.
 *
 * Every block here is a doorway into a screen that already exists — the
 * dashboard owns no feature of its own. Its job is to answer "what was I
 * doing, and what should I do next?" in one glance: resume a design, market a
 * listing that has nothing made for it yet, catch a seasonal moment before it
 * passes, and see who enquired overnight.
 *
 * Each section loads and fails independently. A dashboard that goes blank
 * because one of five requests failed is worse than one with a quiet gap —
 * so there is no shared error state, and a failed section renders a one-line
 * shrug instead of taking the page down with it.
 *
 * Backend health used to live here; it moved to Settings. An agent cannot act
 * on "Redis: ok", so it was noise in the one place that should be all signal.
 */

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchListings, type Listing, type ListingStatus } from '../api/listings.ts'
import {
  fetchProfileCompleteness,
  type ProfileCompleteness,
} from '../api/profileSetup.ts'
import type { Paginated } from '../api/profiles.ts'
import {
  fetchCalendarEvents,
  fetchDesigns,
  type CalendarEvent,
  type Design,
} from '../api/templates.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import {
  IconArrowRight,
  IconBrandKit,
  IconCalendar,
  IconEnquiries,
  IconListings,
  IconTemplates,
} from '../components/icons.tsx'
import { apiRequest } from '../lib/apiClient.ts'
import { DESIGNS_HOME, TEMPLATES_HOME, designEditorPath } from '../lib/routes.ts'
import { lastEdited } from '../lib/time.ts'

/** The slice of an enquiry this page shows. The API returns more; listing
 *  only what is read keeps the dashboard decoupled from the full record. */
type EnquiryRow = {
  id: number
  listing_address: string | null
  name: string
  message: string
  status: 'new' | 'read' | 'replied' | 'archived' | 'spam'
  created_at: string
}

type EnquirySummary = { total: number; new: number; spam: number }

/**
 * Remembers a dismissal against *what was missing at the time*, not just
 * "dismissed".
 *
 * Dismissing forever would hide a genuinely new gap — an agent who dismisses
 * this at 90%, then joins a brokerage with a disclaimer they have not filled
 * in, should hear about it. Keying on the missing set means the prompt comes
 * back when the answer changes and stays gone when it does not.
 */
const DISMISSED_KEY = 'profile-prompt-dismissed'

function signatureOf(completeness: ProfileCompleteness): string {
  return completeness.missing_required
    .map((field) => field.key)
    .sort()
    .join(',')
}

function readDismissed(userId: number | undefined): string | null {
  if (userId === undefined) return null
  try {
    return window.localStorage.getItem(`${DISMISSED_KEY}:${userId}`)
  } catch {
    // Private browsing, or storage disabled. Showing the prompt is the safe
    // failure: it is advice, and it can be dismissed again.
    return null
  }
}

const LISTING_STATUS_STYLE: Record<ListingStatus, string> = {
  draft: 'bg-subtle text-muted',
  active: 'bg-emerald-100 text-emerald-700',
  under_offer: 'bg-amber-100 text-amber-700',
  sold: 'bg-brand-soft text-brand',
  withdrawn: 'bg-subtle text-muted',
}

const LISTING_STATUS_LABEL: Record<ListingStatus, string> = {
  draft: 'Draft',
  active: 'Active',
  under_offer: 'Under offer',
  sold: 'Sold',
  withdrawn: 'Withdrawn',
}

/** "Mar 14" — the calendar strip's date, without the year noise. */
function shortDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function daysAwayLabel(days: number): string {
  if (days <= 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  return `In ${days} days`
}

export default function DashboardPage() {
  const { user } = useAuth()
  const [completeness, setCompleteness] = useState<ProfileCompleteness | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(() => readDismissed(user?.id))

  // null = still loading, [] = loaded and empty, undefined = failed. The
  // three-way split is what lets each section say the right thing.
  const [designs, setDesigns] = useState<Design[] | null | undefined>(null)
  const [listings, setListings] = useState<Listing[] | null | undefined>(null)
  const [events, setEvents] = useState<CalendarEvent[] | null | undefined>(null)
  const [enquiries, setEnquiries] = useState<EnquiryRow[] | null | undefined>(null)
  const [enquirySummary, setEnquirySummary] = useState<EnquirySummary | null>(null)

  useEffect(() => {
    fetchProfileCompleteness()
      .then(setCompleteness)
      .catch(() => setCompleteness(null))
    fetchDesigns({ mine: '1' })
      .then((page) => setDesigns(page.results))
      .catch(() => setDesigns(undefined))
    fetchListings()
      .then((page) => setListings(page.results))
      .catch(() => setListings(undefined))
    // 90 days, not a tighter window: the seeded occasions are real holidays,
    // which cluster — a "next few weeks" strip is empty most of the year.
    fetchCalendarEvents({ within_days: '90' })
      .then(setEvents)
      .catch(() => setEvents(undefined))
    apiRequest<Paginated<EnquiryRow>>('/api/enquiries/')
      .then((page) => setEnquiries(page.results))
      .catch(() => setEnquiries(undefined))
    apiRequest<EnquirySummary>('/api/enquiries/summary/')
      .then(setEnquirySummary)
      .catch(() => setEnquirySummary(null))
  }, [])

  const signature = useMemo(
    () => (completeness ? signatureOf(completeness) : null),
    [completeness],
  )

  function dismiss() {
    if (signature === null || user === null) return
    setDismissed(signature)
    try {
      window.localStorage.setItem(`${DISMISSED_KEY}:${user.id}`, signature)
    } catch {
      // Dismissal just will not survive a reload. Not worth an error message.
    }
  }

  const showPrompt =
    completeness !== null && !completeness.is_complete && dismissed !== signature

  const recentDesigns = useMemo(
    () =>
      (designs ?? [])
        .slice()
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        .slice(0, 4),
    [designs],
  )

  /**
   * Listings with no design attached — the "you listed it, now market it"
   * nudge. Computed from the two lists already in hand rather than a
   * dedicated endpoint: both are one agent's own rows, small by nature.
   * Draft/withdrawn listings are excluded — there is nothing to promote yet
   * or any more — and sold stays, because "Just Sold" is marketing too.
   */
  const unmarketed = useMemo(() => {
    if (!listings) return []
    const marketed = new Set(
      (designs ?? []).map((design) => design.listing).filter(Boolean),
    )
    return listings
      .filter((listing) => listing.status !== 'draft' && listing.status !== 'withdrawn')
      .filter((listing) => !marketed.has(listing.id))
      .slice(0, 4)
  }, [listings, designs])

  const upcoming = useMemo(
    () => (events ?? []).filter((event) => !event.is_past).slice(0, 4),
    [events],
  )

  const recentEnquiries = useMemo(
    () => (enquiries ?? []).filter((row) => row.status !== 'spam').slice(0, 3),
    [enquiries],
  )

  const firstName = (user?.full_name || user?.email || '').split(/[\s@]/)[0]

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">
          {firstName ? `Welcome back, ${firstName}` : 'Dashboard'}
        </h1>
        <p className="mt-1 text-sm text-muted">
          Signed in as {user?.full_name || user?.email} &middot; {user?.role_display}
        </p>
      </div>

      {/* An offer, not a gate: dismissible, and nothing on the dashboard stops
          working while it is ignored. What it must not do is be the first time
          an agent hears about a gap at the moment they try to publish, which is
          why each missing field links straight to the screen that fixes it. */}
      {showPrompt && completeness && (
        <section className="rounded-panel border border-line bg-surface p-5 shadow-panel">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm font-medium">Complete your profile</h2>
              <p className="mt-1 text-xs text-muted">
                {completeness.ready_for_marketing
                  ? 'You have everything you need to export. These would round it out.'
                  : 'Optional for now — needed before you can export marketing material.'}
              </p>
            </div>
            <button
              type="button"
              onClick={dismiss}
              className="shrink-0 rounded-control px-2 py-1 text-xs font-medium text-muted transition hover:bg-hover hover:text-ink"
            >
              Dismiss
            </button>
          </div>

          <div className="mt-3 flex items-center gap-3">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-subtle">
              <div
                className={`h-full transition-all ${
                  completeness.ready_for_marketing ? 'bg-emerald-600' : 'bg-brand'
                }`}
                style={{ width: `${completeness.completion_percent}%` }}
              />
            </div>
            <span className="text-sm font-semibold">
              {completeness.completion_percent}%
            </span>
          </div>

          {completeness.missing_required.length > 0 && (
            <ul className="mt-4 flex flex-wrap gap-2">
              {completeness.missing_required.map((field) => (
                <li key={field.key}>
                  <Link
                    to={field.fix_path}
                    title={field.hint || undefined}
                    className="inline-block rounded-control border border-line px-2.5 py-1 text-xs font-medium transition hover:border-brand hover:bg-hover"
                  >
                    {field.label} →
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* Quick create: the four places a piece of marketing starts. Doorways,
          not features — a design cannot begin without picking a template, so
          the honest destination is the screen where that choice lives. */}
      <section>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <QuickAction
            to={TEMPLATES_HOME}
            Icon={IconTemplates}
            title="New design"
            hint="Start from a template"
          />
          <QuickAction
            to="/listings"
            Icon={IconListings}
            title="Market a listing"
            hint="Promote a property"
          />
          <QuickAction
            to="/calendar"
            Icon={IconCalendar}
            title="Seasonal post"
            hint="Holidays and occasions"
          />
          <QuickAction
            to="/brand-kit"
            Icon={IconBrandKit}
            title="Brand kit"
            hint="Logo, colours, fonts"
          />
        </ul>
      </section>

      {/* Recent designs — the single most likely reason an agent opened the
          app today is to finish what they started yesterday. */}
      <section>
        <SectionHeader title="Pick up where you left off" to={DESIGNS_HOME} linkLabel="All designs" />
        {designs === undefined && <SectionShrug>Couldn’t load your designs.</SectionShrug>}
        {designs === null && <SectionShrug>Loading…</SectionShrug>}
        {designs && recentDesigns.length === 0 && (
          <div className="rounded-panel border border-dashed border-line p-8 text-center">
            <p className="text-sm text-muted">Nothing started yet.</p>
            <Link
              to={TEMPLATES_HOME}
              className="mt-2 inline-block text-sm font-medium text-brand underline underline-offset-2"
            >
              Browse templates
            </Link>
          </div>
        )}
        {recentDesigns.length > 0 && (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {recentDesigns.map((design) => (
              <li key={design.id}>
                <Link
                  to={designEditorPath(design.id)}
                  title={`Open ${design.name}`}
                  className="group block overflow-hidden rounded-panel border border-line bg-surface shadow-panel transition hover:-translate-y-0.5 hover:border-brand/50 hover:shadow-pop"
                >
                  {/* The last export is the only true picture of a design this
                      list can get cheaply — same trade-off as the designs
                      panel, same wording when there is none. */}
                  <div className="flex h-28 items-center justify-center overflow-hidden bg-subtle">
                    {design.exports[0]?.image_url ? (
                      <img
                        src={design.exports[0].image_url}
                        alt=""
                        aria-hidden="true"
                        loading="lazy"
                        className="size-full object-cover"
                      />
                    ) : (
                      <span className="text-xs text-muted">Not exported yet</span>
                    )}
                  </div>
                  <div className="p-3">
                    <p className="truncate text-sm font-medium">{design.name}</p>
                    <p className="mt-0.5 truncate text-[11px] text-muted">
                      Edited {lastEdited(design.updated_at)}
                    </p>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Listings with nothing made for them. Silence here is success — the
          section disappears entirely once every listing has a design. */}
      {unmarketed.length > 0 && (
        <section>
          <SectionHeader title="Listings without marketing" to="/listings" linkLabel="All listings" />
          <ul className="divide-y divide-line overflow-hidden rounded-panel border border-line bg-surface shadow-panel">
            {unmarketed.map((listing) => (
              <li key={listing.id}>
                <div className="flex items-center gap-3 px-4 py-3">
                  <div className="size-10 shrink-0 overflow-hidden rounded-control bg-subtle">
                    {listing.photos[0]?.image_url && (
                      <img
                        src={listing.photos[0].image_url}
                        alt=""
                        aria-hidden="true"
                        loading="lazy"
                        className="size-full object-cover"
                      />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <Link
                      to={`/listings/${listing.id}`}
                      className="block truncate text-sm font-medium hover:text-brand"
                    >
                      {listing.full_address || listing.address}
                    </Link>
                    <p className="mt-0.5 text-[11px] text-muted">No designs yet</p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${LISTING_STATUS_STYLE[listing.status]}`}
                  >
                    {LISTING_STATUS_LABEL[listing.status]}
                  </span>
                  <Link
                    to={TEMPLATES_HOME}
                    className="shrink-0 rounded-control border border-line px-2.5 py-1.5 text-xs font-medium transition hover:border-brand hover:bg-brand hover:text-white"
                  >
                    Make a design
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid gap-8 lg:grid-cols-2">
        {/* Coming up — the calendar's next few occasions, so a Diwali post
            gets made before Diwali rather than the day after. */}
        <section>
          <SectionHeader title="Coming up" to="/calendar" linkLabel="Calendar" />
          {events === undefined && <SectionShrug>Couldn’t load the calendar.</SectionShrug>}
          {events === null && <SectionShrug>Loading…</SectionShrug>}
          {events && upcoming.length === 0 && (
            <SectionShrug>Nothing on the calendar in the next three months.</SectionShrug>
          )}
          {upcoming.length > 0 && (
            <ul className="divide-y divide-line overflow-hidden rounded-panel border border-line bg-surface shadow-panel">
              {upcoming.map((event) => (
                <li key={event.id}>
                  <Link
                    to="/calendar"
                    className="flex items-center gap-3 px-4 py-3 transition hover:bg-hover"
                  >
                    <span className="flex w-12 shrink-0 flex-col items-center rounded-control bg-subtle py-1.5 text-[10px] font-semibold uppercase text-muted">
                      {shortDate(event.date)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{event.name}</span>
                      <span className="mt-0.5 block text-[11px] text-muted">
                        {daysAwayLabel(event.days_away)}
                        {event.template_count > 0 &&
                          ` · ${event.template_count} template${event.template_count === 1 ? '' : 's'}`}
                      </span>
                    </span>
                    <IconArrowRight className="size-4 shrink-0 text-muted" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Recent enquiries — who wants to hear back. The new-count in the
            header is the number that makes an agent click through. */}
        <section>
          <SectionHeader
            title="Recent enquiries"
            badge={enquirySummary && enquirySummary.new > 0 ? `${enquirySummary.new} new` : undefined}
            to="/enquiries"
            linkLabel="All enquiries"
          />
          {enquiries === undefined && <SectionShrug>Couldn’t load enquiries.</SectionShrug>}
          {enquiries === null && <SectionShrug>Loading…</SectionShrug>}
          {enquiries && recentEnquiries.length === 0 && (
            <SectionShrug>No enquiries yet. They arrive from your public listing pages.</SectionShrug>
          )}
          {recentEnquiries.length > 0 && (
            <ul className="divide-y divide-line overflow-hidden rounded-panel border border-line bg-surface shadow-panel">
              {recentEnquiries.map((row) => (
                <li key={row.id}>
                  <Link
                    to="/enquiries"
                    className="flex items-start gap-3 px-4 py-3 transition hover:bg-hover"
                  >
                    <span className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand">
                      <IconEnquiries className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-baseline gap-2">
                        <span className="truncate text-sm font-medium">{row.name}</span>
                        {row.status === 'new' && (
                          <span className="shrink-0 rounded-full bg-brand px-1.5 py-px text-[9px] font-semibold uppercase text-white">
                            New
                          </span>
                        )}
                      </span>
                      {row.listing_address && (
                        <span className="mt-0.5 block truncate text-[11px] text-muted">
                          {row.listing_address}
                        </span>
                      )}
                      <span className="mt-0.5 block truncate text-xs text-muted">
                        {row.message}
                      </span>
                    </span>
                    <span className="shrink-0 text-[11px] text-muted">
                      {lastEdited(row.created_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}

function QuickAction({
  to,
  Icon,
  title,
  hint,
}: {
  to: string
  Icon: (props: { className?: string }) => React.ReactElement
  title: string
  hint: string
}) {
  return (
    <li>
      <Link
        to={to}
        className="group flex items-center gap-3 rounded-panel border border-line bg-surface p-4 shadow-panel transition hover:-translate-y-0.5 hover:border-brand/50 hover:shadow-pop"
      >
        <span className="flex size-10 shrink-0 items-center justify-center rounded-control bg-brand-soft text-brand transition group-hover:bg-brand group-hover:text-white">
          <Icon className="size-5" />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">{title}</span>
          <span className="block truncate text-[11px] text-muted">{hint}</span>
        </span>
      </Link>
    </li>
  )
}

function SectionHeader({
  title,
  badge,
  to,
  linkLabel,
}: {
  title: string
  badge?: string
  to: string
  linkLabel: string
}) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="flex items-baseline gap-2 text-sm font-semibold">
        {title}
        {badge && (
          <span className="rounded-full bg-brand px-2 py-px text-[10px] font-semibold text-white">
            {badge}
          </span>
        )}
      </h2>
      <Link
        to={to}
        className="shrink-0 text-xs font-medium text-brand underline-offset-2 hover:underline"
      >
        {linkLabel} →
      </Link>
    </div>
  )
}

/** One quiet line where a section's content would be. */
function SectionShrug({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-panel border border-dashed border-line p-6 text-center text-sm text-muted">
      {children}
    </p>
  )
}
