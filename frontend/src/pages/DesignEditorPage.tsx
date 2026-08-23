/**
 * The design editor.
 *
 * The canvas is the editor. Everything that used to be done through a column
 * of per-element form cards is now done by selecting an element and using the
 * contextual toolbar above the canvas or the properties panel beside it. The
 * old cards still exist, moved into an "Advanced" disclosure at the bottom —
 * they remain the only place a few rarely-touched things live, and deleting a
 * working surface outright would have been a downgrade for anyone using it.
 *
 * HOW EDITOR STATE FITS TOGETHER
 * ---------------------------------------------------------------------------
 * Three pieces of state, one derived view:
 *
 *   baseResolved   what the server last told us this design resolves to
 *                  (images turned into real URLs, content_source paths
 *                  followed). Only changes on load, dimension switch, save.
 *   draft          the working state: `overrides` for template elements plus
 *                  `extraElements` for the ones the agent added or
 *                  duplicated. This is what autosave sends.
 *   imagePreviews  URLs for images swapped in but not yet saved, since a
 *                  storage key isn't something a browser can display.
 *
 *   resolved       = template defaults + draft + those previews, recomputed
 *                    by useMemo whenever any of them change.
 *
 * Deriving the canvas rather than mutating it is what makes undo/redo exact:
 * history is a list of whole-draft snapshots, so stepping through it cannot
 * leave the canvas showing something the draft doesn't say. Because added
 * and deleted elements live in that same draft, they are undoable too.
 *
 * WHAT REACHES THE DATABASE
 * ---------------------------------------------------------------------------
 * Interaction is local. A drag updates `draft` at pointer rate and touches
 * no endpoint; the autosave timer restarts on every change and fires once
 * the pointer stops, sending overrides and extra elements in a single PATCH.
 * The one exception is adding an element, which asks the server to author
 * the entry so the "what is a circle" recipes live in exactly one place —
 * one request for one deliberate click, not one per mouse move.
 *
 * None of this can touch the master Template: the template API is read-only
 * for agents, and everything here writes to the agent's own Design row.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import {
  adaptDesign,
  addDesignElement,
  createDesign,
  deleteDesign,
  duplicateDesign,
  exportDesign,
  fetchDesign,
  fetchDesigns,
  fetchRenderDimensions,
  fetchResolvedDesign,
  fetchTemplate,
  previewDesign,
  renameDesign,
  saveDesignState,
  uploadDesignImage,
  type AddableElementKind,
  type Design,
  type ExportFormat,
  type ExtraElement,
  type Geometry,
  type Overrides,
  type RenderDimension,
  type ResolvedDesign,
  type ResolvedElement,
  type TemplateDetail,
  type TemplateElement,
  type TemplateSummary,
  type UploadedImage,
} from '../api/templates.ts'
import { fetchDesignCompliance, type ComplianceReport } from '../api/compliance.ts'
import { fetchListing, type ListingPhoto } from '../api/listings.ts'
import { fetchMyBrandKit, type BrandKit } from '../api/profiles.ts'
import { usePublishCompliance } from '../components/ComplianceNotice.tsx'
import Canvas from '../components/design-editor/Canvas.tsx'
import CanvasContextMenu, {
  type AlignAction,
  type LayerAction,
} from '../components/design-editor/ContextMenu.tsx'
import {
  getCopiedElement,
  getCopiedStyle,
  nextPasteStep,
  setCopiedElement,
  setCopiedStyle,
} from '../components/design-editor/elementClipboard.ts'
import {
  clampToCanvasLimits,
  geometryToPixelBox,
  pixelBoxToGeometry,
  type Box,
} from '../components/design-editor/geometry.ts'
import { type ShapePrimitive } from '../components/design-editor/shapeLibrary.ts'
import LeftPanel, {
  isImageElement,
  useLeftPanelTab,
} from '../components/design-editor/LeftPanel.tsx'
import EditorHeader from '../components/design-editor/EditorHeader.tsx'
import ExportDialog from '../components/design-editor/ExportDialog.tsx'
import PropertiesSidebar from '../components/design-editor/PropertiesSidebar.tsx'
import QuickActions from '../components/design-editor/QuickActions.tsx'
import TopToolbar from '../components/design-editor/TopToolbar.tsx'
import VariationsStrip from '../components/design-editor/VariationsStrip.tsx'
import { Alert } from '../components/FormControls.tsx'
import { ElementControls } from '../components/ElementControls.tsx'
import { ApiError } from '../lib/apiClient.ts'
import { DESIGNS_HOME, designEditorPath, listingsForDesignPath } from '../lib/routes.ts'

/** A field this design needs, and the screen that fills it in. */
type MissingField = {
  element: string
  label: string
  step: string
  step_label: string
  fix_path: string
}

/**
 * The whole editable state of a design, in one object.
 *
 * Undo/redo, dirty-checking and autosave all operate on this and nothing
 * else. Keeping added/duplicated elements in here alongside the overrides is
 * what makes "add an element" and "delete an element" undoable — while they
 * were saved through a separate endpoint the moment they changed, they were
 * invisible to history and to the unsaved-changes indicator.
 */
type EditorDraft = {
  overrides: Overrides
  extraElements: ExtraElement[]
}

const EMPTY_DRAFT: EditorDraft = { overrides: {}, extraElements: [] }

/**
 * An id for an element authored in the browser. The `added-`/`clone-` prefix
 * is what routes edits to the draft's own list (see `isExtraElement`), and
 * the server accepts any `[\w-]+` id. Not `crypto.randomUUID()`: that only
 * exists in secure contexts, and the dev stack is served over plain http
 * from a non-localhost hostname.
 */
function localElementId(prefix: 'added' | 'clone'): string {
  const hex = Array.from({ length: 12 }, () =>
    Math.floor(Math.random() * 16).toString(16),
  ).join('')
  return `${prefix}-${Date.now().toString(36)}-${hex}`
}

/** Idle time before an autosave fires. Long enough that a drag, a slider
 *  sweep or a burst of typing settles into one request rather than dozens;
 *  short enough that nobody wonders whether their work is safe. */
const AUTOSAVE_IDLE_MS = 1500

type SaveState = 'saved' | 'unsaved' | 'saving' | 'error'

/**
 * What "Copy style" carries between elements: presentation only. Geometry,
 * content and identity stay behind — pasting a headline's style onto a badge
 * should recolour and re-typeset the badge, not move or rewrite it.
 */
const COPYABLE_STYLE_FIELDS = [
  'color',
  'background_color',
  'font_family',
  'font_size_ratio',
  'font_weight',
  'font_style',
  'text_align',
  'line_height',
  'letter_spacing_em',
  'text_transform',
  'opacity',
  'border_radius_ratio',
  'border_width_ratio',
  'border_color',
  'object_fit',
  'object_position',
] as const

/** The state behind the right-click menu: where it opens, what it acts on
 *  (null = the empty-canvas menu), and — for a paste from empty canvas — the
 *  canvas-frame point to paste under. */
type ContextMenuState = {
  x: number
  y: number
  targetId: string | null
  pastePoint?: { x: number; y: number }
}

/** Key-order-independent signature, so undoing back to the saved state is
 *  recognised as "not dirty" even though the draft object was rebuilt. */
function draftSignature(draft: EditorDraft): string {
  const overrides = Object.keys(draft.overrides)
    .sort()
    .map((key) => [
      key,
      Object.keys(draft.overrides[key])
        .sort()
        .map((field) => [field, draft.overrides[key][field]]),
    ])
  // Order matters for extra elements (it is the paint order), so this is a
  // straight list, not a sorted one.
  const extras = draft.extraElements.map((entry) => [
    entry.id,
    entry.source_key,
    entry.kind ?? '',
    entry.label,
    entry.geometry,
    entry.z_index,
    entry.hidden,
    entry.locked ?? false,
    entry.content,
    Object.keys(entry.style)
      .sort()
      .map((key) => [key, entry.style[key]]),
  ])
  return JSON.stringify([overrides, extras])
}

/**
 * The canvas view: template defaults, then the draft on top.
 *
 * Geometry and style come from the *template element*, not from
 * `baseResolved`, so removing a field from the draft (Reset, or undoing past
 * an edit) reverts it immediately and exactly — `baseResolved` still carries
 * whatever was last SAVED and would show a stale value.
 *
 * Content is the one thing that can't be recomputed here: resolving
 * `listing.price` or turning a storage key into a data URI is server work.
 * So content comes from `baseResolved`, with the draft's own text and any
 * freshly-uploaded image URL layered over it.
 */
function deriveResolved(
  base: ResolvedDesign,
  templateElements: TemplateElement[],
  draft: EditorDraft,
  imagePreviews: Record<string, string>,
): ResolvedDesign {
  const templateByKey = new Map(templateElements.map((element) => [element.key, element]))

  // Template elements: rebuilt from the template's own defaults, then the
  // draft on top.
  const fromTemplate = base.elements
    .filter((element) => !element.is_clone)
    .map((element) => {
      const templateElement = templateByKey.get(element.key)
      const override = draft.overrides[element.key] ?? {}

      // A template's stored geometry is raw JSON and may predate rotation,
      // so default it after the spread rather than trusting the declared type.
      const templateGeometry = templateElement?.geometry
      const baseGeometry: Geometry = templateGeometry
        ? {
            ...templateGeometry,
            rotation: templateGeometry.rotation ?? 0,
            z_index: templateElement?.z_index ?? element.z_index,
          }
        : element.geometry

      let geometry: Geometry = baseGeometry
      let style: Record<string, unknown> = templateElement?.style_properties ?? element.style
      let content = element.content
      let resolvedContent = element.resolved_content
      let name = element.name
      let locked = element.locked
      let hidden = false
      let visible = element.visible
      let zIndex = templateElement?.z_index ?? element.z_index

      for (const [field, value] of Object.entries(override)) {
        if (field === 'geometry') geometry = value as Geometry
        else if (field === 'hidden') {
          // The override is authoritative in either direction — unhiding must
          // beat a server snapshot that still says invisible.
          hidden = Boolean(value)
          visible = !hidden
        }
        else if (field === 'name') name = String(value)
        else if (field === 'locked') locked = Boolean(value)
        else if (field === 'text') {
          content = String(value)
          // The canvas draws `resolved_content`; typed-over text must win
          // there too, or the edit only appears after a save round-trip.
          resolvedContent = String(value)
        } else if (field === 'z_index') zIndex = Number(value)
        else if (field === 'image_key') continue
        else style = { ...style, [field]: value }
      }

      const preview = imagePreviews[element.key]
      if (preview) {
        content = preview
        resolvedContent = preview
      }

      // `transform` and `geometry` are the same numbers under two names — the
      // canvas reads the former, the older panels the latter — so a drag that
      // updated only `geometry` left the canvas drawing the stale position.
      const transform = { ...geometry, z_index: zIndex }

      return {
        ...element,
        name,
        locked,
        visible,
        transform,
        geometry: transform,
        style,
        content,
        resolved_content: resolvedContent,
        hidden,
        z_index: zIndex,
      }
    })

  // Added and duplicated elements come from the draft, not from `base` —
  // the draft may hold one the server has never seen (just added) or be
  // missing one the server still has (just deleted, not yet autosaved).
  // `base` is consulted only for resolved image content, which is server
  // work: a storage key is not something a browser can display.
  const serverExtras = new Map(
    base.elements.filter((element) => element.is_clone).map((element) => [element.key, element]),
  )

  const fromDraft: ResolvedElement[] = draft.extraElements.map((entry) => {
    const server = serverExtras.get(entry.id)
    const isImage = ['image', 'logo', 'icon'].includes(entry.element_type)
    // What the canvas should display. An image needs the server to resolve a
    // storage key into a data URI, so a preview or the server's answer wins;
    // everything else displays its own literal content.
    const shown = isImage
      ? imagePreviews[entry.id] ?? server?.resolved_content ?? null
      : entry.content
    // The document shape and the compat shape together, like every element
    // that came through withResolvedElementCompat — the canvas reads
    // `id`/`transform`/`visible`, the older panels read `key`/`geometry`/
    // `hidden`, and an element carrying only one half crashes the other.
    const transform = { ...entry.geometry, z_index: entry.z_index }

    return {
      id: entry.id,
      original_element_id: entry.source_key ?? null,
      type: entry.element_type,
      name: entry.label,
      locked: entry.locked ?? false,
      visible: !entry.hidden,
      transform,
      content: entry.content,
      content_source: '',
      bound_to: null,
      manually_overridden: false,
      style: entry.style,
      resolved_content: shown,
      bound_value: null,
      key: entry.id,
      label: entry.label,
      element_type: entry.element_type,
      // An element the agent added or duplicated is theirs to move, restyle
      // and delete — the server treats it as FREE by construction.
      permission: 'free',
      constraints: server?.constraints ?? {},
      geometry: transform,
      hidden: entry.hidden,
      overridden_fields: [],
      is_clone: true,
      source_key: entry.source_key ?? null,
      z_index: entry.z_index,
    }
  })

  return { ...base, elements: [...fromTemplate, ...fromDraft] }
}

export default function DesignEditorPage() {
  const { id } = useParams<{ id: string }>()
  const designId = Number(id)
  const navigate = useNavigate()

  const [design, setDesign] = useState<Design | null>(null)
  const [template, setTemplate] = useState<TemplateDetail | null>(null)
  const [baseResolved, setBaseResolved] = useState<ResolvedDesign | null>(null)
  const [dimensions, setDimensions] = useState<RenderDimension[]>([])

  const [draft, setDraft] = useState<EditorDraft>(EMPTY_DRAFT)
  const [imagePreviews, setImagePreviews] = useState<Record<string, string>>({})
  /** Signature of what the server currently holds. Everything about "is
   *  there anything to save" is this compared against the live draft. */
  const [savedSignature, setSavedSignature] = useState(() => draftSignature(EMPTY_DRAFT))
  const [saveState, setSaveState] = useState<SaveState>('saved')
  const [saveError, setSaveError] = useState<string | null>(null)

  // Undo/redo: snapshots of the whole draft. `historyIndex` points at the
  // entry currently on screen; undo walks back, redo forward, and a fresh
  // edit truncates whatever was ahead.
  const [history, setHistory] = useState<EditorDraft[]>([EMPTY_DRAFT])
  const [historyIndex, setHistoryIndex] = useState(0)
  // Consecutive edits to the same field collapse into one history entry, so
  // dragging a slider or an element is a single undo rather than a hundred.
  // Cleared by commitEdits() on release, which is what ends the run.
  const openEditRef = useRef<string | null>(null)

  // Starts as the platform default and switches to the template's own native
  // format once loaded — see the effect below. A template composed tall must
  // not open square.
  // A placeholder until the template says what this design was drawn for —
  // see the resolved-design effect below, which waits for `dimensionPinned`
  // rather than fetching on this value.
  const [dimension, setDimension] = useState('instagram_post')
  const [dimensionPinned, setDimensionPinned] = useState(false)
  /** The dimension as of *now*, readable from inside an async call that
   *  captured an older one. A save started before a format switch finishes
   *  after it, and its response must not drag the canvas back. */
  const dimensionRef = useRef(dimension)
  const [zoom, setZoom] = useState(100)
  const [fitNonce, setFitNonce] = useState(0)
  const [preview, setPreview] = useState<string | null>(null)
  const [previewMs, setPreviewMs] = useState<number | null>(null)
  const [brandKit, setBrandKit] = useState<BrandKit | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  /** The full properties panel no longer opens itself on selection — the
   *  `Position` button in the docked toolbar (and the pill's ⋯) toggles it,
   *  the way Canva's Position panel works. Sticky across selections: opened
   *  for one element, it stays open for the next. */
  const [propertiesOpen, setPropertiesOpen] = useState(false)
  const [listingPhotos, setListingPhotos] = useState<ListingPhoto[]>([])
  const [uploadingImage, setUploadingImage] = useState(false)
  const [leftTab, setLeftTab] = useLeftPanelTab()
  const [uploads, setUploads] = useState<UploadedImage[]>([])
  const [addingElement, setAddingElement] = useState(false)
  const [adapting, setAdapting] = useState(false)
  /** Sibling designs built from the same template — the bottom strip.
   *  Not pages: each is its own design with its own overrides and its own
   *  export. See VariationsStrip for why the distinction matters. */
  const [variations, setVariations] = useState<Design[]>([])

  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [exportDims, setExportDims] = useState<string[]>(['instagram_post'])
  const [exportFormat, setExportFormat] = useState<ExportFormat>('png')
  const [compliance, setCompliance] = useState<ComplianceReport | null>(null)
  const [notReady, setNotReady] = useState<MissingField[]>([])
  const [checkingCompliance, setCheckingCompliance] = useState(true)
  /** Export is a dialog, not a column. It is also where the compliance flags
   *  are made unavoidable — see ExportDialog. */
  const [exportOpen, setExportOpen] = useState(false)
  /** The two secondary surfaces, off by default and toggled from the ⋯ menu. */
  const [variationsOpen, setVariationsOpen] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  /** The template being opened from the rail's grid, so its tile can say so. */
  const [pickingTemplate, setPickingTemplate] = useState<number | null>(null)

  const isExtraElement = useCallback(
    (key: string) => key.startsWith('added-') || key.startsWith('clone-'),
    [],
  )

  const resolved = useMemo(() => {
    if (!baseResolved || !template) return null
    return deriveResolved(baseResolved, template.elements, draft, imagePreviews)
  }, [baseResolved, template, draft, imagePreviews])

  function selectedElementFor(key: string | null): ResolvedElement | null {
    if (!key || !resolved) return null
    return resolved.elements.find((element) => element.key === key) ?? null
  }
  const selectedElement = selectedElementFor(selectedKey)

  const dirty = draftSignature(draft) !== savedSignature

  // The "In this design" swatch row: every literal colour the canvas is
  // currently using, in paint order. Derived, never stored — it can't drift.
  const documentColors = useMemo(() => {
    if (!resolved) return []
    const seen = new Set<string>()
    for (const element of resolved.elements) {
      for (const key of ['background_color', 'color', 'border_color', 'dot_color']) {
        const candidate = element.style?.[key]
        if (typeof candidate === 'string' && /^#[0-9A-Fa-f]{6}$/.test(candidate)) {
          seen.add(candidate.toUpperCase())
        }
      }
    }
    return [...seen].slice(0, 12)
  }, [resolved])

  const checkCompliance = useCallback(async () => {
    setCheckingCompliance(true)
    try {
      setCompliance(await fetchDesignCompliance(designId))
    } catch {
      setCompliance(null)
    } finally {
      setCheckingCompliance(false)
    }
  }, [designId])

  // Split from the resolved-design load below on purpose: this one only
  // depends on designId, not dimension. Switching the Instagram Post/Story/
  // Facebook/LinkedIn tab must not re-run it — it resets `overrides` from the
  // server, which would silently throw away unsaved edits.
  const loadDesign = useCallback(async () => {
    try {
      const loaded = await fetchDesign(designId)
      setDesign(loaded)
      const initial: EditorDraft = {
        overrides: loaded.overrides ?? {},
        extraElements: loaded.extra_elements ?? [],
      }
      setDraft(initial)
      setSavedSignature(draftSignature(initial))
      setSaveState('saved')
      setHistory([initial])
      setHistoryIndex(0)
      historyIndexRef.current = 0
      openEditRef.current = null
      setTemplate(await fetchTemplate(loaded.template))
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not open this design.')
    }
  }, [designId])

  useEffect(() => {
    void loadDesign()
  }, [loadDesign])

  // Open in the format the design was composed for, once — after that the
  // dimension tabs are the agent's to control. An adapted copy carries its
  // own `preferred_dimension` and must win over the template's native format:
  // its layout only reads right at the format it was adapted to.
  //
  // Pinned as soon as the template is known, even when it names no format,
  // because the resolved-design load below waits on this: leaving it false
  // for a template without a `default_dimension` would mean the canvas never
  // loaded at all.
  useEffect(() => {
    if (dimensionPinned || !template || !design) return
    const composedFor = design.preferred_dimension || template.default_dimension
    if (composedFor) setDimension(composedFor)
    setDimensionPinned(true)
  }, [template, design, dimensionPinned])

  useEffect(() => {
    dimensionRef.current = dimension
  }, [dimension])

  /**
   * Load the resolved canvas — but not before the dimension is settled, and
   * never letting an older response overwrite a newer one.
   *
   * `dimension` starts at a placeholder, because the format a design opens at
   * belongs to its template and the template has not loaded on first render.
   * Fetching on that placeholder issued a request for the wrong format, and
   * the switch to the template's own issued a second; with no cancellation,
   * whichever landed last was the one that stuck. When the placeholder won,
   * an A4 flyer was laid out on a 1080x1080 canvas.
   *
   * That is not a harmless rescale. Geometry is fractional, so widths scale
   * by canvas width and heights by canvas height — but font size scales by
   * min(width, height). Squaring a 1414x2000 page shrinks the type to 76%
   * while shrinking the box holding it to 54%, so the text outgrows its box,
   * `overflow:hidden` cuts it off, and what survives collides with whatever
   * sits beneath it.
   *
   * Waiting on `dimensionPinned` means the wrong request is never sent at
   * all; the stale flag covers the reorderings that remain, such as switching
   * format twice before the first response arrives.
   */
  useEffect(() => {
    if (!dimensionPinned) return
    let stale = false
    void (async () => {
      try {
        const fresh = await fetchResolvedDesign(designId, dimension)
        if (!stale) setBaseResolved(fresh)
      } catch (error) {
        if (stale) return
        setLoadError(error instanceof ApiError ? error.message : 'Could not open this design.')
      }
    })()
    return () => {
      stale = true
    }
  }, [designId, dimension, dimensionPinned])

  useEffect(() => {
    void checkCompliance()
  }, [checkCompliance])

  // Hand the current report to the rail's compliance bell. The checks run
  // exactly as often as they did when this was a pinned panel — only where
  // the result is shown has changed.
  usePublishCompliance(compliance, checkingCompliance)

  useEffect(() => {
    fetchRenderDimensions().then(setDimensions).catch(() => setDimensions([]))
  }, [])

  const loadVariations = useCallback(
    (templateId: number) => {
      fetchDesigns({ template: String(templateId) })
        .then((page) => setVariations(page.results))
        .catch(() => setVariations([]))
    },
    [],
  )

  useEffect(() => {
    if (!design?.template) return
    loadVariations(design.template)
  }, [design?.template, loadVariations])

  useEffect(() => {
    // Needed on-canvas to resolve `@accent_color`-style brand references the
    // same way the renderer does — see ElementLayer's resolveColor(). Not
    // fatal if it fails: elements just fall back to the token's default.
    fetchMyBrandKit().then(setBrandKit).catch(() => setBrandKit(null))
  }, [])

  useEffect(() => {
    // The image-replace picker's "choose from this listing" option — only
    // meaningful when the design actually has a listing attached.
    if (!design?.listing) {
      setListingPhotos([])
      return
    }
    fetchListing(design.listing)
      .then((listing) => setListingPhotos(listing.photos))
      .catch(() => setListingPhotos([]))
  }, [design?.listing])

  /**
   * The authoritative history position.
   *
   * A ref rather than just the `historyIndex` state because a run of edits
   * can fire several times before React re-renders, and each one needs to see
   * where the previous one left off — a state closure would still be showing
   * the position from before the run started.
   */
  const historyIndexRef = useRef(0)

  /** Records a new draft in history, collapsing a run of edits to the same
   *  field into the entry already on top. */
  const pushHistory = useCallback((next: EditorDraft, editId: string | null) => {
    // Decided BEFORE openEditRef is reassigned. Reading the ref inside the
    // setState updaters below would always see the value just written and so
    // always coalesce — which silently kept the history one entry long and
    // left Undo permanently disabled.
    const coalesce = editId !== null && openEditRef.current === editId
    openEditRef.current = editId

    setHistory((current) => {
      const truncated = current.slice(0, historyIndexRef.current + 1)
      if (!coalesce) return [...truncated, next]
      const replaced = [...truncated]
      replaced[replaced.length - 1] = next
      return replaced
    })

    if (!coalesce) {
      historyIndexRef.current += 1
      setHistoryIndex(historyIndexRef.current)
    }
  }, [])

  const goToHistory = useCallback(
    (target: number) => {
      historyIndexRef.current = target
      setHistoryIndex(target)
      setDraft(history[target])
      openEditRef.current = null
    },
    [history],
  )

  /** The one way the draft changes. Every edit in the editor lands here, so
   *  every edit is in history, marks the design unsaved, and gets autosaved. */
  const applyDraft = useCallback(
    (next: EditorDraft, editId: string | null) => {
      setMessage(null)
      setDraft(next)
      pushHistory(next, editId)
    },
    [pushHistory],
  )

  function changeField(elementKey: string, field: string, value: unknown) {
    const editId = `${elementKey}:${field}`

    if (isExtraElement(elementKey)) {
      // An added or duplicated element is edited in place in the draft's own
      // list — same history, same autosave, same undo as everything else.
      applyDraft(
        {
          ...draft,
          extraElements: draft.extraElements.map((entry) => {
            if (entry.id !== elementKey) return entry
            if (field === 'geometry') return { ...entry, geometry: value as Geometry }
            if (field === 'z_index') return { ...entry, z_index: Number(value) }
            if (field === 'hidden') return { ...entry, hidden: Boolean(value) }
            if (field === 'name') return { ...entry, label: String(value) }
            if (field === 'locked') return { ...entry, locked: Boolean(value) }
            if (field === 'text' || field === 'image_key') {
              return { ...entry, content: String(value) }
            }
            return { ...entry, style: { ...entry.style, [field]: value } }
          }),
        },
        editId,
      )
      return
    }

    applyDraft(
      {
        ...draft,
        overrides: {
          ...draft.overrides,
          [elementKey]: { ...(draft.overrides[elementKey] ?? {}), [field]: value },
        },
      },
      editId,
    )
  }

  /** Ends the current run of same-field edits, so the next one starts a new
   *  undo entry. Called on slider release, drag end and textarea blur. */
  function commitEdits() {
    openEditRef.current = null
  }

  function clearElement(elementKey: string) {
    const nextOverrides = { ...draft.overrides }
    delete nextOverrides[elementKey]
    applyDraft({ ...draft, overrides: nextOverrides }, null)
    setImagePreviews((current) => {
      const remaining = { ...current }
      delete remaining[elementKey]
      return remaining
    })
    commitEdits()
  }

  function undo() {
    if (historyIndex <= 0) return
    goToHistory(historyIndex - 1)
  }

  function redo() {
    if (historyIndex >= history.length - 1) return
    goToHistory(historyIndex + 1)
  }

  function startTextEdit(elementKey: string) {
    setSelectedKey(elementKey)
    setEditingKey(elementKey)
  }

  function commitTextEdit(elementKey: string, text: string) {
    changeField(elementKey, 'text', text)
    commitEdits()
    setEditingKey(null)
  }

  function cancelTextEdit() {
    setEditingKey(null)
  }

  function replaceImage(elementKey: string, imageKey: string, previewUrl: string) {
    changeField(elementKey, 'image_key', imageKey)
    commitEdits()
    if (previewUrl) {
      setImagePreviews((current) => ({ ...current, [elementKey]: previewUrl }))
    }
  }

  async function uploadAndReplaceImage(elementKey: string, file: File) {
    setUploadingImage(true)
    try {
      const uploaded = await uploadDesignImage(designId, file)
      setUploads((current) => [uploaded, ...current])
      replaceImage(elementKey, uploaded.image_key, uploaded.url)
    } catch (error) {
      setErrors((current) => ({
        ...current,
        [elementKey]: error instanceof ApiError ? error.message : 'Could not upload this image.',
      }))
    } finally {
      setUploadingImage(false)
    }
  }

  /** Upload without applying — the Uploads tab collects images first and
   *  drops them into an element afterwards. */
  async function uploadToLibrary(file: File) {
    setUploadingImage(true)
    setErrors({})
    try {
      const uploaded = await uploadDesignImage(designId, file)
      setUploads((current) => [uploaded, ...current])
      // If an image element happens to be selected, put it straight in —
      // uploading with a target chosen almost always means "use this here".
      if (selectedKey && isImageElement(selectedElementFor(selectedKey))) {
        replaceImage(selectedKey, uploaded.image_key, uploaded.url)
      }
    } catch (error) {
      setErrors({
        detail: error instanceof ApiError ? error.message : 'Could not upload this image.',
      })
    } finally {
      setUploadingImage(false)
    }
  }

  /**
   * Add an element.
   *
   * The server authors the entry — one request, for a discrete action, not
   * per mouse move — so the recipes for what a "circle" or a "badge" is stay
   * defined in exactly one place. The entry then joins the local draft like
   * any other edit, which is what makes adding undoable.
   */
  async function addElement(kind: AddableElementKind) {
    setAddingElement(true)
    setErrors({})
    try {
      await addDesignElement(designId, kind)
      const fresh = await fetchDesign(designId)
      setDesign(fresh)
      const created = (fresh.extra_elements ?? [])[(fresh.extra_elements ?? []).length - 1]
      if (!created) return
      applyDraft({ ...draft, extraElements: [...draft.extraElements, created] }, null)
      commitEdits()
      // It is on top and almost certainly the thing about to be edited.
      setSelectedKey(created.id)
      setBaseResolved(await fetchResolvedDesign(designId, dimension))
    } catch (error) {
      setErrors({
        detail: error instanceof ApiError ? error.message : 'Could not add that element.',
      })
    } finally {
      setAddingElement(false)
    }
  }

  /**
   * Place a shape from the Elements panel's local library.
   *
   * Created locally, unlike `addElement` above: a drop has a position that
   * must appear under the pointer immediately, and the four shape recipes
   * differ only in style — which the server's per-type blueprint endpoint
   * cannot express (templates.ts documents local creation as the normal
   * path). The entry joins `draft.extraElements` through `applyDraft`, so it
   * is selectable at once, undoable, and persisted by the same autosave PATCH
   * as every other edit — there is no separate save path for it.
   *
   * `geometry` comes from Canvas's drop handler (already normalized); a click
   * on the card passes none and the shape lands centred on the canvas.
   */
  function addShapeElement(shape: ShapePrimitive, geometry?: Box) {
    if (!resolved) return
    const scaleRef = Math.min(resolved.width, resolved.height)
    const width = shape.width * scaleRef
    const height = shape.height * scaleRef
    const placed =
      geometry ??
      clampToCanvasLimits(
        pixelBoxToGeometry(
          {
            left: (resolved.width - width) / 2,
            top: (resolved.height - height) / 2,
            width,
            height,
          },
          0,
          resolved,
        ),
      )
    // On top of everything, capped at the document's own z ceiling.
    const topZ = Math.min(
      1000,
      resolved.elements.reduce((highest, element) => Math.max(highest, element.z_index), 0) + 1,
    )
    const entry: ExtraElement = {
      id: localElementId('added'),
      source_key: null,
      kind: shape.type,
      element_type: shape.type,
      label: shape.label,
      geometry: { ...placed, z_index: topZ },
      style: { ...shape.style },
      content: '',
      hidden: false,
      z_index: topZ,
    }
    applyDraft({ ...draft, extraElements: [...draft.extraElements, entry] }, null)
    commitEdits()
    // It is on top and almost certainly the thing about to be restyled.
    setSelectedKey(entry.id)
  }

  /** Local: the element leaves the draft, and the next autosave is what
   *  actually removes it server-side. Undo brings it straight back. */
  function removeElement(element: ResolvedElement) {
    applyDraft(
      {
        ...draft,
        extraElements: draft.extraElements.filter((entry) => entry.id !== element.key),
      },
      null,
    )
    commitEdits()
    if (selectedKey === element.key) setSelectedKey(null)
  }

  /**
   * The layers panel's delete, by id.
   *
   * An added or duplicated element genuinely leaves the draft; a template
   * element has no entry in the draft to remove, so "delete" becomes hidden —
   * gone from the canvas and the export, still recoverable from the layers
   * panel and by undo, which is the only removal the override model can say.
   */
  function deleteElementById(id: string) {
    const element = resolved?.elements.find((entry) => entry.key === id)
    if (!element) return
    if (isExtraElement(id)) {
      removeElement(element)
      return
    }
    changeField(id, 'hidden', true)
    commitEdits()
    if (selectedKey === id) setSelectedKey(null)
  }

  /**
   * Duplicate any element, locally — the mirror of `addShapeElement`'s local
   * creation. The copy joins `draft.extraElements` nudged down-right the way
   * the server's own `duplicate_element` nudges, keeps the original's
   * template pointer so "reset to template" still means something on it, and
   * saves through the same autosave as everything else. An image copy shows
   * its placeholder until the first save round-trip resolves its content —
   * the same contract every added image element already has.
   */
  function duplicateElement(id: string) {
    if (!resolved) return
    const element = resolved.elements.find((entry) => entry.key === id)
    if (!element) return
    const topZ = Math.min(
      1000,
      resolved.elements.reduce((highest, entry) => Math.max(highest, entry.z_index), 0) + 1,
    )
    const entry: ExtraElement = {
      id: localElementId('clone'),
      source_key: element.original_element_id ?? null,
      kind: element.type,
      element_type: element.type,
      label: `${element.name || 'Element'} copy`,
      geometry: {
        ...element.transform,
        x: element.transform.x + 0.02,
        y: element.transform.y + 0.02,
        z_index: topZ,
      },
      style: { ...element.style },
      content: element.content,
      hidden: false,
      z_index: topZ,
    }
    applyDraft({ ...draft, extraElements: [...draft.extraElements, entry] }, null)
    commitEdits()
    setSelectedKey(entry.id)
  }

  /** Copy an element to the editor's clipboard (module-level, so it survives
   *  switching designs — see elementClipboard.ts for why not the OS one). */
  function copyElement(id: string) {
    if (!resolved || !design) return
    const element = resolved.elements.find((entry) => entry.key === id)
    if (!element) return
    setCopiedElement({
      designId,
      templateId: design.template,
      type: element.type,
      name: element.name || 'Element',
      transform: { ...element.transform },
      style: { ...element.style },
      content: element.content,
      sourceKey: element.original_element_id ?? null,
    })
  }

  /**
   * Paste — the clipboard twin of `duplicateElement`, creating locally so it
   * lands instantly and saves through the same autosave as everything else.
   *
   * With a point (right-click on empty canvas), the copy is centred under the
   * pointer; without one (Ctrl+V, or paste from an element's menu), it lands
   * one nudge further down-right per paste so repeats stay visible. An image
   * pasted across designs may show its placeholder until the server resolves
   * its content — same contract as every added image element.
   */
  function pasteElement(at?: { x: number; y: number }) {
    const clip = getCopiedElement()
    if (!clip || !resolved || !design) return
    const topZ = Math.min(
      1000,
      resolved.elements.reduce((highest, entry) => Math.max(highest, entry.z_index), 0) + 1,
    )
    let geometry: Box
    if (at) {
      const box = geometryToPixelBox(clip.transform, resolved)
      const cx = Math.min(Math.max(at.x, 0), resolved.width)
      const cy = Math.min(Math.max(at.y, 0), resolved.height)
      geometry = clampToCanvasLimits(
        pixelBoxToGeometry(
          { ...box, left: cx - box.width / 2, top: cy - box.height / 2 },
          clip.transform.rotation,
          resolved,
        ),
      )
    } else {
      const step = nextPasteStep()
      geometry = clampToCanvasLimits({
        x: clip.transform.x + 0.02 * step,
        y: clip.transform.y + 0.02 * step,
        width: clip.transform.width,
        height: clip.transform.height,
        rotation: clip.transform.rotation,
      })
    }
    const entry: ExtraElement = {
      id: localElementId('clone'),
      // A template pointer only means something inside the template it names;
      // pasted into another design, the copy stands on its own.
      source_key: clip.templateId === design.template ? clip.sourceKey : null,
      kind: clip.type,
      element_type: clip.type,
      label: clip.name,
      geometry: { ...geometry, z_index: topZ },
      style: { ...clip.style },
      content: clip.content,
      hidden: false,
      z_index: topZ,
    }
    applyDraft({ ...draft, extraElements: [...draft.extraElements, entry] }, null)
    commitEdits()
    setSelectedKey(entry.id)
  }

  function copyStyleOf(id: string) {
    const element = resolved?.elements.find((entry) => entry.key === id)
    if (!element) return
    const style: Record<string, unknown> = {}
    for (const field of COPYABLE_STYLE_FIELDS) {
      const value = element.style?.[field]
      if (value !== undefined && value !== null) style[field] = value
    }
    setCopiedStyle({ sourceType: element.type, style })
  }

  /**
   * Apply a copied style in one draft update — one history entry, so one
   * Ctrl+Z takes the whole paste back rather than peeling it off field by
   * field. Template elements only receive the fields they declare editable;
   * pasting the rest would author overrides the next save rejects, and a
   * rejected autosave loses work silently.
   */
  function pasteStyleTo(id: string) {
    const clip = getCopiedStyle()
    if (!clip || !resolved) return
    const element = resolved.elements.find((entry) => entry.key === id)
    if (!element || element.locked) return
    if (isExtraElement(id)) {
      applyDraft(
        {
          ...draft,
          extraElements: draft.extraElements.map((entry) =>
            entry.id === id ? { ...entry, style: { ...entry.style, ...clip.style } } : entry,
          ),
        },
        null,
      )
    } else {
      // The whole style patch, unfiltered: the document model has no per-field
      // permissions (see document.py), and the old editable_fields lookup was
      // keyed by template keys that a document element's id never matches —
      // filtering on it made paste style a silent no-op here.
      applyDraft(
        {
          ...draft,
          overrides: {
            ...draft.overrides,
            [id]: { ...(draft.overrides[id] ?? {}), ...clip.style },
          },
        },
        null,
      )
    }
    commitEdits()
  }

  /**
   * The Layer menu's four moves, as z-index arithmetic.
   *
   * Same philosophy as `reorderElement` below: only the moved element's
   * z_index changes — neighbours may be locked and are not the agent's to
   * restack — so forward/backward step just past the nearest neighbour rather
   * than renumbering the stack.
   */
  function restackElement(id: string, action: LayerAction) {
    if (!resolved) return
    const element = resolved.elements.find((entry) => entry.key === id)
    if (!element) return
    const others = resolved.elements
      .filter((entry) => entry.key !== id)
      .map((entry) => entry.z_index)
    if (others.length === 0) return
    let nextZ = element.z_index
    if (action === 'front') {
      nextZ = Math.max(...others) + 1
    } else if (action === 'back') {
      nextZ = Math.min(...others) - 1
    } else if (action === 'forward') {
      const above = others.filter((z) => z > element.z_index)
      if (above.length === 0) return
      nextZ = Math.min(...above) + 1
    } else {
      const below = others.filter((z) => z < element.z_index)
      if (below.length === 0) return
      nextZ = Math.max(...below) - 1
    }
    nextZ = Math.min(Math.max(nextZ, 0), 1000)
    if (nextZ === element.z_index) return
    changeField(id, 'z_index', nextZ)
    commitEdits()
  }

  /** Align to page: reposition against the true canvas edges, in the same
   *  pixel space every drag uses, then back to fractions. Size and rotation
   *  are untouched — alignment moves a box, it never reshapes one. */
  function alignElementToPage(id: string, action: AlignAction) {
    if (!resolved) return
    const element = resolved.elements.find((entry) => entry.key === id)
    if (!element || element.locked) return
    const box = geometryToPixelBox(element.transform, resolved)
    const left =
      action === 'left'
        ? 0
        : action === 'center'
          ? (resolved.width - box.width) / 2
          : action === 'right'
            ? resolved.width - box.width
            : box.left
    const top =
      action === 'top'
        ? 0
        : action === 'middle'
          ? (resolved.height - box.height) / 2
          : action === 'bottom'
            ? resolved.height - box.height
            : box.top
    changeField(
      id,
      'geometry',
      clampToCanvasLimits(
        pixelBoxToGeometry({ ...box, left, top }, element.transform.rotation, resolved),
      ),
    )
    commitEdits()
  }

  function toggleLocked(id: string) {
    const target = resolved?.elements.find((entry) => entry.key === id)
    if (!target) return
    changeField(id, 'locked', !target.locked)
    commitEdits()
  }

  /**
   * Drag-reorder in the layers panel.
   *
   * Only the dragged element's z_index changes — the drop target's is left
   * alone, because it may well belong to a locked element the agent has no
   * right to restack. The moved element takes the target's position, nudged
   * past it in whichever direction the drag went.
   */
  function reorderElement(movedKey: string, targetKey: string) {
    if (!resolved) return
    const moved = resolved.elements.find((element) => element.key === movedKey)
    const target = resolved.elements.find((element) => element.key === targetKey)
    if (!moved || !target) return

    const movingUp = moved.z_index <= target.z_index
    const nextZ = Math.min(Math.max(target.z_index + (movingUp ? 1 : -1), 0), 1000)
    if (nextZ === moved.z_index) return

    changeField(movedKey, 'z_index', nextZ)
    commitEdits()
  }

  /**
   * Persist the whole draft — overrides and added/duplicated elements — in
   * one request.
   *
   * One request rather than several because a half-applied save is worse
   * than a failed one: the client's model would silently stop matching the
   * server's, and the next autosave would push the difference.
   */
  const persist = useCallback(
    async (toSave: EditorDraft) => {
      const signature = draftSignature(toSave)
      setSaveState('saving')
      setSaveError(null)
      try {
        const saved = await saveDesignState(designId, toSave.overrides, toSave.extraElements)
        setDesign(saved)
        setSavedSignature(signature)
        // Only "saved" if nothing has changed since this request went out.
        setSaveState((current) => (current === 'saving' ? 'saved' : current))

        // Order matters. The local previews stand in for images the server
        // had not yet resolved; they can only be dropped once the resolved
        // design that replaces them is actually in hand. Clearing them first
        // and *then* awaiting the fetch left the canvas showing the previous
        // image for the length of a round trip — a visible flash of the old
        // photo after every save that touched one.
        const fresh = await fetchResolvedDesign(designId, dimension)
        // Only if the agent has not switched format while this was in flight.
        // The PATCH above landed before this fetch went out, so the canvas
        // effect's own response already carries the saved image either way —
        // which is what makes dropping the previews safe regardless.
        if (dimensionRef.current === dimension) setBaseResolved(fresh)
        setImagePreviews({})
        void checkCompliance()
        return true
      } catch (error) {
        setSaveState('error')
        if (error instanceof ApiError && error.data && typeof error.data === 'object') {
          const parsed: Record<string, string> = {}
          for (const [key, value] of Object.entries(error.data as Record<string, unknown>)) {
            parsed[key] = Array.isArray(value) ? String(value[0]) : String(value)
          }
          setErrors(parsed)
          setSaveError(parsed.detail ?? 'Some changes were rejected.')
        } else {
          setSaveError(
            error instanceof ApiError ? error.message : 'Could not save this design.',
          )
        }
        return false
      }
    },
    [designId, dimension, checkCompliance],
  )

  async function save() {
    setErrors({})
    await persist(draft)
  }

  /**
   * Autosave: one request per lull, not one per interaction step.
   *
   * The timer restarts on every change, so a drag that fires geometry
   * updates at pointer rate produces exactly one write — when the pointer
   * stops. That is the whole point: local state carries the interaction, the
   * database sees the outcome.
   *
   * A failed autosave deliberately does not retry on a loop. It leaves the
   * draft intact and the indicator on "error"; the next edit or an explicit
   * Save tries again, rather than hammering an endpoint that just refused.
   */
  useEffect(() => {
    if (!design) return
    if (draftSignature(draft) === savedSignature) return
    if (saveState === 'error') return
    setSaveState((current) => (current === 'saving' ? current : 'unsaved'))

    const timer = window.setTimeout(() => {
      void persist(draft)
    }, AUTOSAVE_IDLE_MS)
    return () => window.clearTimeout(timer)
  }, [draft, savedSignature, design, persist, saveState])

  // Closing the tab mid-lull would otherwise drop whatever the debounce is
  // still holding.
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  /**
   * The editor's keyboard shortcuts — the same set the context menu prints
   * beside its rows, plus undo/redo. A shortcut a menu advertises but that
   * does nothing when typed reads as broken, so these ship together.
   *
   * Subscribed once through a ref (the pattern Canvas uses for its pointer
   * listeners): the handler body needs the current draft/selection on every
   * press, and re-subscribing a window listener per keystroke-induced render
   * is churn for nothing.
   */
  const shortcutRef = useRef<(event: KeyboardEvent) => void>(() => {})
  shortcutRef.current = (event: KeyboardEvent) => {
    // Never fight real typing: inline text editing, the properties panel's
    // inputs, dialogs. Deleting an element because someone pressed Backspace
    // in a text field is the classic canvas-editor bug.
    const target = event.target
    if (editingKey || exportOpen || preview) return
    if (
      target instanceof HTMLElement &&
      (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
    ) {
      return
    }

    const mod = event.ctrlKey || event.metaKey
    const key = event.key.toLowerCase()

    if (mod && !event.shiftKey && !event.altKey && key === 'z') {
      event.preventDefault()
      undo()
      return
    }
    if (mod && (key === 'y' || (event.shiftKey && key === 'z'))) {
      event.preventDefault()
      redo()
      return
    }
    if (key === 'escape') {
      if (contextMenu) setContextMenu(null)
      else setSelectedKey(null)
      return
    }

    const selected = selectedKey
      ? resolved?.elements.find((entry) => entry.key === selectedKey)
      : null

    if (mod && event.altKey && key === 'c') {
      if (!selected) return
      event.preventDefault()
      copyStyleOf(selected.key)
      return
    }
    if (mod && key === 'c') {
      // A real text selection wins — that copy belongs to the browser.
      if (!selected || window.getSelection()?.toString()) return
      event.preventDefault()
      copyElement(selected.key)
      return
    }
    if (mod && event.altKey && key === 'v') {
      if (!selected || selected.locked) return
      event.preventDefault()
      pasteStyleTo(selected.key)
      return
    }
    if (mod && key === 'v') {
      if (!getCopiedElement()) return
      event.preventDefault()
      pasteElement()
      return
    }
    if (mod && key === 'd') {
      if (!selected || selected.locked) return
      event.preventDefault()
      duplicateElement(selected.key)
      return
    }
    if ((key === 'delete' || key === 'backspace') && selected && !selected.locked) {
      event.preventDefault()
      deleteElementById(selected.key)
      return
    }
    if (event.altKey && event.shiftKey && key === 'l') {
      if (!selected) return
      event.preventDefault()
      toggleLocked(selected.key)
      return
    }
    if (mod && (event.key === ']' || event.key === '[')) {
      if (!selected || selected.locked) return
      event.preventDefault()
      restackElement(
        selected.key,
        event.key === ']'
          ? event.altKey
            ? 'front'
            : 'forward'
          : event.altKey
            ? 'back'
            : 'backward',
      )
    }
  }
  useEffect(() => {
    const listener = (event: KeyboardEvent) => shortcutRef.current(event)
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])

  async function runPreview() {
    setBusy(true)
    setErrors({})
    try {
      const result = await previewDesign(designId, dimension)
      setPreview(result.image)
      setPreviewMs(result.render_ms)
    } catch (error) {
      setErrors({
        detail: error instanceof ApiError ? error.message : 'Could not render a preview.',
      })
    } finally {
      setBusy(false)
    }
  }

  /**
   * Open the export dialog — the header button does not export by itself.
   *
   * Compliance is no longer pinned open beside the canvas, so the dialog is
   * where the flags become unmissable: they sit directly above the button
   * that commits the export, whether or not the agent ever opened the badge.
   */
  function requestExport() {
    setMessage(null)
    setErrors({})
    setExportOpen(true)
  }

  async function runExport() {
    if (exportDims.length === 0) return
    setBusy(true)
    setErrors({})
    setNotReady([])
    setMessage(null)
    try {
      const result = await exportDesign(designId, exportDims, exportFormat)
      setDesign(await fetchDesign(designId))
      setCompliance(result.compliance)
      setMessage(`Exported ${exportDims.length} image${exportDims.length === 1 ? '' : 's'}.`)
      setExportOpen(false)
    } catch (error) {
      // Two different 409s, and telling an agent the wrong one wastes their
      // time: either a rule flagged the copy, or a field the design needs is
      // simply empty. The readiness body carries `missing`; the compliance one
      // carries `compliance`.
      if (error instanceof ApiError && error.status === 409) {
        const data = error.data as {
          compliance?: ComplianceReport
          missing?: MissingField[]
          detail?: string
        } | null

        if (data?.missing?.length) {
          // Fixing these means leaving for another screen, so the dialog gets
          // out of the way and the links land in the notices band.
          setNotReady(data.missing)
          setExportOpen(false)
          setErrors({ detail: data.detail ?? 'This design is missing information.' })
        } else {
          // Show the server's own report, in full, rather than sending the
          // agent hunting for it: it is fresher than ours and it is the one
          // that just refused the export. The dialog stays open around it.
          if (data?.compliance) setCompliance(data.compliance)
          setErrors({ detail: 'This design does not meet the compliance rules yet.' })
        }
      } else {
        setErrors({
          detail: error instanceof ApiError ? error.message : 'Could not export this design.',
        })
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleRename() {
    const name = window.prompt('Design name', design?.name ?? '')
    if (!name) return
    setDesign(await renameDesign(designId, name))
  }

  async function handleDuplicate() {
    const copy = await duplicateDesign(designId)
    void navigate(designEditorPath(copy.id))
  }

  /**
   * Pick another template from the left rail.
   *
   * Moves to *that template's* design rather than re-templating this one. The
   * elements on this canvas were copied from the current template, so changing
   * it would throw the whole canvas away — this design is left exactly as it
   * is, and the other one opens in its place.
   *
   * "That template's design" and not "a new design": if the agent has already
   * customised the template they are picking, the server hands that back
   * instead of adding another near-identical row to their designs panel. This
   * call site was one of the ones producing them — switching templates twice
   * in one session used to leave two abandoned designs behind.
   */
  async function startFromTemplate(picked: TemplateSummary) {
    if (!design || picked.id === design.template) return
    setPickingTemplate(picked.id)
    setErrors({})
    try {
      const created = await createDesign({
        name: `${picked.name} — ${new Date().toLocaleDateString()}`,
        template: picked.id,
        // Imported templates take the listing across too: they can bind
        // property fields without sitting in a listing category, and dropping
        // it here would quietly unpick the property on switching.
        //
        // Ignored when an existing design is resumed — its own listing stands,
        // because that is a choice the agent already made on that design.
        listing: picked.requires_listing || picked.is_imported ? design.listing : null,
      })
      void navigate(designEditorPath(created.id))
    } catch (error) {
      setErrors({
        detail:
          error instanceof ApiError ? error.message : 'Could not start that design.',
      })
      setPickingTemplate(null)
    }
  }

  /**
   * Variation actions.
   *
   * Each is the existing, already-tested endpoint — this strip exposes them,
   * it does not introduce a new way to mutate a design. Reordering is absent
   * on purpose: designs are ordered by `-updated_at` server-side and carry no
   * position column, so a drag here would appear to work and then silently
   * undo itself on the next save.
   */
  async function addVariation() {
    if (!design) return
    try {
      const copy = await duplicateDesign(designId, `${design.name} (variation)`)
      loadVariations(design.template)
      void navigate(designEditorPath(copy.id))
    } catch (error) {
      setErrors({
        detail: error instanceof ApiError ? error.message : 'Could not add a variation.',
      })
    }
  }

  async function duplicateVariation(target: Design) {
    try {
      await duplicateDesign(target.id)
      if (design) loadVariations(design.template)
    } catch (error) {
      setErrors({
        detail: error instanceof ApiError ? error.message : 'Could not duplicate that design.',
      })
    }
  }

  async function renameVariation(target: Design) {
    const name = window.prompt('Design name', target.name)
    if (!name) return
    try {
      const saved = await renameDesign(target.id, name)
      if (target.id === designId) setDesign(saved)
      if (design) loadVariations(design.template)
    } catch (error) {
      setErrors({
        detail: error instanceof ApiError ? error.message : 'Could not rename that design.',
      })
    }
  }

  async function deleteVariation(target: Design) {
    if (!window.confirm(`Delete "${target.name}"? Its exports go with it.`)) return
    try {
      await deleteDesign(target.id)
      if (design) loadVariations(design.template)
    } catch (error) {
      setErrors({
        detail: error instanceof ApiError ? error.message : 'Could not delete that design.',
      })
    }
  }

  /**
   * "Adapt layout for this format": a server-side copy re-composed for the
   * dimension currently on screen — boxes keep their shape and corners stay
   * anchored instead of stretching with the canvas (layout_adaptation.py).
   *
   * The draft is persisted first for the same reason goToListings persists:
   * the server adapts the *stored* document, and adapting a canvas thirty
   * seconds behind the screen would silently drop those edits from the copy.
   * The original design is untouched; the editor moves to the copy.
   */
  async function adaptForCurrentFormat() {
    setAdapting(true)
    setErrors({})
    try {
      if (dirty && !(await persist(draft))) return
      const adapted = await adaptDesign(designId, dimension)
      void navigate(designEditorPath(adapted.id))
    } catch (error) {
      setErrors({
        detail:
          error instanceof ApiError ? error.message : 'Could not adapt this design.',
      })
    } finally {
      setAdapting(false)
    }
  }

  async function handleDelete() {
    if (!window.confirm('Delete this design? Its exports go with it.')) return
    await deleteDesign(designId)
    void navigate(DESIGNS_HOME, { replace: true })
  }

  /**
   * Leave for the listings panel to bring a property into this design.
   *
   * The draft is persisted first and deliberately not in the background: this
   * navigation unmounts the editor, which would take the autosave timer with
   * it, and coming back to find the last thirty seconds of work missing is
   * not a trade worth making for one saved request. A failed save cancels the
   * trip rather than leaving quietly with the work behind.
   */
  async function goToListings() {
    if (dirty) {
      await persist(draft)
      if (saveState === 'error') return
    }
    void navigate(listingsForDesignPath(designId))
  }

  if (loadError) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold tracking-tight">Design</h1>
        <Alert kind="error">{loadError}</Alert>
      </div>
    )
  }

  if (!design || !template || !resolved) {
    return <p className="text-sm text-slate-500">Loading…</p>
  }

  const editableByKey = new Map(
    template.elements.map((element) => [element.key, element.editable_fields]),
  )
  // An added or duplicated element has no template element to read
  // `editable_fields` from — it is FREE by construction, so it gets the full
  // field set. The server still validates every write against the same rules.
  const FREE_FIELDS = [
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
  const editableFieldsFor = (element: ResolvedElement | null): string[] => {
    if (!element) return []
    if (element.is_clone || element.key.startsWith('added-')) return FREE_FIELDS
    return editableByKey.get(element.key) ?? []
  }
  const selectedEditableFields = editableFieldsFor(selectedElement)
  /**
   * The pending override for a control to show.
   *
   * Only template elements have one: an added or duplicated element carries
   * its own values directly (they are already merged into `element.style`
   * and `element.content` by deriveResolved), so an empty object is correct
   * and the controls read straight from the element.
   */
  const overrideFor = (element: ResolvedElement | null): Record<string, unknown> =>
    element && !isExtraElement(element.key) ? draft.overrides[element.key] ?? {} : {}
  // Paint order, which is what the layers list reverses to show top-first.
  const sortedForLayers = [...resolved.elements].sort((a, b) => a.z_index - b.z_index)

  const hasFieldErrors = Object.keys(errors).some((key) => key !== 'detail')
  // The export dialog shows its own failure. Repeating it in the band behind
  // the dialog says the same thing twice and reads as two problems.
  const bannerDetail = exportOpen ? null : errors.detail
  const hasNotices = Boolean(message || bannerDetail || notReady.length > 0 || hasFieldErrors)

  return (
    // h-dvh, not h-screen: on phone browsers the URL bar comes and goes, and
    // dvh tracks the height that is actually visible.
    <div className="flex h-dvh flex-col overflow-hidden bg-app">
      <EditorHeader
        designName={design.name}
        updatedAt={design.updated_at}
        canUndo={historyIndex > 0}
        canRedo={historyIndex < history.length - 1}
        onUndo={undo}
        onRedo={redo}
        zoom={zoom}
        onZoomChange={setZoom}
        onFit={() => setFitNonce((current) => current + 1)}
        onPreview={() => void runPreview()}
        onSave={() => void save()}
        onExport={requestExport}
        saveState={saveState}
        saveError={saveError}
        busy={busy}
        onImportListing={() => void goToListings()}
        listingAddress={design.listing_address ?? null}
        onRename={() => void handleRename()}
        onDuplicate={() => void handleDuplicate()}
        onDelete={() => void handleDelete()}
        variationsOpen={variationsOpen}
        onToggleVariations={() => setVariationsOpen((open) => !open)}
        advancedOpen={advancedOpen}
        onToggleAdvanced={() => setAdvancedOpen((open) => !open)}
      />

      {/* A band under the header, and only when there is something in it —
          the workspace is a fixed height now, so a permanently reserved
          notices strip would cost the canvas that much forever. */}
      {hasNotices && (
        <div className="shrink-0 space-y-2 border-b border-line bg-surface px-4 py-3">
          {message && <Alert kind="success">{message}</Alert>}
          {bannerDetail && <Alert kind="error">{bannerDetail}</Alert>}

          {/* The requirement is real, but this is the first moment it is real —
              so it arrives with the way to satisfy it, not just a refusal. */}
          {notReady.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-4">
              <p className="text-sm font-medium text-amber-900">
                Fill these in and the export will go through:
              </p>
              <ul className="mt-3 flex flex-wrap gap-2">
                {notReady.map((field) => (
                  <li key={field.element}>
                    <Link
                      to={field.fix_path}
                      className="inline-block rounded-md border border-amber-300 bg-white px-2.5 py-1 text-xs font-medium text-amber-900 transition hover:border-amber-500"
                    >
                      {field.label} — {field.step_label} →
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {hasFieldErrors && (
            <Alert kind="error">Some changes were rejected. See the highlighted element.</Alert>
          )}
        </div>
      )}

      {/* relative: on small screens the tool and properties panels float over
          this workspace instead of shrinking the canvas to a ribbon. */}
      <div className="relative flex min-h-0 flex-1">
        <LeftPanel
          tab={leftTab}
          onTabChange={setLeftTab}
          template={template}
          elements={sortedForLayers}
          selectedKey={selectedKey}
          onSelect={(key) => {
            setSelectedKey(key)
            setEditingKey(null)
          }}
          onReorder={(movedKey, targetKey) => void reorderElement(movedKey, targetKey)}
          onRemoveElement={(id) => deleteElementById(id)}
          onRenameElement={(id, name) => {
            changeField(id, 'name', name)
            commitEdits()
          }}
          onToggleVisible={(id) => {
            const target = resolved.elements.find((entry) => entry.key === id)
            if (!target) return
            changeField(id, 'hidden', target.visible)
            commitEdits()
          }}
          onToggleLocked={(id) => toggleLocked(id)}
          onDuplicateElement={(id) => duplicateElement(id)}
          onAddElement={(kind) => void addElement(kind)}
          onAddShape={(shape) => addShapeElement(shape)}
          adding={addingElement}
          onPickTemplate={(picked) => void startFromTemplate(picked)}
          pickingTemplate={pickingTemplate}
          hasListing={design.listing !== null}
          listingPhotos={listingPhotos}
          uploads={uploads}
          onUploadFile={(file) => void uploadToLibrary(file)}
          uploading={uploadingImage}
          selectedElement={selectedElement}
          brandKit={brandKit}
          onApplyImage={
            selectedElement &&
            isImageElement(selectedElement) &&
            selectedEditableFields.includes('image_key')
              ? (imageKey, previewUrl) =>
                  replaceImage(selectedElement.key, imageKey, previewUrl)
              : null
          }
        />

        <main className="flex min-w-0 flex-1 flex-col gap-2 p-3">
          <div className="flex flex-wrap items-center gap-1">
            {dimensions.map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => setDimension(option.key)}
                className={`rounded-control px-3 py-1.5 text-[12px] font-medium transition ${
                  dimension === option.key
                    ? 'border border-line bg-surface text-brand shadow-panel'
                    : 'border border-transparent text-muted hover:bg-hover hover:text-ink'
                }`}
              >
                {option.label}
              </button>
            ))}

            {/* Only away from the design's own format — at home there is
                nothing to adapt, and the tabs alone already render it right. */}
            {dimension !== (design.preferred_dimension || template.default_dimension) && (
              <button
                type="button"
                onClick={() => void adaptForCurrentFormat()}
                disabled={adapting}
                title={
                  'Create a copy of this design re-composed for this format: ' +
                  'boxes keep their shape and corners stay anchored instead of ' +
                  'stretching with the canvas. This design is not changed.'
                }
                className="ml-2 rounded-control border border-brand/40 px-3 py-1.5 text-[12px] font-medium text-brand transition hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {adapting
                  ? 'Adapting…'
                  : `✨ Adapt layout for ${
                      dimensions.find((option) => option.key === dimension)?.label ?? dimension
                    }`}
              </button>
            )}
          </div>

          {/* The contextual toolbar, docked (Canva-style) rather than floating
              over the artwork. Always rendered so the canvas below never jumps
              when selection changes. */}
          <TopToolbar
            element={selectedElement ?? undefined}
            override={overrideFor(selectedElement)}
            onChange={(field, value) => {
              if (selectedElement) changeField(selectedElement.key, field, value)
            }}
            onCommit={commitEdits}
            listingPhotos={listingPhotos}
            onPickPhoto={(imageKey, previewUrl) => {
              if (selectedElement) replaceImage(selectedElement.key, imageKey, previewUrl)
            }}
            onUploadFile={(file) => {
              if (selectedElement) void uploadAndReplaceImage(selectedElement.key, file)
            }}
            uploading={uploadingImage}
            brandKit={brandKit}
            propertiesOpen={propertiesOpen}
            onToggleProperties={() => setPropertiesOpen((open) => !open)}
          />

          <Canvas
            selectionToolbar={
              selectedElement ? (
                <QuickActions
                  locked={selectedElement.locked}
                  onToggleLock={() => toggleLocked(selectedElement.key)}
                  onDuplicate={() => duplicateElement(selectedElement.key)}
                  onDelete={() => deleteElementById(selectedElement.key)}
                  onMore={() => setPropertiesOpen((open) => !open)}
                />
              ) : undefined
            }
            design={resolved}
            backgroundColor={
              typeof template.layout_definition.background_color === 'string'
                ? template.layout_definition.background_color
                : undefined
            }
            brandKit={brandKit}
            selectedKey={selectedKey}
            onSelect={(key) => {
              setSelectedKey(key)
              if (key !== editingKey) setEditingKey(null)
            }}
            editingKey={editingKey}
            onStartEdit={startTextEdit}
            onCommitEdit={commitTextEdit}
            onCancelEdit={cancelTextEdit}
            onGeometryChange={(key, geometry) => changeField(key, 'geometry', geometry)}
            onGeometryCommit={commitEdits}
            onShapeDrop={(shape, geometry) => addShapeElement(shape, geometry)}
            onElementContextMenu={(id, position) => {
              const element = resolved.elements.find((entry) => entry.key === id)
              if (!element) return
              // A locked element opens its (Unlock) menu without being
              // selected — selection implies handles and a toolbar, which a
              // locked element should not sprout.
              if (!element.locked) {
                setSelectedKey(id)
                setEditingKey(null)
              }
              setContextMenu({ x: position.x, y: position.y, targetId: id })
            }}
            onCanvasContextMenu={(position, point) => {
              setContextMenu({
                x: position.x,
                y: position.y,
                targetId: null,
                pastePoint: point,
              })
            }}
            zoom={zoom}
            onZoomChange={setZoom}
            fitNonce={fitNonce}
          />

          {/* Secondary surfaces. Both are off by default and toggled from the
              header's ⋯ menu: neither is part of designing, and both used to
              take permanent height from the thing that is. */}
          {variationsOpen && (
            <VariationsStrip
              variations={variations}
              currentId={designId}
              aspect={resolved.width / resolved.height}
              backgroundColor={
                typeof template.layout_definition.background_color === 'string'
                  ? template.layout_definition.background_color
                  : '#FFFFFF'
              }
              busy={busy}
              onOpen={(id) => void navigate(designEditorPath(id))}
              onAdd={() => void addVariation()}
              onDuplicate={(target) => void duplicateVariation(target)}
              onRename={(target) => void renameVariation(target)}
              onDelete={(target) => void deleteVariation(target)}
            />
          )}

          {advancedOpen && (
            <div className="max-h-[40vh] shrink-0 overflow-y-auto rounded-panel border border-line bg-surface">
              <div className="sticky top-0 flex items-center gap-2 border-b border-line bg-surface px-3 py-2">
                <span className="text-xs font-semibold text-ink">
                  Every element as a list ({resolved.elements.length})
                </span>
                <button
                  type="button"
                  onClick={() => setAdvancedOpen(false)}
                  className="ml-auto rounded px-1.5 text-base leading-none text-muted transition hover:bg-hover hover:text-ink"
                  aria-label="Close the element list"
                >
                  ×
                </button>
              </div>
              <ul className="space-y-3 p-3">
                {resolved.elements.map((element) => (
                  <ElementControls
                    key={element.key}
                    element={element}
                    editableFields={editableFieldsFor(element)}
                    override={overrideFor(element)}
                    onChange={(field, value) => changeField(element.key, field, value)}
                    onClear={() => clearElement(element.key)}
                    error={errors[element.key]}
                  />
                ))}
              </ul>
            </div>
          )}
        </main>

        {/* On demand only — the `Position` button in the docked toolbar (or
            the pill's slider icon) opens it, matching Canva: selection alone
            never costs the canvas 320px of workspace. */}
        {selectedElement && propertiesOpen && (
          <aside className="w-[320px] shrink-0 overflow-y-auto border-l border-line bg-app p-3 max-lg:absolute max-lg:inset-y-0 max-lg:right-0 max-lg:z-30 max-lg:w-[min(320px,85vw)] max-lg:bg-surface max-lg:shadow-pop">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold text-ink">Position &amp; properties</span>
              <button
                type="button"
                onClick={() => setPropertiesOpen(false)}
                className="rounded px-1.5 text-base leading-none text-muted transition hover:bg-hover hover:text-ink"
                aria-label="Close the properties panel"
              >
                ×
              </button>
            </div>
            <PropertiesSidebar
              element={selectedElement}
              documentColors={documentColors}
              brandKit={brandKit}
              onChange={(field, value) => changeField(selectedElement.key, field, value)}
              onCommit={commitEdits}
              onClear={() => clearElement(selectedElement.key)}
              listingPhotos={listingPhotos}
              onPickPhoto={(imageKey, previewUrl) =>
                replaceImage(selectedElement.key, imageKey, previewUrl)
              }
              onUploadFile={(file) =>
                void uploadAndReplaceImage(selectedElement.key, file)
              }
              uploading={uploadingImage}
              error={errors[selectedElement.key]}
            />
          </aside>
        )}
      </div>

      {contextMenu && (
        <CanvasContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          element={contextMenu.targetId ? selectedElementFor(contextMenu.targetId) : null}
          canPaste={getCopiedElement() !== null}
          canPasteStyle={getCopiedStyle() !== null}
          onCopy={() => {
            if (contextMenu.targetId) copyElement(contextMenu.targetId)
          }}
          onCopyStyle={() => {
            if (contextMenu.targetId) copyStyleOf(contextMenu.targetId)
          }}
          onPaste={() => pasteElement(contextMenu.pastePoint)}
          onPasteStyle={() => {
            if (contextMenu.targetId) pasteStyleTo(contextMenu.targetId)
          }}
          onDuplicate={() => {
            if (contextMenu.targetId) duplicateElement(contextMenu.targetId)
          }}
          onDelete={() => {
            if (contextMenu.targetId) deleteElementById(contextMenu.targetId)
          }}
          onLayer={(action) => {
            if (contextMenu.targetId) restackElement(contextMenu.targetId, action)
          }}
          onAlign={(action) => {
            if (contextMenu.targetId) alignElementToPage(contextMenu.targetId, action)
          }}
          onToggleLock={() => {
            if (contextMenu.targetId) toggleLocked(contextMenu.targetId)
          }}
          onClose={() => setContextMenu(null)}
        />
      )}

      {exportOpen && (
        <ExportDialog
          designName={design.name}
          dimensions={dimensions}
          selected={exportDims}
          onSelectedChange={setExportDims}
          format={exportFormat}
          onFormatChange={setExportFormat}
          compliance={compliance}
          checkingCompliance={checkingCompliance}
          exports={design.exports}
          busy={busy}
          error={errors.detail ?? null}
          onExport={() => void runExport()}
          onClose={() => setExportOpen(false)}
        />
      )}

      {/* The real, browser-rendered export, over the canvas rather than under
          it: the point is to compare the two, which needs the same space. */}
      {preview && (
        <div
          role="dialog"
          aria-label="Rendered export preview"
          className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-slate-900/70 p-6"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPreview(null)
          }}
        >
          <img
            src={preview}
            alt="Rendered export preview"
            className="max-h-[80vh] w-auto rounded-panel bg-white shadow-pop"
          />
          <div className="flex items-center gap-3 text-xs text-white/90">
            {previewMs !== null && <span>Rendered in {previewMs} ms</span>}
            <button
              type="button"
              onClick={() => setPreview(null)}
              className="rounded-md border border-white/40 px-2.5 py-1 font-medium transition hover:bg-white/10"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
