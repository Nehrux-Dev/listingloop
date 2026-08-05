/**
 * Compliance API.
 *
 * Rules are read-only here: they are owned by whoever is accountable for them
 * and edited in the Django admin. An agent is checked against the rules, not
 * put in charge of them.
 */

import { apiRequest } from '../lib/apiClient.ts'

export type ResultStatus = 'pass' | 'fail' | 'skipped' | 'rule_error'
export type Severity = 'error' | 'warning' | 'info'

export type ComplianceResult = {
  rule_id: string
  description: string
  check_type: string
  severity: Severity
  status: ResultStatus
  message: string
  evidence: string[]
  /** True while the rule is still PENDING LEGAL REVIEW. */
  is_placeholder: boolean
  blocks_export: boolean
}

export type ComplianceReport = {
  subject_kind: string
  subject_label: string
  status: 'passed' | 'flagged' | 'failed'
  blocks_export: boolean
  error_count: number
  warning_count: number
  rule_error_count: number
  used_placeholder_rules: boolean
  results: ComplianceResult[]
}

export type ComplianceSummary = {
  total: number
  active: number
  pending_legal_review: number
  approved: number
  blocking: number
}

/** Check a design without exporting or storing anything. */
export function fetchDesignCompliance(designId: number): Promise<ComplianceReport> {
  return apiRequest<ComplianceReport>(`/api/designs/${designId}/compliance/`)
}

export function evaluateText(text: string): Promise<ComplianceReport> {
  return apiRequest<ComplianceReport>('/api/compliance/evaluate/', {
    method: 'POST',
    body: { text },
  })
}

export function evaluateVariant(variantId: number): Promise<ComplianceReport> {
  return apiRequest<ComplianceReport>('/api/compliance/evaluate/', {
    method: 'POST',
    body: { content_variant: variantId },
  })
}

export function fetchComplianceSummary(): Promise<ComplianceSummary> {
  return apiRequest<ComplianceSummary>('/api/compliance/rules/summary/')
}
