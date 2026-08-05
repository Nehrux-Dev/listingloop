/** Types and calls for the template library, designs and exports. */

import { apiRequest } from '../lib/apiClient.ts'
import type { ComplianceReport } from './compliance.ts'
import type { Paginated } from './profiles.ts'

export type TemplateCategory =
  | 'new_listing'
  | 'coming_soon'
  | 'open_house'
  | 'just_sold'
  | 'price_reduced'
  | 'leased'
  | 'agent_introduction'
  | 'testimonial'
  | 'market_update'
  | 'neighbourhood_guide'

export type TemplateStyle =
  | 'bold'
  | 'minimal'
  | 'luxury'
  | 'warm'
  | 'editorial'
  | 'classic'

/** Mirrors ElementPermission on the backend. */
export type ElementPermission = 'locked' | 'content_only' | 'styled' | 'free'

export type ElementType =
  | 'text'
  | 'image'
  | 'color_block'
  | 'logo'
  | 'badge'
  | 'divider'

export type Geometry = { x: number; y: number; width: number; height: number }

export type ElementConstraints = {
  allowed_colors?: string[]
  min_font_size_ratio?: number
  max_font_size_ratio?: number
  bounds?: Geometry
  max_length?: number
  required?: boolean
  max_scale?: number
}

export type TemplateElement = {
  id: number
  key: string
  label: string
  element_type: ElementType
  permission: ElementPermission
  /**
   * Which override fields the server will accept for this element. Supplied by
   * the API rather than inferred here, so the UI and the enforcement layer
   * cannot drift apart — the server still re-checks every write regardless.
   */
  editable_fields: string[]
  geometry: Geometry
  style_properties: Record<string, unknown>
  constraints: ElementConstraints
  content_source: string
  default_content: string
  z_index: number
}

export type TemplateSummary = {
  id: number
  name: string
  slug: string
  description: string
  category: TemplateCategory
  category_display: string
  style: TemplateStyle
  style_display: string
  element_count: number
  layout_definition: Record<string, unknown>
}

export type TemplateDetail = TemplateSummary & {
  elements: TemplateElement[]
  permission_map: Record<string, ElementPermission>
}

export type Facet = { value: string; label: string; count: number }
export type TemplateFacets = { categories: Facet[]; styles: Facet[] }

export type DesignExport = {
  id: number
  design: number
  dimension: string
  dimension_label: string
  export_format: 'png' | 'jpg'
  image_url: string | null
  width: number
  height: number
  bytes: number
  render_ms: number
  created_at: string
}

/** `{element_key: {field: value}}` — validated server-side on every write. */
export type Overrides = Record<string, Record<string, unknown>>

export type Design = {
  id: number
  name: string
  template: number
  template_detail: TemplateSummary
  agent: number
  listing: number | null
  listing_address: string | null
  overrides: Overrides
  exports: DesignExport[]
  created_at: string
  updated_at: string
}

export type ResolvedElement = {
  key: string
  label: string
  element_type: ElementType
  permission: ElementPermission
  constraints: ElementConstraints
  geometry: Geometry
  style: Record<string, unknown>
  content: string | null
  hidden: boolean
  overridden_fields: string[]
}

export type ResolvedDesign = {
  dimension: string
  width: number
  height: number
  elements: ResolvedElement[]
}

export type RenderDimension = {
  key: string
  label: string
  width: number
  height: number
  aspect: number
}

export const PERMISSION_LABELS: Record<ElementPermission, string> = {
  locked: 'Locked',
  content_only: 'Content only',
  styled: 'Content + style',
  free: 'Free',
}

export const PERMISSION_HINTS: Record<ElementPermission, string> = {
  locked: 'Set by the template and cannot be changed.',
  content_only: 'Swap the content. Position and styling are fixed.',
  styled: 'Swap the content and adjust colour and size within limits.',
  free: 'Move, resize and restyle within the area the template allows.',
}

// -- templates --------------------------------------------------------------

export function fetchTemplates(
  params?: Record<string, string>,
): Promise<Paginated<TemplateSummary>> {
  const query = params ? `?${new URLSearchParams(params).toString()}` : ''
  return apiRequest<Paginated<TemplateSummary>>(`/api/templates/${query}`)
}

export function fetchTemplate(id: number): Promise<TemplateDetail> {
  return apiRequest<TemplateDetail>(`/api/templates/${id}/`)
}

export function fetchTemplateFacets(): Promise<TemplateFacets> {
  return apiRequest<TemplateFacets>('/api/templates/facets/')
}

export function fetchRenderDimensions(): Promise<RenderDimension[]> {
  return apiRequest<RenderDimension[]>('/api/render-dimensions/')
}

// -- designs ----------------------------------------------------------------

export function fetchDesigns(params?: Record<string, string>): Promise<Paginated<Design>> {
  const query = params ? `?${new URLSearchParams(params).toString()}` : ''
  return apiRequest<Paginated<Design>>(`/api/designs/${query}`)
}

export function fetchDesign(id: number): Promise<Design> {
  return apiRequest<Design>(`/api/designs/${id}/`)
}

export function fetchResolvedDesign(id: number, dimension: string): Promise<ResolvedDesign> {
  return apiRequest<ResolvedDesign>(`/api/designs/${id}/resolved/?dimension=${dimension}`)
}

export function createDesign(payload: {
  name: string
  template: number
  listing?: number | null
  overrides?: Overrides
}): Promise<Design> {
  return apiRequest<Design>('/api/designs/', { method: 'POST', body: payload })
}

export function saveDesignOverrides(id: number, overrides: Overrides): Promise<Design> {
  return apiRequest<Design>(`/api/designs/${id}/`, {
    method: 'PATCH',
    body: { overrides },
  })
}

export function renameDesign(id: number, name: string): Promise<Design> {
  return apiRequest<Design>(`/api/designs/${id}/rename/`, {
    method: 'POST',
    body: { name },
  })
}

export function duplicateDesign(id: number, name?: string): Promise<Design> {
  return apiRequest<Design>(`/api/designs/${id}/duplicate/`, {
    method: 'POST',
    body: name ? { name } : {},
  })
}

export function deleteDesign(id: number): Promise<null> {
  return apiRequest<null>(`/api/designs/${id}/`, { method: 'DELETE' })
}

export type PreviewResult = {
  dimension: string
  width: number
  height: number
  render_ms: number
  image: string
}

export function previewDesign(id: number, dimension: string): Promise<PreviewResult> {
  return apiRequest<PreviewResult>(`/api/designs/${id}/preview/`, {
    method: 'POST',
    body: { dimension },
  })
}

/**
 * Export, subject to compliance.
 *
 * The response carries the compliance report either way: on success so
 * warnings are seen rather than passed over, and on a 409 so the agent is told
 * exactly which rule stopped them.
 */
export function exportDesign(
  id: number,
  dimensions: string[],
  format: 'png' | 'jpg',
): Promise<{ exports: DesignExport[]; compliance: ComplianceReport }> {
  return apiRequest(`/api/designs/${id}/export/`, {
    method: 'POST',
    body: { dimensions, export_format: format },
  })
}
