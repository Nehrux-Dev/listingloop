import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  createDesign,
  fetchCalendarEvents,
  fetchEventTemplates,
  type CalendarEvent,
  type TemplateSummary,
} from '../api/templates.ts'
import { Alert } from '../components/FormControls.tsx'
import { ApiError } from '../lib/apiClient.ts'

/**
 * The content calendar: what is coming up, and what to post about it.
 *
 * Nothing here needs a property. That is the point — an agent between listings
 * still has to stay visible, and a Diwali card has nothing to do with a house.
 */
export default function ContentCalendarPage() {
  const navigate = useNavigate()
  const [events, setEvents] = useState<CalendarEvent[] | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [templates, setTemplates] = useState<TemplateSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [window, setWindow] = useState('180')

  useEffect(() => {
    setEvents(null)
    fetchCalendarEvents(window === 'all' ? undefined : { within_days: window })
      .then(setEvents)
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : 'Could not load the calendar.'),
      )
  }, [window])

  async function openEvent(event: CalendarEvent) {
    if (expanded === event.id) {
      setExpanded(null)
      return
    }
    setExpanded(event.id)
    setTemplates([])
    try {
      const result = await fetchEventTemplates(event.id)
      setTemplates(result.templates)
    } catch {
      setTemplates([])
    }
  }

  async function start(template: TemplateSummary, event: CalendarEvent) {
    setCreating(true)
    setError(null)
    try {
      const design = await createDesign({
        name: `${event.name} — ${new Date(event.date).getFullYear()}`,
        template: template.id,
        // No listing. The whole reason this page exists.
        listing: null,
        calendar_event: event.id,
      })
      void navigate(`/designs/${design.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start that design.')
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h1 className="text-xl font-semibold tracking-tight">Content calendar</h1>
          <p className="mt-1 text-sm text-slate-500">
            Seasonal posts to keep you visible between listings. None of these need a
            property attached.
          </p>
        </div>
        <select
          value={window}
          onChange={(event) => setWindow(event.target.value)}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="60">Next 60 days</option>
          <option value="180">Next 6 months</option>
          <option value="365">Next year</option>
          <option value="all">Everything scheduled</option>
        </select>
      </div>

      {error && <Alert kind="error">{error}</Alert>}
      {!events && !error && <p className="text-sm text-slate-500">Loading…</p>}

      {events && events.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">
          Nothing scheduled in this window.
        </div>
      )}

      {events && events.length > 0 && (
        <ul className="space-y-3">
          {events.map((event) => (
            <li
              key={event.id}
              className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm"
            >
              <button
                type="button"
                onClick={() => void openEvent(event)}
                className="flex w-full items-center gap-4 p-4 text-left transition hover:bg-slate-50"
              >
                <div className="flex size-14 shrink-0 flex-col items-center justify-center rounded-md bg-slate-900 text-white">
                  <span className="text-[10px] uppercase tracking-wide opacity-70">
                    {new Date(event.date).toLocaleDateString(undefined, { month: 'short' })}
                  </span>
                  <span className="text-lg font-semibold leading-none">
                    {new Date(event.date).getDate()}
                  </span>
                </div>

                <div className="min-w-0 flex-1">
                  <p className="font-medium text-slate-800">{event.name}</p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {event.days_away === 0
                      ? 'Today'
                      : `In ${event.days_away} day${event.days_away === 1 ? '' : 's'}`}
                    {' · '}
                    {event.template_count} template
                    {event.template_count === 1 ? '' : 's'}
                    {event.regions.length > 0 && ` · ${event.regions.join(', ')}`}
                  </p>
                  {event.needs_date_review && (
                    <p
                      className="mt-1 text-[11px] text-amber-700"
                      title="This date is maintained by hand rather than calculated"
                    >
                      This date moves each year — confirm it for your market before
                      scheduling.
                    </p>
                  )}
                </div>

                <span className="shrink-0 text-slate-400">
                  {expanded === event.id ? '−' : '+'}
                </span>
              </button>

              {expanded === event.id && (
                <div className="border-t border-slate-100 bg-slate-50 p-4">
                  {event.description && (
                    <p className="mb-3 text-xs text-slate-500">{event.description}</p>
                  )}
                  {templates.length === 0 ? (
                    <p className="text-sm text-slate-500">
                      No templates for this occasion yet.
                    </p>
                  ) : (
                    <ul className="grid gap-2 sm:grid-cols-2">
                      {templates.map((template) => (
                        <li key={template.id}>
                          <button
                            type="button"
                            disabled={creating}
                            onClick={() => void start(template, event)}
                            className="w-full rounded-md border border-slate-200 bg-white p-3 text-left transition hover:border-slate-400 disabled:opacity-60"
                          >
                            <p className="text-sm font-medium text-slate-800">
                              {template.name}
                            </p>
                            <p className="mt-0.5 text-xs text-slate-500">
                              {template.style_display}
                              {!template.requires_listing && ' · no listing needed'}
                            </p>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
