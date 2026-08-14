/**
 * Compliance flags for a design, shown before the agent can export.
 *
 * Two things this panel is careful about:
 *
 *   1. It distinguishes a *content* failure from a *rule* failure. "Your
 *      caption says X" and "this rule is broken and was not applied" are
 *      different problems with different owners, and conflating them teaches
 *      agents to ignore both.
 *   2. It says plainly when the rules are still provisional. The seeded set is
 *      PENDING LEGAL REVIEW, and an agent being blocked deserves to know the
 *      wording has not been signed off yet.
 */

import type { ComplianceReport, ComplianceResult } from '../api/compliance.ts'

const STATUS_STYLE: Record<string, string> = {
  passed: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  flagged: 'border-amber-200 bg-amber-50 text-amber-800',
  failed: 'border-rose-200 bg-rose-50 text-rose-800',
}

export function CompliancePanel({
  report,
  loading,
  collapsible,
}: {
  report: ComplianceReport | null
  loading?: boolean
  /**
   * Show the one-line verdict, and put the per-rule detail behind a
   * disclosure.
   *
   * For the export dialog, where the summary is what the decision turns on
   * ("1 warning — you can still export") and the rule-by-rule breakdown is
   * what you read only if that sentence gives you pause. The badge popover
   * leaves this off: it was opened precisely to see the detail.
   */
  collapsible?: boolean
}) {
  if (loading) {
    return <p className="text-xs text-slate-500">Checking compliance…</p>
  }
  if (!report) return null

  const failures = report.results.filter((result) => result.status === 'fail')
  const ruleErrors = report.results.filter((result) => result.status === 'rule_error')
  const passed = report.results.filter((result) => result.status === 'pass').length
  const hasDetail =
    failures.length > 0 || ruleErrors.length > 0 || report.used_placeholder_rules

  const detail = (
    <>
      {failures.length > 0 && (
        <ul className="space-y-1.5">
          {failures.map((result) => (
            <ResultRow key={result.rule_id} result={result} />
          ))}
        </ul>
      )}

      {ruleErrors.length > 0 && (
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
          <p className="text-xs font-medium text-slate-600">
            {ruleErrors.length} rule{ruleErrors.length === 1 ? '' : 's'} could not be
            applied
          </p>
          <p className="mt-0.5 text-[11px] text-slate-500">
            This is a problem with the rule itself, not with your content. It has been
            logged for an administrator.
          </p>
        </div>
      )}

      {report.used_placeholder_rules && (
        <p className="text-[11px] text-slate-500">
          Some of these checks are provisional and have not yet been through legal
          review.
        </p>
      )}
    </>
  )

  return (
    <div className="space-y-2">
      <div className={`rounded-md border px-3 py-2 text-sm ${STATUS_STYLE[report.status]}`}>
        {report.status === 'passed' && (
          <span>All {passed} compliance checks passed.</span>
        )}
        {report.status === 'flagged' && (
          <span>
            {report.warning_count} warning{report.warning_count === 1 ? '' : 's'} — you
            can still export.
          </span>
        )}
        {report.status === 'failed' && (
          <span>
            <strong>
              {report.error_count} issue{report.error_count === 1 ? '' : 's'} must be
              fixed before this can be exported.
            </strong>
          </span>
        )}
      </div>

      {hasDetail &&
        (collapsible ? (
          <details className="group">
            <summary className="cursor-pointer select-none text-[11px] font-medium text-slate-600 underline underline-offset-2 hover:text-slate-900">
              <span className="group-open:hidden">Show detail</span>
              <span className="hidden group-open:inline">Hide detail</span>
            </summary>
            <div className="mt-2 space-y-2">{detail}</div>
          </details>
        ) : (
          detail
        ))}
    </div>
  )
}

function ResultRow({ result }: { result: ComplianceResult }) {
  const isError = result.severity === 'error'
  return (
    <li
      className={`rounded-md border px-3 py-2 ${
        isError ? 'border-rose-200 bg-rose-50' : 'border-amber-200 bg-amber-50'
      }`}
    >
      <div className="flex items-start gap-2">
        <span
          className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
            isError ? 'bg-rose-600 text-white' : 'bg-amber-500 text-white'
          }`}
        >
          {isError ? 'Blocks export' : 'Warning'}
        </span>
        <div className="min-w-0">
          <p className={`text-sm ${isError ? 'text-rose-800' : 'text-amber-800'}`}>
            {result.message}
          </p>
          <p className="mt-0.5 text-[11px] text-slate-500">
            {result.description}
            {result.is_placeholder && ' · provisional rule'}
          </p>
        </div>
      </div>
    </li>
  )
}
