/** Types and calls for brokerages, agent profiles and brand kits. */

import { apiRequest } from '../lib/apiClient.ts'

export type DesignStyle = 'modern' | 'classic' | 'minimal' | 'bold' | 'luxury' | 'warm'

export const DESIGN_STYLES: { value: DesignStyle; label: string }[] = [
  { value: 'modern', label: 'Modern' },
  { value: 'classic', label: 'Classic' },
  { value: 'minimal', label: 'Minimal' },
  { value: 'bold', label: 'Bold' },
  { value: 'luxury', label: 'Luxury' },
  { value: 'warm', label: 'Warm' },
]

export type BrokerageSummary = {
  id: number
  name: string
  logo_url: string | null
  required_disclaimer: string
}

export type Brokerage = {
  id: number
  name: string
  logo_url: string | null
  required_disclaimer: string
  website: string
  phone: string
  agent_count: number
  created_at: string
  updated_at: string
}

export type AgentProfile = {
  id: number
  user: number
  user_email: string
  role: string
  brokerage: number | null
  brokerage_detail: BrokerageSummary | null
  name: string
  photo_url: string | null
  phone: string
  email: string
  job_title: string
  tagline: string
  created_at: string
  updated_at: string
}

export type BrandKit = {
  id: number
  agent: number | null
  brokerage: number | null
  owner_type: 'agent' | 'brokerage'
  owner_name: string
  name: string
  primary_color: string
  secondary_color: string
  accent_color: string
  heading_font: string
  body_font: string
  design_style: DesignStyle
  created_at: string
  updated_at: string
}

export type Paginated<T> = {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

/**
 * Build a multipart body, skipping keys whose value is null/undefined.
 *
 * A `File` is appended as-is so the browser streams it; everything else is
 * stringified. Empty file inputs are omitted rather than sent as "", which
 * DRF would otherwise try to parse as a file.
 */
export function toFormData(values: Record<string, unknown>): FormData {
  const formData = new FormData()
  for (const [key, value] of Object.entries(values)) {
    if (value === null || value === undefined) continue
    if (value instanceof File) {
      if (value.size > 0) formData.append(key, value)
      continue
    }
    formData.append(key, String(value))
  }
  return formData
}

// -- agent profile ----------------------------------------------------------

/** The caller's own profile. The server resolves it from the access token. */
export function fetchMyProfile(): Promise<AgentProfile> {
  return apiRequest<AgentProfile>('/api/agents/me/')
}

export function updateMyProfile(values: Record<string, unknown>): Promise<AgentProfile> {
  const hasFile = Object.values(values).some((value) => value instanceof File)
  return apiRequest<AgentProfile>('/api/agents/me/', {
    method: 'PATCH',
    body: hasFile ? toFormData(values) : values,
  })
}

export function fetchAgents(): Promise<Paginated<AgentProfile>> {
  return apiRequest<Paginated<AgentProfile>>('/api/agents/')
}

// -- brokerage --------------------------------------------------------------

export function fetchBrokerages(): Promise<Paginated<Brokerage>> {
  return apiRequest<Paginated<Brokerage>>('/api/brokerages/')
}

export function updateBrokerage(
  id: number,
  values: Record<string, unknown>,
): Promise<Brokerage> {
  const hasFile = Object.values(values).some((value) => value instanceof File)
  return apiRequest<Brokerage>(`/api/brokerages/${id}/`, {
    method: 'PATCH',
    body: hasFile ? toFormData(values) : values,
  })
}

// -- brand kit --------------------------------------------------------------

/** The caller's own kit; created with defaults on first call. */
export function fetchMyBrandKit(): Promise<BrandKit> {
  return apiRequest<BrandKit>('/api/brand-kits/mine/')
}

export function updateBrandKit(
  id: number,
  values: Partial<BrandKit>,
): Promise<BrandKit> {
  return apiRequest<BrandKit>(`/api/brand-kits/${id}/`, {
    method: 'PATCH',
    body: values,
  })
}

export function fetchBrandKits(): Promise<Paginated<BrandKit>> {
  return apiRequest<Paginated<BrandKit>>('/api/brand-kits/')
}

export function createBrandKit(values: Partial<BrandKit>): Promise<BrandKit> {
  return apiRequest<BrandKit>('/api/brand-kits/', { method: 'POST', body: values })
}
