/** Registration, and the Settings operations the CRUD endpoints do not cover. */

import { apiRequest } from '../lib/apiClient.ts'
import { setAccessToken } from '../auth/tokenStore.ts'
import type { Brokerage } from './profiles.ts'
import type { User } from '../auth/types.ts'

export type RegisterInput = {
  first_name: string
  last_name: string
  email: string
  password: string
  password_confirm: string
}

/**
 * Create an account. Name, email, password — nothing else.
 *
 * Uses the SAME endpoint the app has always had. The response carries an
 * access token and sets the httpOnly refresh cookie, so the new agent lands in
 * the dashboard rather than on a sign-in form they just implicitly passed.
 */
export async function registerAgent(
  input: RegisterInput,
): Promise<{ access: string; user: User }> {
  const data = await apiRequest<{ access: string; user: User }>('/api/auth/register/', {
    method: 'POST',
    body: input,
    // A 401 here means bad input, not an expired token — refreshing would be
    // pointless.
    skipAuthRefresh: true,
  })
  setAccessToken(data.access)
  return data
}

export type CompletenessField = {
  key: string
  label: string
  step: 'profile' | 'brokerage' | 'brand'
  step_label: string
  /** Route that fixes this field — resolved server-side, so callers don't
   *  each reinvent the mapping (and get the no-brokerage-yet case wrong). */
  fix_path: string
  present: boolean
  required_for_marketing: boolean
  hint: string
}

export type StepProgress = {
  label: string
  total: number
  present: number
  complete: boolean
}

/**
 * What is filled in and what is not. Advisory: an agent who never acts on it
 * keeps a perfectly working account. The export path is what insists.
 */
export type ProfileCompleteness = {
  completion_percent: number
  is_complete: boolean
  ready_for_marketing: boolean
  missing_required: CompletenessField[]
  missing_optional: CompletenessField[]
  by_step: Record<string, StepProgress>
}

export function fetchProfileCompleteness(): Promise<ProfileCompleteness> {
  return apiRequest<ProfileCompleteness>('/api/profile/completeness/')
}

export type BrokerageMatch = {
  id: number
  name: string
  logo_url: string | null
  agent_count: number
}

/** Search before creating, so two rows never end up describing one firm. */
export function searchBrokerages(search: string): Promise<BrokerageMatch[]> {
  return apiRequest<BrokerageMatch[]>(
    `/api/profile/brokerages/?search=${encodeURIComponent(search)}`,
  )
}

export function joinBrokerage(brokerageId: number): Promise<Brokerage> {
  return apiRequest<Brokerage>('/api/profile/brokerage/', {
    method: 'POST',
    body: { brokerage: brokerageId },
  })
}

export function createBrokerage(fields: {
  name: string
  required_disclaimer?: string
  phone?: string
  website?: string
  licence_number?: string
}): Promise<Brokerage> {
  return apiRequest<Brokerage>('/api/profile/brokerage/', {
    method: 'POST',
    body: { create: fields },
  })
}
