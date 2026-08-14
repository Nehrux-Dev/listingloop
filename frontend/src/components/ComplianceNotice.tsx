/**
 * Compliance flags, as a badge on the rail rather than a pinned panel.
 *
 * WHY THIS IS A CONTEXT AND NOT A PROP
 * ---------------------------------------------------------------------------
 * The thing that knows the flags is the design editor; the place the agent
 * looks for "is anything wrong" is the rail footer, which lives in the app
 * shell above the router outlet. Threading a report up through the layout
 * would mean AppLayout owning state it has no business owning, so the shell
 * opens a channel instead: the editor publishes what it has, the bell reads
 * it, and nothing in between has to care.
 *
 * The bell is deliberately blank when nothing publishes. On every page but
 * the editor there is no design to check, and a badge showing the last
 * design's warnings would be a lie — so the button falls back to the disabled
 * "coming soon" state it had before.
 *
 * WHAT THE COUNT MEANS
 * ---------------------------------------------------------------------------
 * Errors plus warnings: the flags raised against *this design's content*,
 * which are the ones the agent can act on. Rules that failed to run are not
 * counted — they are an administrator's problem, not the agent's — but they
 * are still listed inside, because silently dropping them would hide the fact
 * that a check did not happen.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import type { ComplianceReport } from '../api/compliance.ts'
import { CompliancePanel } from './CompliancePanel.tsx'
import { IconBell } from './icons.tsx'

/** What the current screen knows about compliance. `null` at the context
 *  level means nothing on screen is checking anything. */
type Notice = {
  report: ComplianceReport | null
  loading: boolean
}

type ContextValue = {
  notice: Notice | null
  publish: (notice: Notice | null) => void
}

const ComplianceNoticeContext = createContext<ContextValue | null>(null)

/** Flags the agent can act on. See the file header. */
export function flagCount(report: ComplianceReport | null): number {
  if (!report) return 0
  return report.error_count + report.warning_count
}

export function ComplianceNoticeProvider({ children }: { children: React.ReactNode }) {
  const [notice, setNotice] = useState<Notice | null>(null)
  const publish = useCallback((next: Notice | null) => setNotice(next), [])
  const value = useMemo(() => ({ notice, publish }), [notice, publish])

  return (
    <ComplianceNoticeContext.Provider value={value}>
      {children}
    </ComplianceNoticeContext.Provider>
  )
}

/**
 * Publish this screen's compliance report to the rail badge.
 *
 * Re-publishes whenever the report changes, which is what makes the count
 * live: the editor re-checks after every save, and the badge follows without
 * anything having to be refreshed. Unmounting clears the channel, so leaving
 * the editor takes the badge with it.
 */
export function usePublishCompliance(report: ComplianceReport | null, loading: boolean) {
  const publish = useContext(ComplianceNoticeContext)?.publish

  useEffect(() => {
    publish?.({ report, loading })
  }, [publish, report, loading])

  useEffect(() => () => publish?.(null), [publish])
}

/**
 * The rail's compliance bell: a count you can ignore, and a panel you can
 * open when you want the detail.
 */
export function ComplianceBell() {
  const notice = useContext(ComplianceNoticeContext)?.notice ?? null
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const closeOnOutside = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', closeOnOutside)
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      window.removeEventListener('mousedown', closeOnOutside)
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  // Nothing on screen is being checked, so the bell has nothing to report.
  if (!notice) {
    return (
      <button
        type="button"
        title="Notifications (coming soon)"
        aria-label="Notifications (coming soon)"
        disabled
        className={UTILITY_BUTTON}
      >
        <IconBell className="size-[15px]" />
      </button>
    )
  }

  const count = flagCount(notice.report)
  const blocking = (notice.report?.error_count ?? 0) > 0
  const label = notice.loading
    ? 'Checking compliance…'
    : count === 0
      ? 'Compliance — no warnings'
      : `Compliance — ${count} warning${count === 1 ? '' : 's'}`

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        title={label}
        aria-label={label}
        aria-expanded={open}
        className={UTILITY_BUTTON}
      >
        <IconBell className="size-[15px]" />
        {count > 0 && (
          <span
            className={`absolute -right-1 -top-1 flex h-[15px] min-w-[15px] items-center justify-center rounded-full px-[3px] text-[9px] font-bold leading-none text-white ${
              blocking ? 'bg-rose-600' : 'bg-amber-500'
            }`}
          >
            {count > 9 ? '9+' : count}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Compliance"
          className="absolute bottom-full left-0 z-50 mb-2 w-[300px] rounded-panel border border-line bg-surface p-3 shadow-pop"
        >
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-[12px] font-semibold text-ink">Compliance</p>
              <p className="mt-0.5 text-[11px] text-muted">
                Checked against the current rule set before export.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close"
              className="-mr-1 -mt-1 flex size-6 shrink-0 items-center justify-center rounded-control text-base leading-none text-muted transition hover:bg-hover hover:text-ink"
            >
              ×
            </button>
          </div>

          <div className="mt-2.5 max-h-[60vh] overflow-y-auto">
            {!notice.loading && !notice.report ? (
              <p className="text-xs text-muted">
                These checks could not be run just now. They will run again on the
                next save, and export re-checks regardless.
              </p>
            ) : (
              <CompliancePanel report={notice.report} loading={notice.loading} />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/** Matches the rail's other small utility buttons. */
const UTILITY_BUTTON =
  'relative flex size-6 items-center justify-center rounded-control text-muted transition hover:bg-hover hover:text-ink disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent'
