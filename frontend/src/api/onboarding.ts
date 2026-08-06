/** Agent registration and onboarding. */

import { apiRequest } from '../lib/apiClient.ts'
import { setAccessToken } from '../auth/tokenStore.ts'
import type { AgentProfile, Brokerage, BrandKit } from './profiles.ts'
import type { User } from '../auth/types.ts'

export type RegisterInput = {
  first_name: string
  last_name: string
  email: string
  password: string
  password_confirm: string
}

/**
 * Step 1. Uses the SAME endpoint the app has always had — onboarding does not
 * introduce a second way to create an account.
 *
 * The response carries an access token and sets the httpOnly refresh cookie,
 * so onboarding continues straight into step 2 without a second sign-in.
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

export type CompletionField = {
  key: string
  label: string
  step: 'profile' | 'brokerage' | 'brand'
  step_label: string
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

export type OnboardingStatus = {
  role: string
  has_profile: boolean
  profile: AgentProfile | null
  brokerage: Brokerage | null
  brand_kit: BrandKit | null
  completion_percent: number
  is_complete: boolean
  ready_for_marketing: boolean
  fields: CompletionField[]
  missing_required: CompletionField[]
  missing_optional: CompletionField[]
  by_step: Record<string, StepProgress>
}

export function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  return apiRequest<OnboardingStatus>('/api/onboarding/status/')
}

export type ProfileCompletion = Pick<
  OnboardingStatus,
  'completion_percent' | 'is_complete' | 'ready_for_marketing' | 'missing_required' | 'by_step'
>

export function fetchProfileCompletion(): Promise<ProfileCompletion> {
  return apiRequest<ProfileCompletion>('/api/onboarding/completion/')
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
    `/api/onboarding/brokerages/?search=${encodeURIComponent(search)}`,
  )
}

export function joinBrokerage(brokerageId: number): Promise<Brokerage> {
  return apiRequest<Brokerage>('/api/onboarding/brokerage/', {
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
  return apiRequest<Brokerage>('/api/onboarding/brokerage/', {
    method: 'POST',
    body: { create: fields },
  })
}

export function completeOnboarding(): Promise<OnboardingStatus> {
  return apiRequest<OnboardingStatus>('/api/onboarding/complete/', { method: 'POST' })
}
