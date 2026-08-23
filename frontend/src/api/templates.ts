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

/**
 * A template element's type, as the *template* stores it. A design never sees
 * these: opening a template maps each one onto an `ElementType` below.
 */
export type TemplateElementType =
  | 'text'
  | 'image'
  | 'color_block'
  | 'logo'
  | 'badge'
  | 'divider'
  | 'static_graphic'

/**
 * What an element on a design's canvas is. Every one of these is an
 * independent, selectable, editable layer — there is no tier, no permission
 * and no "fixed by template". See document.py.
 */
export type ElementType =
  | 'text'
  | 'image'
  | 'shape'
  | 'line'
  | 'icon'
  | 'logo'
  | 'button'
  | 'background'

export const ELEMENT_TYPES: ElementType[] = [
  'text',
  'image',
  'shape',
  'line',
  'icon',
  'logo',
  'button',
  'background',
]

/** Types that draw an `<img>`. `background` does too, but only when it has a
 *  picture — check with `carriesImage`. */
export const IMAGE_TYPES: ElementType[] = ['image', 'logo', 'icon']

/** Types that draw type. A `button` is a shape with a label inside it. */
export const TEXT_TYPES: ElementType[] = ['text', 'button']

export function carriesImage(type: ElementType, content: string): boolean {
  if (IMAGE_TYPES.includes(type)) return true
  return type === 'background' && Boolean(content)
}

export function carriesText(type: ElementType): boolean {
  return TEXT_TYPES.includes(type)
}

/**
 * Position, size, angle and stacking order — the whole geometry of an element,
 * in one place.
 *
 * Fractions of the canvas, not pixels, so one design renders at Instagram
 * Post, Story, Facebook and LinkedIn without four stored layouts. Pixels are a
 * render-time projection; nothing writes them back.
 */
export type Transform = {
  x: number
  y: number
  width: number
  height: number
  /** Degrees. Always present — the server defaults it to 0 rather than
   *  omitting it, so a transform has one consistent shape. */
  rotation: number
  /** Higher paints later, i.e. nearer the viewer. */
  z_index: number
}

// Compatibility names for the older editor surfaces that still talk in
// geometry/permission terms while the API now stores a whole document.
export type Geometry = Transform

export type ElementPermission = 'locked' | 'content_only' | 'styled' | 'free'

export type ElementConstraints = {
  max_length?: number
  allowed_colors?: string[]
  min_font_size_ratio?: number
  max_font_size_ratio?: number
  bounds?: Geometry
}

export const PERMISSION_LABELS: Record<ElementPermission, string> = {
  locked: 'Locked',
  content_only: 'Content',
  styled: 'Styled',
  free: 'Free',
}

export const PERMISSION_HINTS: Record<ElementPermission, string> = {
  locked: 'Locked on the canvas. Unlock it from the properties panel to edit.',
  content_only: 'Content can be changed.',
  styled: 'Content and styling can be changed.',
  free: 'Fully editable.',
}

/** Which property/agent fact feeds an element's content. See PropertyField. */
export type PropertyFieldName = string

/**
 * One element of a design. The unit of everything: selection, the layers
 * panel, the properties panel, the canvas and the export all address this.
 */
export type DesignElement = {
  id: string
  /** The template element this was copied from, or null for one the agent
   *  added. What makes "reset this element" possible after any amount of
   *  renaming, moving, reordering and duplicating. */
  original_element_id: string | null
  type: ElementType
  /** Shown in the layers panel; renameable. */
  name: string
  /**
   * The ONLY thing that restricts editing, and the user sets it themselves.
   * Defaults to false on every element, including ones copied from a template.
   * A locked element still renders and still appears in the layers panel — it
   * just does not hit-test on the canvas.
   */
  locked: boolean
  visible: boolean
  transform: Transform
  /** Literal text, or a storage key for an image. Not what is displayed when
   *  the element is bound and unmodified — see `resolved_content`. */
  content: string
  /** The dotted data path behind a binding. Derived from `bound_to` server
   *  side, so the two can never disagree. */
  content_source: string
  /** The named property field this element is populated from, or null. A
   *  binding controls initial population and re-sync only; it restricts
   *  nothing. */
  bound_to: PropertyFieldName | null
  /** Set when the agent types over bound content. The binding is kept — that
   *  is what makes "sync to current data" still possible — but the agent's
   *  words win until this is cleared. */
  manually_overridden: boolean
  style: Record<string, unknown>
}

export type Overrides = Record<string, Record<string, unknown>>

export type ExtraElement = {
  id: string
  source_key?: string | null
  kind?: ElementType
  element_type: ElementType
  label: string
  geometry: Geometry
  style: Record<string, unknown>
  content: string
  hidden: boolean
  /** Optional because entries saved before the layers panel could lock an
   *  added element carry no key — absent means unlocked, as it always was. */
  locked?: boolean
  z_index: number
}

export type AddableElementKind = ElementType

export type TemplateElement = {
  id: number
  key: string
  label: string
  element_type: TemplateElementType
  geometry: { x: number; y: number; width: number; height: number; rotation?: number }
  style_properties: Record<string, unknown>
  content_source: string
  default_content: string
  z_index: number
  editable_fields: string[]
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
  /** False for seasonal and agent-led templates — those need no property —
   *  and for anything you imported, whatever its category: your own artwork
   *  carries its own words and pictures, so it opens without one. */
  requires_listing: boolean
  is_seasonal: boolean
  /** True for a template you imported from your own artwork. The shared
   *  Nehrux library is false, and is not yours to remove. */
  is_imported: boolean
  /** The rasterised source page for an imported template — a real picture of
   *  the design, not a style swatch. Null for library templates. */
  source_image_url: string | null
  /** Whether the editor offers to add new elements. A hint about how the
   *  layout is meant to be used, not a restriction on the elements a design
   *  already has — those are the agent's to change. */
  allows_added_elements: boolean
  /** The format this template was composed for — what the editor should
   *  open. A tall layout opened square reads as a crop. */
  default_dimension: string
  layout_definition: Record<string, unknown>
}

export type TemplateDetail = TemplateSummary & {
  elements: TemplateElement[]
}

export type CalendarEvent = {
  id: number
  name: string
  slug: string
  category: TemplateCategory
  category_display: string
  date: string
  days_away: number
  is_past: boolean
  description: string
  regions: string[]
  /** True for lunar/lunisolar dates, which are maintained by hand. */
  needs_date_review: boolean
  template_count: number
}

export function fetchCalendarEvents(
  params?: Record<string, string>,
): Promise<CalendarEvent[]> {
  const query = params ? `?${new URLSearchParams(params).toString()}` : ''
  return apiRequest<CalendarEvent[]>(`/api/calendar-events/${query}`)
}

export function fetchEventTemplates(
  id: number,
): Promise<{ event: CalendarEvent; templates: TemplateSummary[] }> {
  return apiRequest(`/api/calendar-events/${id}/templates/`)
}

export type Facet = { value: string; label: string; count: number }
export type TemplateFacets = {
  /** Occasion: New Listing, Just Sold, Diwali, ... */
  categories: Facet[]
  styles: Facet[]
  /** The format each template was composed for — Instagram Post, Story, ... */
  dimensions: Facet[]
}

/** Matches ExportFormat on the backend. PDF goes through a different
 *  Chromium pipeline in the renderer (page.pdf, not page.screenshot) but is
 *  the same request from here. */
export type ExportFormat = 'png' | 'jpg' | 'pdf'

export type DesignExport = {
  id: number
  design: number
  dimension: string
  dimension_label: string
  export_format: ExportFormat
  image_url: string | null
  width: number
  height: number
  bytes: number
  render_ms: number
  created_at: string
}

export type Design = {
  id: number
  name: string
  template: number
  template_detail: TemplateSummary
  agent: number
  listing: number | null
  listing_address: string | null
  calendar_event?: number | null
  /** The format this design's layout was composed or adapted for — set by
   *  the adapt endpoint. Empty means the template's own native format. The
   *  editor opens the design at this dimension when present, because an
   *  adapted layout only reads right at its target. */
  preferred_dimension?: string
  /** The design's own canvas — a deep copy of the template's elements, taken
   *  when the design was created and independently mutable ever since. */
  elements: DesignElement[]
  overrides?: Overrides
  extra_elements?: ExtraElement[]
  exports: DesignExport[]
  created_at: string
  updated_at: string
}

/**
 * An element as the canvas needs it: everything the design stores, plus the
 * two values only the server can work out.
 */
export type ResolvedElement = DesignElement & {
  /** What this element currently displays, after the binding is applied and
   *  images are turned into browser-usable data URIs. The canvas draws this;
   *  the properties panel edits `content`. */
  resolved_content: string | null
  /** The live value behind the binding, so the panel can show what "sync to
   *  current data" would put there. Null when the element is not bound. */
  bound_value: string | null
  key: string
  label: string
  element_type: ElementType
  permission: ElementPermission
  constraints: ElementConstraints
  geometry: Geometry
  hidden: boolean
  overridden_fields: string[]
  is_clone: boolean
  source_key: string | null
  z_index: number
}

export type ResolvedDesign = {
  dimension: string
  width: number
  height: number
  /** Fraction of the canvas reserved for platform chrome (Story's top/bottom
   *  overlays, mainly) — geometry is mapped into the area between these, not
   *  the raw canvas. Zero for formats with none. */
  safe_inset_top: number
  safe_inset_bottom: number
  background_color: string
  /** Back to front: index 0 paints first and sits at the bottom. */
  elements: ResolvedElement[]
}

export type RenderDimension = {
  key: string
  label: string
  width: number
  height: number
  aspect: number
  safe_inset_top: number
  safe_inset_bottom: number
}

/** What each element type is called in the layers panel and the add menu. */
export const ELEMENT_TYPE_LABELS: Record<ElementType, string> = {
  text: 'Text',
  image: 'Image',
  shape: 'Shape',
  line: 'Line',
  icon: 'Icon',
  logo: 'Logo',
  button: 'Button',
  background: 'Background',
}

/**
 * One bindable business fact, as `/api/designs/:id/property-data/` reports it.
 */
export type PropertyField = {
  name: PropertyFieldName
  label: string
  group: 'property' | 'agent' | 'brokerage'
  format: string
  is_image: boolean
  value: string | number | null
  /** Every element on this design populated from this field. */
  bound_element_ids: string[]
  /** Those of them the agent has typed over. Editing the field must not
   *  silently overwrite these. */
  overridden_element_ids: string[]
}

export type PropertyData = {
  has_listing: boolean
  fields: PropertyField[]
}

// -- templates --------------------------------------------------------------

export function fetchTemplates(
  params?: Record<string, string>,
): Promise<Paginated<TemplateSummary>> {
  const query = params ? `?${new URLSearchParams(params).toString()}` : ''
  return apiRequest<Paginated<TemplateSummary>>(`/api/templates/${query}`)
}

export function fetchTemplate(id: number): Promise<TemplateDetail> {
  return apiRequest<TemplateDetail>(`/api/templates/${id}/`).then((template) => ({
    ...template,
    elements: template.elements.map(withTemplateElementCompat),
  }))
}

export function fetchTemplateFacets(): Promise<TemplateFacets> {
  return apiRequest<TemplateFacets>('/api/templates/facets/')
}

// -- importing artwork into a template ---------------------------------------

export type ImportStatus = 'queued' | 'running' | 'succeeded' | 'failed'

/**
 * One attempt at turning an uploaded PDF or image into a template.
 *
 * The upload returns this immediately with `status: 'queued'` — extraction is
 * a minute-scale vision call that runs on a worker, so the request cannot wait
 * for it. Poll until `is_finished`, then read `template_detail`.
 */
export type TemplateImport = {
  id: number
  original_filename: string
  status: ImportStatus
  status_display: string
  /** True once the job reached `succeeded` or `failed` — stop polling. */
  is_finished: boolean
  /** Written to be shown to the user as-is. Empty unless status is 'failed'. */
  error: string
  template: number | null
  /** The finished template, inline, so the grid needs no second request at
   *  the moment it has something new to show. */
  template_detail: TemplateSummary | null
  element_count: number
  /** Elements the extractor could not describe with confidence, surfaced at
   *  upload time so a half-worked import stops looking like one that worked.
   *  Derived from the template's own elements, so fixing one in the editor
   *  clears it rather than leaving a stale complaint behind. */
  warnings: TemplateImportWarning[]
  created_at: string
  finished_at: string | null
}

export type TemplateImportWarning = {
  /** The element's label, so it can be found on the canvas. */
  element: string
  issue: string
  fill_type: string
}

/** Start an import. Resolves as soon as the file is stored and queued. */
export function importTemplate(input: {
  file: File
  name?: string
  category: TemplateCategory
  style: TemplateStyle
}): Promise<TemplateImport> {
  const body = new FormData()
  body.append('file', input.file)
  if (input.name) body.append('name', input.name)
  body.append('category', input.category)
  body.append('style', input.style)
  return apiRequest<TemplateImport>('/api/template-imports/', { method: 'POST', body })
}

/**
 * Move an imported template into the shared library — the Upload button.
 *
 * An import lands owned by whoever uploaded it, which makes it a private
 * draft only they can see. Clearing that owner server-side is what puts it in
 * front of every agent in every brokerage. Nehrux Admins only; the endpoint
 * returns 403 to anyone else regardless of what the UI offers.
 */
export function publishTemplateToLibrary(id: number): Promise<TemplateDetail> {
  return apiRequest<TemplateDetail>(`/api/templates/${id}/publish/`, { method: 'POST' })
}

/** What removing a template did. See `deleteTemplate`. */
export type TemplateRemoval = {
  /** True when designs already exist from it, so it was retired rather than
   *  deleted. Either way it is gone from every agent's gallery. */
  retired: boolean
  designs: number
  detail: string
}

/**
 * Take a template out of every agent's Templates panel.
 *
 * Two outcomes, and the API reports which: an unused template is deleted
 * outright (204); one that designs were made from is retired instead (200 with
 * a body), because `Design.template` is PROTECT and an agent's finished flyer
 * must not vanish because the library was tidied. Both remove it from the
 * gallery — the difference only matters for what the UI should say afterwards.
 *
 * Nehrux Admins only; the endpoint returns 403 to anyone else.
 */
export async function deleteTemplate(id: number): Promise<TemplateRemoval> {
  const result = await apiRequest<TemplateRemoval | null>(`/api/templates/${id}/`, {
    method: 'DELETE',
  })
  // 204 comes back as null — nothing referenced it, so it is simply gone.
  return result ?? { retired: false, designs: 0, detail: 'Template deleted.' }
}

export function fetchTemplateImport(id: number): Promise<TemplateImport> {
  return apiRequest<TemplateImport>(`/api/template-imports/${id}/`)
}

export function fetchTemplateImports(): Promise<Paginated<TemplateImport>> {
  return apiRequest<Paginated<TemplateImport>>('/api/template-imports/')
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
  return apiRequest<Design>(`/api/designs/${id}/`).then(withDesignCompat)
}

/**
 * Attach a property to a design that already exists.
 *
 * This is the whole of "Apply to design". Nothing about the elements is sent:
 * every element that was built to show a property field already carries the
 * binding, and the server resolves it at render time. So the price arrives in
 * the price slot and the photos arrive in the photo slots, while anything the
 * agent typed over themselves is marked `manually_overridden` and is left
 * exactly as they left it.
 */
export function attachListingToDesign(
  designId: number,
  listingId: number | null,
): Promise<Design> {
  return apiRequest<Design>(`/api/designs/${designId}/`, {
    method: 'PATCH',
    body: { listing: listingId },
  }).then(withDesignCompat)
}

export function fetchResolvedDesign(id: number, dimension: string): Promise<ResolvedDesign> {
  return apiRequest<ResolvedDesign>(
    `/api/designs/${id}/resolved/?dimension=${dimension}`,
  ).then(withResolvedDesignCompat)
}

/**
 * Open a template as a design — resuming yours if you already have one.
 *
 * NOT ALWAYS A CREATE, DESPITE THE NAME AND THE VERB
 * ---------------------------------------------------------------------------
 * The server hands back the design you already made from this template rather
 * than adding a near-duplicate, and answers 200 instead of 201 when it does.
 * That is the whole fix for the designs list filling with copies: opening a
 * template was the step that duplicated, and four different screens did it.
 *
 * Pass `fresh: true` to insist on a new one anyway — the "Start a fresh copy"
 * button, and nothing else.
 */
export function createDesign(payload: {
  name: string
  template: number
  listing?: number | null
  /** Ties a seasonal design to the occasion it was made for. Part of the
   *  server's identity check, so Diwali 2027 does not resume Diwali 2026. */
  calendar_event?: number | null
  /** Make a second design from this template on purpose. */
  fresh?: boolean
}): Promise<Design> {
  // The server copies the template's elements into the new design here. The
  // client deliberately does not send an `elements` array: a design that
  // started from whatever the browser happened to have cached would not be a
  // copy of the template, it would be a copy of a stale render of it.
  return apiRequest<Design>('/api/designs/', { method: 'POST', body: payload }).then(
    withDesignCompat,
  )
}

/**
 * Save the canvas — the whole document, in one request.
 *
 * One request and not a per-element patch stream, because the elements are
 * ordered and cross-referential: a reorder touches several z-indexes at once,
 * and a half-applied reorder is a visibly wrong canvas. Sending all of it
 * means the server's state after a save is exactly the client's, or the save
 * failed and neither moved.
 */
export function saveDesignDocument(
  id: number,
  elements: DesignElement[],
): Promise<Design> {
  return apiRequest<Design>(`/api/designs/${id}/`, {
    method: 'PATCH',
    body: { elements },
  }).then(withDesignCompat)
}

export async function saveDesignState(
  id: number,
  overrides: Overrides,
  extraElements: ExtraElement[],
): Promise<Design> {
  const current = await fetchDesign(id)
  const extraById = new Map(extraElements.map((element) => [element.id, element]))
  const baseElements = current.elements
    .filter((element) => element.original_element_id || !extraById.has(element.id))
    .map((element) => applyOverride(element, overrides[element.id] ?? {}))

  const addedElements = extraElements.map((element) => ({
    id: element.id,
    original_element_id: element.source_key ?? null,
    type: element.element_type,
    name: element.label,
    locked: element.locked ?? false,
    visible: !element.hidden,
    transform: { ...element.geometry, z_index: element.z_index },
    content: element.content,
    content_source: '',
    bound_to: null,
    manually_overridden: false,
    style: element.style,
  }))

  return saveDesignDocument(id, [...baseElements, ...addedElements])
}

export function renameDesign(id: number, name: string): Promise<Design> {
  return apiRequest<Design>(`/api/designs/${id}/rename/`, {
    method: 'POST',
    body: { name },
  }).then(withDesignCompat)
}

export function duplicateDesign(id: number, name?: string): Promise<Design> {
  return apiRequest<Design>(`/api/designs/${id}/duplicate/`, {
    method: 'POST',
    body: name ? { name } : {},
  }).then(withDesignCompat)
}

/**
 * Copy a design with its layout re-composed for another format.
 *
 * A copy, never an in-place change: one document renders at every dimension,
 * so re-laying it out for LinkedIn in place would wreck the Instagram
 * version. The server does the layout maths once (layout_adaptation.py) and
 * the result is an ordinary, fully editable design whose
 * `preferred_dimension` says where to open it.
 */
export function adaptDesign(id: number, dimension: string): Promise<Design> {
  return apiRequest<Design>(`/api/designs/${id}/adapt/`, {
    method: 'POST',
    body: { dimension },
  }).then(withDesignCompat)
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
  format: ExportFormat,
): Promise<{ exports: DesignExport[]; compliance: ComplianceReport }> {
  return apiRequest(`/api/designs/${id}/export/`, {
    method: 'POST',
    body: { dimensions, export_format: format },
  })
}

/**
 * What a fresh element of each kind looks like, straight from the server.
 *
 * Fetched rather than hardcoded so the canvas can create an element locally —
 * instantly, where the user clicked — without inventing its own idea of a
 * default button or text box that the server would then reject on save. One
 * definition (`document.BLANK_ELEMENTS`), two consumers.
 */
export type ElementKind = {
  kind: ElementType
  label: string
  blueprint: {
    name: string
    transform: Partial<Transform>
    content?: string
    content_source?: string
    style?: Record<string, unknown>
  }
}

const FREE_EDITABLE_FIELDS = [
  'text',
  'image_key',
  'hidden',
  'color',
  'background_color',
  'font_size_ratio',
  'font_weight',
  'font_style',
  'text_align',
  'object_fit',
  'object_position',
  'line_height',
  'letter_spacing_em',
  'opacity',
  'border_radius_ratio',
  'border_width_ratio',
  'border_color',
  'geometry',
  'z_index',
]

function withTemplateElementCompat(element: TemplateElement): TemplateElement {
  return { ...element, editable_fields: element.editable_fields ?? FREE_EDITABLE_FIELDS }
}

function toExtraElement(element: DesignElement): ExtraElement {
  return {
    id: element.id,
    source_key: element.original_element_id,
    kind: element.type,
    element_type: element.type,
    label: element.name,
    geometry: element.transform,
    style: element.style,
    content: element.content,
    hidden: !element.visible,
    // Without this an added element's lock silently vanished on reload.
    locked: element.locked,
    z_index: element.transform.z_index,
  }
}

function withDesignCompat(design: Design): Design {
  return {
    ...design,
    overrides: design.overrides ?? {},
    extra_elements:
      design.extra_elements ??
      design.elements.filter((element) => !element.original_element_id).map(toExtraElement),
  }
}

function withResolvedElementCompat(element: ResolvedElement): ResolvedElement {
  const permission: ElementPermission = element.locked ? 'locked' : 'free'
  return {
    ...element,
    key: element.key ?? element.id,
    label: element.label ?? element.name,
    element_type: element.element_type ?? element.type,
    permission: element.permission ?? permission,
    constraints: element.constraints ?? {},
    geometry: element.geometry ?? element.transform,
    hidden: element.hidden ?? !element.visible,
    overridden_fields: element.overridden_fields ?? [],
    is_clone: element.is_clone ?? !element.original_element_id,
    source_key: element.source_key ?? element.original_element_id,
    z_index: element.z_index ?? element.transform.z_index,
  }
}

function withResolvedDesignCompat(design: ResolvedDesign): ResolvedDesign {
  return { ...design, elements: design.elements.map(withResolvedElementCompat) }
}

function applyOverride(element: DesignElement, override: Record<string, unknown>): DesignElement {
  let next = { ...element, transform: { ...element.transform }, style: { ...element.style } }
  for (const [field, value] of Object.entries(override)) {
    if (field === 'geometry') next.transform = value as Transform
    else if (field === 'z_index') next.transform.z_index = Number(value)
    else if (field === 'hidden') next.visible = !value
    else if (field === 'name') next.name = String(value)
    else if (field === 'locked') next.locked = Boolean(value)
    else if (field === 'text' || field === 'image_key') {
      next.content = String(value)
      // Both count as typing over the binding. `image_key` has to, now that a
      // bound photo slot can also carry the template's own baked artwork: the
      // server resolves a live binding ahead of any stored key, so without
      // this flag an agent's chosen photo would be replaced by the listing's
      // on the very next render. See html_builder.resolve_content.
      next.manually_overridden = Boolean(next.bound_to)
    } else {
      next.style = { ...next.style, [field]: value }
    }
  }
  return next
}

export function fetchElementKinds(): Promise<ElementKind[]> {
  return apiRequest<ElementKind[]>('/api/design-element-kinds/')
}

/**
 * Add an element server-side and get it back.
 *
 * The canvas normally creates elements locally and saves them with the rest of
 * the document; this is here for the case where the client has no blueprint
 * cached yet.
 */
export function addDesignElement(
  designId: number,
  kind: ElementType,
): Promise<{ element: DesignElement; design: ResolvedDesign }> {
  return apiRequest(`/api/designs/${designId}/elements/add/`, {
    method: 'POST',
    body: { kind },
  })
}

/**
 * Put one element back the way its template has it.
 *
 * Matched on the server by `original_element_id`, so it survives every edit
 * that could have happened in between. Fails with 400 for an element the agent
 * added, which has no original to return to.
 */
export function resetDesignElement(
  designId: number,
  elementId: string,
): Promise<{ element: DesignElement; design: ResolvedDesign }> {
  return apiRequest(`/api/designs/${designId}/elements/${elementId}/reset/`, {
    method: 'POST',
  })
}

/**
 * Discard every edit and re-copy the whole canvas from the template.
 *
 * `confirm` is required by the server, not just by the dialog: a mis-wired
 * button or a replayed request must not be able to wipe a design on its own.
 */
export function resetDesign(designId: number): Promise<ResolvedDesign> {
  return apiRequest<ResolvedDesign>(`/api/designs/${designId}/reset/`, {
    method: 'POST',
    body: { confirm: true },
  }).then(withResolvedDesignCompat)
}

/** The business facts behind this design, and which elements show them. */
export function fetchPropertyData(designId: number): Promise<PropertyData> {
  return apiRequest<PropertyData>(`/api/designs/${designId}/property-data/`)
}

export type UploadedImage = {
  /** Goes straight into an image element's `content` — it is already the
   *  storage key the server expects there, not a URL. */
  image_key: string
  /** For immediate on-canvas display, before the design is saved and
   *  resolved fresh — the upload alone does not change the design. */
  url: string
}

/**
 * Upload a new image for use as an element's `image_key` override.
 *
 * Does not itself touch the design — same as picking an existing listing
 * photo, applying it is a separate PATCH the caller makes afterward.
 */
export function uploadDesignImage(designId: number, file: File): Promise<UploadedImage> {
  const body = new FormData()
  body.append('image', file)
  return apiRequest<UploadedImage>(`/api/designs/${designId}/upload-image/`, {
    method: 'POST',
    body,
  })
}
