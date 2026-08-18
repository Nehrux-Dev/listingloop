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
import LeftPanel, {
  isImageElement,
  useLeftPanelTab,
} from '../components/design-editor/LeftPanel.tsx'
import EditorHeader from '../components/design-editor/EditorHeader.tsx'
import ExportDialog from '../components/design-editor/ExportDialog.tsx'
import PropertiesSidebar from '../components/design-editor/PropertiesSidebar.tsx'
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

/** Idle time before an autosave fires. Long enough that a drag, a slider
 *  sweep or a burst of typing settles into one request rather than dozens;
 *  short enough that nobody wonders whether their work is safe. */
const AUTOSAVE_IDLE_MS = 1500

type SaveState = 'saved' | 'unsaved' | 'saving' | 'error'

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
    entry.geometry,
    entry.z_index,
    entry.hidden,
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
        ? { ...templateGeometry, rotation: templateGeometry.rotation ?? 0 }
        : element.geometry

      let geometry: Geometry = baseGeometry
      let style: Record<string, unknown> = templateElement?.style_properties ?? element.style
      let content = element.content
      let hidden = false
      let zIndex = templateElement?.z_index ?? element.z_index

      for (const [field, value] of Object.entries(override)) {
        if (field === 'geometry') geometry = value as Geometry
        else if (field === 'hidden') hidden = Boolean(value)
        else if (field === 'text') content = String(value)
        else if (field === 'z_index') zIndex = Number(value)
        else if (field === 'image_key') continue
        else style = { ...style, [field]: value }
      }

      const preview = imagePreviews[element.key]
      if (preview) content = preview

      return { ...element, geometry, style, content, hidden, z_index: zIndex }
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
    const isImage = ['image', 'logo', 'static_graphic'].includes(entry.element_type)
    const content = isImage
      ? imagePreviews[entry.id] ?? server?.content ?? entry.content
      : entry.content

    return {
      key: entry.id,
      label: entry.label,
      element_type: entry.element_type,
      // An element the agent added or duplicated is theirs to move, restyle
      // and delete — the server treats it as FREE by construction.
      permission: 'free',
      constraints: server?.constraints ?? {},
      geometry: entry.geometry,
      style: entry.style,
      content,
      hidden: entry.hidden,
      overridden_fields: [],
      is_clone: true,
      source_key: entry.source_key,
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
  const [listingPhotos, setListingPhotos] = useState<ListingPhoto[]>([])
  const [uploadingImage, setUploadingImage] = useState(false)
  const [leftTab, setLeftTab] = useLeftPanelTab()
  const [uploads, setUploads] = useState<UploadedImage[]>([])
  const [addingElement, setAddingElement] = useState(false)
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

  // Open in the format the template was drawn for, once — after that the
  // dimension tabs are the agent's to control.
  //
  // Pinned as soon as the template is known, even when it names no format,
  // because the resolved-design load below waits on this: leaving it false
  // for a template without a `default_dimension` would mean the canvas never
  // loaded at all.
  useEffect(() => {
    if (dimensionPinned || !template) return
    if (template.default_dimension) setDimension(template.default_dimension)
    setDimensionPinned(true)
  }, [template, dimensionPinned])

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
      const created = fresh.extra_elements[fresh.extra_elements.length - 1]
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
  const textEditableKeys = new Set(
    template.elements
      .filter((element) => element.editable_fields.includes('text'))
      .map((element) => element.key),
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
    <div className="flex h-screen flex-col overflow-hidden bg-app">
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

      <div className="flex min-h-0 flex-1">
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
          canReorder={(element) => editableFieldsFor(element).includes('z_index')}
          onReorder={(movedKey, targetKey) => void reorderElement(movedKey, targetKey)}
          onRemoveElement={(element) => void removeElement(element)}
          onAddElement={(kind) => void addElement(kind)}
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
          <div className="flex flex-wrap gap-1">
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
          </div>

          <Canvas
            selectionToolbar={
              selectedElement ? (
                <TopToolbar
                  element={selectedElement}
                  editableFields={selectedEditableFields}
                  override={overrideFor(selectedElement)}
                  onChange={(field, value) => changeField(selectedElement.key, field, value)}
                  onCommit={commitEdits}
                  listingPhotos={listingPhotos}
                  onPickPhoto={(imageKey, previewUrl) =>
                    replaceImage(selectedElement.key, imageKey, previewUrl)
                  }
                  onUploadFile={(file) =>
                    void uploadAndReplaceImage(selectedElement.key, file)
                  }
                  uploading={uploadingImage}
                  brandKit={brandKit}
                  onDelete={
                    selectedElement.is_clone ? () => removeElement(selectedElement) : undefined
                  }
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
            textEditableKeys={textEditableKeys}
            editingKey={editingKey}
            onStartEdit={startTextEdit}
            onCommitEdit={commitTextEdit}
            onCancelEdit={cancelTextEdit}
            onGeometryChange={(key, geometry) => changeField(key, 'geometry', geometry)}
            onGeometryCommit={commitEdits}
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

        {/* Only on selection. With nothing selected there is nothing for this
            column to say, and an empty panel is 320px of the workspace spent
            on the words "Nothing selected". */}
        {selectedElement && (
          <aside className="w-[320px] shrink-0 overflow-y-auto border-l border-line bg-app p-3">
            <PropertiesSidebar
              element={selectedElement}
              editableFields={selectedEditableFields}
              override={overrideFor(selectedElement)}
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
