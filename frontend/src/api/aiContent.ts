/**
 * Generated-content API.
 *
 * Note what is NOT here: no OpenAI client, no API key, no model name the
 * browser chooses. The frontend asks our backend to generate; the backend
 * holds the key and talks to OpenAI. That is the only arrangement where the
 * key cannot be pulled out of a browser.
 */

import { apiRequest } from '../lib/apiClient.ts'
import type { Paginated } from './profiles.ts'

export type JobStatus = 'queued' | 'running' | 'ready' | 'failed'
export type ValidationStatus = 'pending' | 'passed' | 'flagged' | 'rejected'
export type ReviewStatus = 'draft' | 'approved' | 'rejected'

export type ValidationIssue = {
  code: string
  severity: 'error' | 'warning'
  message: string
  evidence: string
}

export type VariantKind =
  | 'instagram_caption'
  | 'facebook_caption'
  | 'linkedin_caption'
  | 'sharing_message'
  | 'property_description'
  | 'hashtags'

export type ContentVariant = {
  id: number
  generation: number
  kind: VariantKind
  kind_display: string
  /** Prose variants use `text`; the hashtag variant uses `items`. */
  text: string
  items: string[]
  rejected_text: string
  rejected_items: string[]
  /** Whichever of the above applies, joined — for display. */
  display_text: string
  validation_status: ValidationStatus
  validation_issues: ValidationIssue[]
  error_count: number
  warning_count: number
  review_status: ReviewStatus
  reviewed_at: string | null
  is_usable: boolean
  is_edited: boolean
  original_text: string
  edited_at: string | null
}

export type ContentLanguage = {
  code: string
  name: string
  rtl: boolean
  /**
   * False when the automatic fact check only partly understands this language.
   * Published rather than hidden — an agent picking a language deserves to
   * know before they pick it, not after.
   */
  fully_validated: boolean
  unchecked: string[]
}

export function fetchContentLanguages(): Promise<ContentLanguage[]> {
  return apiRequest<ContentLanguage[]>('/api/ai-content/languages/')
}

export type GeneratedContent = {
  id: number
  listing: number
  listing_address: string | null
  kind: string
  job_status: JobStatus
  error_message: string
  caption: string
  hashtags: string[]
  /** Populated instead of `caption` when the fact check rejected the response. */
  rejected_output: { caption?: string; hashtags?: string[] }
  validation_status: ValidationStatus
  validation_issues: ValidationIssue[]
  error_count: number
  warning_count: number
  review_status: ReviewStatus
  reviewed_at: string | null
  is_usable: boolean
  model_name: string
  prompt_version: string
  /** The exact facts the copy was written from — the basis for approving it. */
  prompt_facts: Record<string, unknown>
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  estimated_cost_usd: string
  duration_ms: number
  created_at: string
  updated_at: string
  variants: ContentVariant[]
  usable_variant_count: number
  language: string
  language_name: string
  /** True when the fact check could not fully read this language. */
  has_partial_validation: boolean
}

export type GenerationStatus = {
  id: number
  job_status: JobStatus
  validation_status: ValidationStatus
  review_status: ReviewStatus
  is_usable: boolean
  error_message: string
}

export type UsageTotals = {
  generations: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  estimated_cost_usd: string
  by_status: Record<string, number>
}

export function fetchContentForListing(listingId: number): Promise<Paginated<GeneratedContent>> {
  return apiRequest<Paginated<GeneratedContent>>(`/api/ai-content/?listing=${listingId}`)
}

export function fetchContent(id: number): Promise<GeneratedContent> {
  return apiRequest<GeneratedContent>(`/api/ai-content/${id}/`)
}

/** Small payload — this is polled on a timer. */
export function fetchContentStatus(id: number): Promise<GenerationStatus> {
  return apiRequest<GenerationStatus>(`/api/ai-content/${id}/status/`)
}

/**
 * The ONLY call that starts a generation. Returns 202 immediately with a
 * queued record; the OpenAI call happens in a worker.
 */
export function requestGeneration(
  listing: number,
  options: { tone?: string; languages?: string[] } = {},
): Promise<GeneratedContent[]> {
  // Returns one queued job per language — the endpoint fans out rather than
  // packing every language into a single response.
  const body: Record<string, unknown> = { listing }
  if (options.tone) body.tone = options.tone
  if (options.languages?.length) body.languages = options.languages
  return apiRequest<GeneratedContent[]>('/api/ai-content/generate/', {
    method: 'POST',
    body,
  })
}

export function reviewContent(
  id: number,
  decision: 'approved' | 'rejected',
): Promise<GeneratedContent> {
  return apiRequest<GeneratedContent>(`/api/ai-content/${id}/review/`, {
    method: 'POST',
    body: { decision },
  })
}

/** Apply one decision to every variant that can take it. Skips the rest. */
export function reviewAllVariants(
  id: number,
  decision: 'approved' | 'rejected',
): Promise<{ applied: number; skipped: number; generation: GeneratedContent }> {
  return apiRequest(`/api/ai-content/${id}/review-all/`, {
    method: 'POST',
    body: { decision },
  })
}

export function reviewVariant(
  id: number,
  decision: 'approved' | 'rejected',
): Promise<ContentVariant> {
  return apiRequest<ContentVariant>(`/api/ai-content-variants/${id}/review/`, {
    method: 'POST',
    body: { decision },
  })
}

/**
 * Rewrite one variant. The server re-validates and returns any issues, but an
 * agent's own words are advisory rather than blocking — see `is_usable`.
 */
export function editVariant(
  id: number,
  payload: { text?: string; items?: string[] },
): Promise<ContentVariant> {
  return apiRequest<ContentVariant>(`/api/ai-content-variants/${id}/edit/`, {
    method: 'POST',
    body: payload,
  })
}

export function fetchUsage(): Promise<UsageTotals> {
  return apiRequest<UsageTotals>('/api/ai-content/usage/')
}
