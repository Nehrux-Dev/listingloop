/**
 * The left rail: what you can put into the design, and what is already in it.
 *
 * A THIN RAIL WITH A FLYOUT, NOT A SECOND COLUMN
 * ---------------------------------------------------------------------------
 * The icons are always there; the panel beside them is not. Clicking a tool
 * opens it, clicking the open tool again closes it, and with everything shut
 * the canvas has the whole workspace. That is the difference between a rail
 * and a column: a column costs 340px whether or not you are using it.
 *
 * Seven tools — Templates, Elements, Uploads, Text, Images, Brand, Layers.
 * Everything that adds an element goes through `POST /elements/add/`, which
 * writes to the agent's own `Design.extra_elements` and never to the
 * `Template`. Where the template forbids added elements entirely
 * (`allows_added_elements`), those tools say so instead of offering buttons
 * that would come back rejected.
 *
 * ON THE CONTENT BEING REAL
 * ---------------------------------------------------------------------------
 * The collections, counts and thumbnails in here are built from data this
 * app actually holds — the listing's photos, this session's uploads, the
 * shape recipes the server will accept. None of it is placeholder furniture.
 * A tile that cannot add anything is not rendered as if it can: the catalogue
 * below is derived from ADDABLE_ELEMENTS, so the panel and the server agree
 * on what exists.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import type { ListingPhoto } from '../../api/listings.ts'
import type { BrandKit } from '../../api/profiles.ts'
import {
  fetchTemplates,
  type ElementType,
  type ResolvedElement,
  type TemplateDetail,
  type TemplateSummary,
  type UploadedImage,
} from '../../api/templates.ts'
import {
  IconArrowRight,
  IconBrandKit,
  IconElements,
  IconFilter,
  IconImage,
  IconLayers,
  IconSearch,
  IconSparkle,
  IconTemplates,
  IconText,
  IconUpload,
} from '../icons.tsx'
import TemplateThumb from '../TemplateThumb.tsx'
import LayersPanel from './LayersPanel.tsx'
import { elementKind } from './elementKind.ts'
import {
  SHAPE_DRAG_MIME,
  SHAPE_PRIMITIVES,
  shapePrimitive,
  type ShapePrimitive,
  type ShapePrimitiveKey,
} from './shapeLibrary.ts'

export type LeftPanelTab =
  | 'templates'
  | 'elements'
  | 'uploads'
  | 'text'
  | 'images'
  | 'brand'
  | 'layers'

const TABS: {
  key: LeftPanelTab
  label: string
  Icon: (props: { className?: string }) => React.ReactElement
}[] = [
  { key: 'templates', label: 'Templates', Icon: IconTemplates },
  { key: 'elements', label: 'Elements', Icon: IconElements },
  { key: 'uploads', label: 'Uploads', Icon: IconUpload },
  { key: 'text', label: 'Text', Icon: IconText },
  { key: 'images', label: 'Images', Icon: IconImage },
  { key: 'brand', label: 'Brand', Icon: IconBrandKit },
  { key: 'layers', label: 'Layers', Icon: IconLayers },
]

/** The element categories the chips filter by. */
type Category = 'all' | 'shapes' | 'frames' | 'icons' | 'lines'

const CATEGORIES: { key: Category; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'shapes', label: 'Shapes' },
  { key: 'frames', label: 'Frames' },
  { key: 'icons', label: 'Icons' },
  { key: 'lines', label: 'Lines' },
]

/**
 * Every element the panel can add, with the swatch that represents it.
 *
 * `kind` is the server-side recipe name; a tile without one could not be
 * added, so there are none. "Frames" are image elements — in this editor a
 * frame is a slot you drop a photo into, which is exactly what an image
 * element is.
 */
type Tile = {
  kind: ElementType
  /** Set for a shape/frame card: the local recipe placed directly (and
   *  draggable onto the canvas). Without it the tile goes through the
   *  server's per-type blueprint — which cannot tell a star from a square. */
  shape?: ShapePrimitiveKey
  label: string
  keywords: string
  category: Exclude<Category, 'all'>
  swatch: React.ReactNode
}

/**
 * A card's preview, drawn from the primitive's own recipe — the same
 * clip polygon and radius the placed element will render with, so the card
 * can never advertise a shape the canvas then draws differently.
 */
function ShapeSwatch({ primitive }: { primitive: ShapePrimitive }) {
  const aspect = primitive.width / primitive.height
  const width = aspect >= 1 ? 40 : Math.max(12, Math.round(40 * aspect))
  const height = aspect >= 1 ? Math.max(3, Math.round(40 / aspect)) : 40

  const style: React.CSSProperties = { width, height }
  const polygon = primitive.style.clip_polygon as number[] | undefined
  if (Array.isArray(polygon)) {
    const pairs: string[] = []
    for (let index = 0; index < polygon.length; index += 2) {
      pairs.push(`${polygon[index]}% ${polygon[index + 1]}%`)
    }
    style.clipPath = `polygon(${pairs.join(',')})`
  }
  const radius = Number(primitive.style.border_radius_ratio ?? 0)
  if (radius > 0) style.borderRadius = radius >= 0.5 ? 999 : 5

  if (primitive.category === 'frames') {
    return (
      <span className="flex items-center justify-center bg-beige" style={style}>
        <IconImage className="size-4 text-brand/50" />
      </span>
    )
  }
  return (
    <span
      className={`block ${primitive.category === 'lines' ? 'bg-brand/70' : 'bg-beige'}`}
      style={style}
    />
  )
}

const TILES: Tile[] = [
  // Every primitive becomes a card; the swatch is derived from the recipe.
  ...SHAPE_PRIMITIVES.map(
    (primitive): Tile => ({
      kind: primitive.type,
      shape: primitive.key,
      label: primitive.label,
      keywords: primitive.keywords,
      category: primitive.category,
      swatch: <ShapeSwatch primitive={primitive} />,
    }),
  ),
  // The badge is a shape with a label inside it — a server-blueprint element
  // (`type: button`), not a style-only primitive, so it keeps its own card.
  {
    kind: 'button',
    label: 'Badge',
    keywords: 'badge pill label tag chip',
    category: 'shapes',
    swatch: (
      <span className="block rounded-full bg-brand px-2.5 py-1 text-[8px] font-bold tracking-wide text-white">
        BADGE
      </span>
    ),
  },
]

/** What identifies a tile in the recently-used store — the shape key where
 *  there is one, else the element type. Two shape tiles share `kind`, so the
 *  kind alone cannot name them. */
function tileId(tile: Tile): string {
  return tile.shape ?? tile.kind
}

const RECENT_KEY = 'design-editor:recent-elements'
const RECENT_LIMIT = 4

function readRecent(): string[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const known = new Set(TILES.map(tileId))
    return parsed.filter((k): k is string => typeof k === 'string' && known.has(k))
  } catch {
    // A corrupt or unavailable store is not worth breaking the panel over.
    return []
  }
}

type Props = {
  /** The open tool, or null when the rail is collapsed to icons only. */
  tab: LeftPanelTab | null
  onTabChange: (tab: LeftPanelTab | null) => void

  template: TemplateDetail
  elements: ResolvedElement[]
  selectedKey: string | null
  onSelect: (key: string) => void
  onReorder: (movedId: string, targetId: string) => void
  onRemoveElement: (id: string) => void
  onRenameElement: (id: string, name: string) => void
  onToggleVisible: (id: string) => void
  onToggleLocked: (id: string) => void
  onDuplicateElement: (id: string) => void

  onAddElement: (kind: ElementType) => void
  /** Place a shape primitive from the local library — at the canvas centre
   *  from a click; the drag-onto-canvas path goes through Canvas's own drop
   *  handler instead, because only it can name the drop position. */
  onAddShape: (shape: ShapePrimitive) => void
  adding: boolean

  /** Start a new design from another template. See TemplatesTab for why this
   *  starts one rather than swapping the current design's. */
  onPickTemplate: (template: TemplateSummary) => void
  /** The template being opened, so its tile can say so. */
  pickingTemplate: number | null
  /** Whether this design has a listing, which decides if the property
   *  templates in the grid are usable from here. */
  hasListing: boolean

  listingPhotos: ListingPhoto[]
  uploads: UploadedImage[]
  onUploadFile: (file: File) => void
  uploading: boolean
  onApplyImage: ((imageKey: string, previewUrl: string) => void) | null
  selectedElement: ResolvedElement | null
  brandKit: BrandKit | null
}

export default function LeftPanel(props: Props) {
  return (
    // relative: on small screens the expanded panel floats over the canvas
    // (anchored to this wrapper) instead of squeezing it off the viewport —
    // a 300px column beside a 390px phone leaves nothing to design on.
    <div className="relative flex h-full min-h-0 shrink-0">
      <nav className="flex w-[74px] shrink-0 flex-col gap-1 overflow-y-auto border-r border-line bg-subtle p-2">
        {TABS.map((entry) => {
          const active = props.tab === entry.key
          return (
            <button
              key={entry.key}
              type="button"
              // Clicking the open tool closes it. The rail is a toggle, not a
              // set of radio buttons — there has to be a way back to a bare
              // canvas that isn't "pick the least useful panel".
              onClick={() => props.onTabChange(active ? null : entry.key)}
              aria-pressed={active}
              aria-expanded={active}
              className={`flex flex-col items-center gap-1 rounded-control px-1 py-2 text-[10px] font-medium transition ${
                active
                  ? 'bg-active text-brand'
                  : 'text-muted hover:bg-hover hover:text-ink'
              }`}
            >
              <entry.Icon className={`size-[18px] ${active ? 'text-brand' : ''}`} />
              {entry.label}
            </button>
          )
        })}
      </nav>

      <div
        className={`flex min-h-0 min-w-0 flex-col border-r border-line bg-surface max-md:absolute max-md:inset-y-0 max-md:left-full max-md:z-30 max-md:shadow-pop ${
          // Templates is a grid to pick from, not a list to read, so it gets
          // the width two columns of thumbnails actually need. The max-md cap
          // keeps either width inside a phone viewport minus the tab rail.
          props.tab === 'templates'
            ? 'w-[344px] shrink-0 max-md:w-[min(344px,calc(100vw-74px))]'
            : props.tab
              ? 'w-[300px] shrink-0 max-md:w-[min(300px,calc(100vw-74px))]'
              : 'hidden'
        }`}
      >
        {props.tab === 'templates' && <TemplatesTab {...props} />}
        {props.tab === 'elements' && <ElementsTab {...props} />}
        {props.tab === 'uploads' && <UploadsTab {...props} />}
        {props.tab === 'text' && <TextTab {...props} />}
        {props.tab === 'images' && <ImagesTab {...props} />}
        {props.tab === 'brand' && <BrandTab brandKit={props.brandKit} />}
        {props.tab === 'layers' && (
          <Scroll>
            <LayersPanel
              elements={props.elements}
              selectedId={props.selectedKey}
              onSelect={props.onSelect}
              onRename={props.onRenameElement}
              onToggleVisible={props.onToggleVisible}
              onToggleLocked={props.onToggleLocked}
              onReorder={props.onReorder}
              onDuplicate={props.onDuplicateElement}
              onDelete={props.onRemoveElement}
            />
          </Scroll>
        )}
      </div>
    </div>
  )
}

// -- shared chrome -----------------------------------------------------------

function Scroll({ children }: { children: React.ReactNode }) {
  return <div className="min-h-0 flex-1 overflow-y-auto p-3">{children}</div>
}

function SectionHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="mb-2 flex items-baseline justify-between">
      <h3 className="text-[12px] font-semibold text-ink">{title}</h3>
      {action}
    </div>
  )
}

function SeeAll({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-[11px] font-medium text-brand transition hover:underline"
    >
      See all
    </button>
  )
}

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] leading-relaxed text-muted">{children}</p>
}

/** Shown wherever a tool would otherwise offer an add button the server
 *  would refuse. */
function FixedLayoutNotice({ template }: { template: TemplateDetail }) {
  return (
    <Scroll>
      <p className="rounded-control border border-line bg-subtle px-3 py-2.5 text-[11px] leading-relaxed text-muted">
        <span className="font-semibold text-ink">{template.name}</span> is a fixed
        layout — new elements cannot be added to it. You can still edit the elements it
        already has.
      </p>
    </Scroll>
  )
}

// -- Elements ----------------------------------------------------------------

function ElementsTab({
  template,
  onAddElement,
  onAddShape,
  adding,
  listingPhotos,
  uploads,
  onTabChange,
}: Props) {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<Category>('all')
  const [recent, setRecent] = useState<string[]>(() => readRecent())

  /** Remembers what you reach for. Local to the browser — this is a
   *  convenience, not data worth a table. */
  const add = useCallback(
    (tile: Tile) => {
      // A shape card carries its own recipe and is placed locally; everything
      // else still goes through the server's per-type blueprint.
      const primitive = tile.shape ? shapePrimitive(tile.shape) : null
      if (primitive) onAddShape(primitive)
      else onAddElement(tile.kind)
      setRecent((current) => {
        const id = tileId(tile)
        const next = [id, ...current.filter((k) => k !== id)].slice(0, RECENT_LIMIT)
        try {
          window.localStorage.setItem(RECENT_KEY, JSON.stringify(next))
        } catch {
          /* private mode, quota — the panel still works without the memory */
        }
        return next
      })
    },
    [onAddElement, onAddShape],
  )

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return TILES.filter((tile) => {
      if (category !== 'all' && tile.category !== category) return false
      if (!needle) return true
      return `${tile.label} ${tile.keywords}`.toLowerCase().includes(needle)
    })
  }, [query, category])

  if (!template.allows_added_elements) return <FixedLayoutNotice template={template} />

  const byCategory = (key: Tile['category']) => visible.filter((tile) => tile.category === key)
  const shapes = byCategory('shapes')
  const frames = byCategory('frames')
  const lines = byCategory('lines')
  const recentTiles = recent
    .map((id) => TILES.find((tile) => tileId(tile) === id))
    .filter((tile): tile is Tile => Boolean(tile))

  const collections = [
    {
      key: 'photos',
      name: 'Listing photos',
      count: listingPhotos.length,
      thumbs: listingPhotos.slice(0, 3).map((photo) => photo.image_url).filter(Boolean) as string[],
      go: () => onTabChange('images'),
    },
    {
      key: 'uploads',
      name: 'Your uploads',
      count: uploads.length,
      thumbs: uploads.slice(0, 3).map((upload) => upload.url),
      go: () => onTabChange('uploads'),
    },
    {
      key: 'shapes',
      name: 'Shapes',
      count: TILES.filter((tile) => tile.category === 'shapes').length,
      thumbs: [],
      go: () => setCategory('shapes'),
    },
  ]

  return (
    <>
      <div className="space-y-2.5 border-b border-line p-3">
        <div className="flex items-center gap-1.5">
          <div className="relative min-w-0 flex-1">
            <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search elements, shapes, icons..."
              className="w-full rounded-control border border-line bg-subtle py-2 pl-8 pr-2.5 text-[12px] outline-none transition placeholder:text-muted focus:border-brand focus:bg-surface"
            />
          </div>
          <button
            type="button"
            onClick={() => setCategory('all')}
            title="Reset filters"
            aria-label="Reset filters"
            className="flex size-[34px] shrink-0 items-center justify-center rounded-control border border-line text-muted transition hover:bg-hover hover:text-ink"
          >
            <IconFilter className="size-4" />
          </button>
        </div>

        <div className="flex flex-wrap gap-1">
          {CATEGORIES.map((entry) => (
            <button
              key={entry.key}
              type="button"
              onClick={() => setCategory(entry.key)}
              className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition ${
                category === entry.key
                  ? 'bg-brand text-white'
                  : 'bg-subtle text-muted hover:bg-hover hover:text-ink'
              }`}
            >
              {entry.label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-3">
        {category === 'all' && !query && (
          <section>
            <SectionHeader title="Smart collections" />
            <div className="space-y-1.5">
              {collections.map((collection) => (
                <button
                  key={collection.key}
                  type="button"
                  onClick={collection.go}
                  className="flex w-full items-center gap-2.5 rounded-control border border-line p-2 text-left transition hover:border-brand/40 hover:bg-hover"
                >
                  <span className="flex -space-x-2">
                    {collection.thumbs.length > 0 ? (
                      collection.thumbs.map((src, index) => (
                        <img
                          key={index}
                          src={src}
                          alt=""
                          className="size-8 rounded-md border-2 border-surface object-cover"
                        />
                      ))
                    ) : (
                      <span className="flex size-8 items-center justify-center rounded-md bg-beige">
                        <IconElements className="size-4 text-brand/70" />
                      </span>
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12px] font-semibold text-ink">
                      {collection.name}
                    </span>
                    <span className="block text-[11px] text-muted">
                      {collection.count} item{collection.count === 1 ? '' : 's'}
                    </span>
                  </span>
                  <IconArrowRight className="size-4 shrink-0 text-muted" />
                </button>
              ))}
            </div>
          </section>
        )}

        {shapes.length > 0 && (
          <section>
            <SectionHeader
              title="Shapes"
              action={category === 'all' ? <SeeAll onClick={() => setCategory('shapes')} /> : undefined}
            />
            <TileGrid tiles={shapes} onAdd={add} disabled={adding} />
          </section>
        )}

        {frames.length > 0 && (
          <section>
            <SectionHeader
              title="Frames"
              action={category === 'all' ? <SeeAll onClick={() => setCategory('frames')} /> : undefined}
            />
            <TileGrid tiles={frames} onAdd={add} disabled={adding} />
            <p className="mt-1.5 text-[11px] leading-relaxed text-muted">
              A frame is an image slot — add one, then fill it from Images or Uploads.
            </p>
          </section>
        )}

        {lines.length > 0 && (
          <section>
            <SectionHeader title="Lines" />
            <TileGrid tiles={lines} onAdd={add} disabled={adding} />
          </section>
        )}

        {category === 'icons' && (
          <p className="rounded-control border border-dashed border-line bg-subtle px-3 py-6 text-center text-[11px] text-muted">
            No icon library yet.
          </p>
        )}

        {visible.length === 0 && category !== 'icons' && (
          <p className="rounded-control border border-dashed border-line bg-subtle px-3 py-6 text-center text-[11px] text-muted">
            Nothing matches “{query}”.
          </p>
        )}

        {recentTiles.length > 0 && category === 'all' && !query && (
          <section>
            <SectionHeader title="Recently used" />
            <TileGrid tiles={recentTiles} onAdd={add} disabled={adding} />
          </section>
        )}
      </div>

      <AiImageGeneratorCard />
    </>
  )
}

function TileGrid({
  tiles,
  onAdd,
  disabled,
}: {
  tiles: Tile[]
  onAdd: (tile: Tile) => void
  disabled: boolean
}) {
  return (
    <div className="grid grid-cols-2 gap-1.5">
      {tiles.map((tile) => (
        <button
          key={`${tile.category}-${tileId(tile)}`}
          type="button"
          disabled={disabled}
          onClick={() => onAdd(tile)}
          // Shape cards can also be dragged straight onto the canvas, landing
          // where they are dropped. The payload is just the primitive's key —
          // the drop side looks the recipe up itself, so the two ends can
          // never disagree about what a "circle" is.
          draggable={Boolean(tile.shape) && !disabled}
          onDragStart={(event) => {
            if (!tile.shape) return
            event.dataTransfer.setData(SHAPE_DRAG_MIME, tile.shape)
            event.dataTransfer.effectAllowed = 'copy'
          }}
          title={
            tile.shape
              ? `Add ${tile.label.toLowerCase()} — click, or drag it onto the canvas`
              : `Add ${tile.label.toLowerCase()}`
          }
          className="group flex flex-col items-center justify-center gap-2 rounded-control border border-line bg-surface py-4 transition hover:border-brand/40 hover:bg-hover disabled:opacity-50"
        >
          <span className="flex h-9 items-center justify-center">{tile.swatch}</span>
          <span className="text-[10px] font-medium text-muted transition group-hover:text-ink">
            {tile.label}
          </span>
        </button>
      ))}
    </div>
  )
}

/**
 * The AI entry point.
 *
 * Rendered because the product's creative panel calls for it, and wired to
 * nothing because there is no image-generation service behind it yet. It
 * says so on click rather than failing silently or pretending to work.
 */
function AiImageGeneratorCard() {
  const [noticed, setNoticed] = useState(false)

  return (
    <div className="border-t border-line p-3">
      <div className="rounded-panel border border-line bg-subtle p-3">
        <div className="flex items-center gap-2">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-control bg-brand-soft text-brand">
            <IconSparkle className="size-4" />
          </span>
          <span className="text-[12px] font-semibold text-ink">AI Image Generator</span>
          <span className="rounded-full bg-brand-soft px-1.5 py-px text-[9px] font-bold uppercase tracking-wide text-brand">
            Beta
          </span>
        </div>

        <p className="mt-2 text-[11px] leading-relaxed text-muted">
          Generate stunning property images for your designs.
        </p>

        <button
          type="button"
          onClick={() => setNoticed(true)}
          className="mt-2.5 flex w-full items-center justify-center gap-1.5 rounded-control bg-brand py-2 text-[12px] font-semibold text-white transition hover:bg-brand-strong"
        >
          <IconSparkle className="size-4" />
          Generate image
        </button>

        {noticed && (
          <p role="status" className="mt-2 text-[11px] leading-relaxed text-muted">
            Image generation isn’t connected yet — this is the entry point only.
          </p>
        )}
      </div>
    </div>
  )
}

// -- Templates ---------------------------------------------------------------

/**
 * The template grid: thumbnails to pick from, not a card describing the one
 * you already have.
 *
 * PICKING ONE STARTS A DESIGN — IT DOES NOT SWAP THIS ONE'S TEMPLATE
 * ---------------------------------------------------------------------------
 * Every element on this canvas was copied from the current template, so
 * changing the template under them replaces the canvas: your edits, your
 * added elements, your moved photo, gone. That is a "start a new design"
 * action wearing a panel's clothes, so it is labelled and behaves as one —
 * the design you are in is left exactly as it was.
 *
 * The explanation for that lives on the header's help affordance rather than
 * as a paragraph in the panel. A grid you pick from should be thumbnails
 * top-to-bottom; prose you have already read is dead weight in the middle
 * of it.
 */
function TemplatesTab({
  template,
  onPickTemplate,
  pickingTemplate,
  hasListing,
}: Props) {
  const [all, setAll] = useState<TemplateSummary[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [query, setQuery] = useState('')

  useEffect(() => {
    fetchTemplates()
      .then((page) => setAll(page.results))
      .catch(() => setFailed(true))
  }, [])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!all) return []
    if (!needle) return all
    return all.filter((entry) =>
      `${entry.name} ${entry.category_display} ${entry.style_display}`
        .toLowerCase()
        .includes(needle),
    )
  }, [all, query])

  return (
    <>
      <div className="space-y-2.5 border-b border-line p-3">
        <SectionHeader
          title="Templates"
          action={
            <span
              tabIndex={0}
              role="note"
              title={
                'A design keeps the template it was started from — its elements were ' +
                'copied from it. Picking another one here starts a new design and ' +
                'leaves this one untouched.'
              }
              className="flex size-4 cursor-help items-center justify-center rounded-full bg-subtle text-[9px] font-bold text-muted transition hover:bg-hover hover:text-ink"
            >
              ?
            </span>
          }
        />
        <div className="relative">
          <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search templates..."
            className="w-full rounded-control border border-line bg-subtle py-2 pl-8 pr-2.5 text-[12px] outline-none transition placeholder:text-muted focus:border-brand focus:bg-surface"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {failed && <Hint>Could not load the template library.</Hint>}
        {!all && !failed && <Hint>Loading…</Hint>}

        {all && visible.length === 0 && (
          <p className="rounded-control border border-dashed border-line bg-subtle px-3 py-6 text-center text-[11px] text-muted">
            {query ? `Nothing matches “${query}”.` : 'No templates yet.'}
          </p>
        )}

        {visible.length > 0 && (
          <ul className="grid grid-cols-2 gap-2">
            {visible.map((entry) => {
              const current = entry.id === template.id
              const blocked = entry.requires_listing && !hasListing
              return (
                <li key={entry.id}>
                  <button
                    type="button"
                    disabled={current || blocked || pickingTemplate !== null}
                    onClick={() => onPickTemplate(entry)}
                    title={
                      current
                        ? 'This design is built on this template'
                        : blocked
                          ? 'This template describes a property. Attach a listing to use it.'
                          : `Start a new design from ${entry.name}`
                    }
                    className={`w-full overflow-hidden rounded-control border text-left transition disabled:cursor-not-allowed ${
                      current
                        ? 'border-brand ring-1 ring-brand/40'
                        : 'border-line hover:border-brand/50 hover:shadow-panel disabled:opacity-50'
                    }`}
                  >
                    <TemplateThumb template={entry} className="h-20" showStyleLabel={false}>
                      {current && (
                        <span className="absolute left-1.5 top-1.5 rounded bg-brand px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">
                          Current
                        </span>
                      )}
                      {pickingTemplate === entry.id && (
                        <span className="absolute inset-0 flex items-center justify-center bg-white/80 text-[10px] font-semibold text-ink">
                          Opening…
                        </span>
                      )}
                    </TemplateThumb>
                    <div className="p-2">
                      <p className="truncate text-[11px] font-semibold text-ink">{entry.name}</p>
                      <span className="mt-1 inline-block rounded-full bg-subtle px-1.5 py-0.5 text-[9px] font-medium text-muted">
                        {entry.category_display}
                      </span>
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="border-t border-line p-3">
        <Link
          to="/templates"
          className="inline-flex items-center gap-1.5 rounded-control border border-line px-2.5 py-1.5 text-[12px] font-medium text-ink transition hover:bg-hover"
        >
          Open the full library
          <IconArrowRight className="size-3.5 text-muted" />
        </Link>
      </div>
    </>
  )
}

// -- Text --------------------------------------------------------------------

function TextTab({ template, onAddElement, adding }: Props) {
  if (!template.allows_added_elements) return <FixedLayoutNotice template={template} />

  return (
    <Scroll>
      <div className="space-y-2">
        <SectionHeader title="Add text" />
        <button
          type="button"
          disabled={adding}
          onClick={() => onAddElement('text')}
          className="w-full rounded-control border border-line px-3 py-3 text-left transition hover:border-brand/40 hover:bg-hover disabled:opacity-50"
        >
          <span className="block text-lg font-bold leading-tight text-ink">Heading</span>
          <span className="text-[10px] text-muted">Large, bold</span>
        </button>
        <button
          type="button"
          disabled={adding}
          onClick={() => onAddElement('text')}
          className="w-full rounded-control border border-line px-3 py-3 text-left transition hover:border-brand/40 hover:bg-hover disabled:opacity-50"
        >
          <span className="block text-sm leading-tight text-ink">Body text</span>
          <span className="text-[10px] text-muted">Regular weight</span>
        </button>
        <button
          type="button"
          disabled={adding}
          onClick={() => onAddElement('button')}
          className="w-full rounded-control border border-line px-3 py-3 text-left transition hover:border-brand/40 hover:bg-hover disabled:opacity-50"
        >
          <span className="inline-block rounded-full bg-brand px-2 py-0.5 text-[10px] font-bold text-white">
            BADGE
          </span>
          <span className="mt-1 block text-[10px] text-muted">Pill with a background</span>
        </button>

        <Hint>Double-click any text on the canvas to edit it in place.</Hint>
      </div>
    </Scroll>
  )
}

// -- image tools -------------------------------------------------------------

function ImageTargetHint({
  selectedElement,
  onApplyImage,
}: {
  selectedElement: ResolvedElement | null
  onApplyImage: Props['onApplyImage']
}) {
  if (onApplyImage) {
    return (
      <Hint>
        Click an image to put it in{' '}
        <span className="font-semibold text-ink">
          {selectedElement?.name}
        </span>
        .
      </Hint>
    )
  }
  return (
    <p className="rounded-control border border-line bg-subtle px-2.5 py-2 text-[11px] leading-relaxed text-muted">
      Select an image element on the canvas first — or add a frame from Elements — and
      these will drop into it.
    </p>
  )
}

function ImageGrid({
  items,
  disabled,
  onPick,
}: {
  items: { key: string; url: string; title?: string; imageKey: string }[]
  disabled: boolean
  onPick: (imageKey: string, url: string) => void
}) {
  return (
    <div className="grid grid-cols-3 gap-1.5">
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          disabled={disabled}
          title={item.title}
          onClick={() => onPick(item.imageKey, item.url)}
          className="aspect-square overflow-hidden rounded-control border border-line transition hover:border-brand disabled:cursor-not-allowed disabled:opacity-50"
        >
          <img src={item.url} alt="" className="size-full object-cover" />
        </button>
      ))}
    </div>
  )
}

function UploadsTab({ uploads, onUploadFile, uploading, onApplyImage, selectedElement }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null)

  return (
    <Scroll>
      <div className="space-y-3">
        <SectionHeader title="Uploads" />

        <button
          type="button"
          disabled={uploading}
          onClick={() => fileInputRef.current?.click()}
          className="flex w-full flex-col items-center gap-1 rounded-control border border-dashed border-line bg-subtle px-3 py-5 text-[12px] font-medium text-ink transition hover:border-brand/50 hover:bg-hover disabled:opacity-50"
        >
          <IconUpload className="size-5 text-brand" />
          {uploading ? 'Uploading…' : 'Upload an image'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) onUploadFile(file)
            event.target.value = ''
          }}
        />

        <ImageTargetHint selectedElement={selectedElement} onApplyImage={onApplyImage} />

        {uploads.length === 0 ? (
          <Hint>Nothing uploaded in this session yet.</Hint>
        ) : (
          <ImageGrid
            disabled={!onApplyImage}
            onPick={(imageKey, url) => onApplyImage?.(imageKey, url)}
            items={uploads.map((upload) => ({
              key: upload.image_key,
              imageKey: upload.image_key,
              url: upload.url,
            }))}
          />
        )}
      </div>
    </Scroll>
  )
}

function ImagesTab({ listingPhotos, onApplyImage, selectedElement }: Props) {
  return (
    <Scroll>
      <div className="space-y-3">
        <SectionHeader title="Listing photos" />
        <ImageTargetHint selectedElement={selectedElement} onApplyImage={onApplyImage} />

        {listingPhotos.length === 0 ? (
          <Hint>This design has no listing attached, or the listing has no photos yet.</Hint>
        ) : (
          <ImageGrid
            disabled={!onApplyImage}
            onPick={(imageKey, url) => onApplyImage?.(imageKey, url)}
            items={listingPhotos.map((photo) => ({
              key: String(photo.id),
              imageKey: photo.image_key,
              url: photo.image_url ?? '',
              title: photo.caption || undefined,
            }))}
          />
        )}
      </div>
    </Scroll>
  )
}

// -- Brand -------------------------------------------------------------------

/**
 * The brand kit, for reference while designing.
 *
 * Read-only on purpose: these colours already reach the artwork through
 * `@accent_color`-style tokens that templates resolve at render time, and
 * the kit itself is edited on its own page. Showing it here answers "what
 * are my brand colours" without adding a second place to change them.
 */
function BrandTab({ brandKit }: { brandKit: BrandKit | null }) {
  if (!brandKit) {
    return (
      <Scroll>
        <div className="space-y-3">
          <SectionHeader title="Brand kit" />
          <Hint>No brand kit yet. Set your colours and fonts to use them in designs.</Hint>
          <Link
            to="/brand-kit"
            className="inline-flex items-center gap-1.5 rounded-control border border-line px-2.5 py-1.5 text-[12px] font-medium text-ink transition hover:bg-hover"
          >
            Set up brand kit
            <IconArrowRight className="size-3.5 text-muted" />
          </Link>
        </div>
      </Scroll>
    )
  }

  const swatches = [
    { label: 'Primary', value: brandKit.primary_color, token: '@primary_color' },
    { label: 'Secondary', value: brandKit.secondary_color, token: '@secondary_color' },
    { label: 'Accent', value: brandKit.accent_color, token: '@accent_color' },
  ]

  return (
    <Scroll>
      <div className="space-y-4">
        <section>
          <SectionHeader title="Colours" />
          <div className="space-y-1.5">
            {swatches.map((swatch) => (
              <div
                key={swatch.label}
                className="flex items-center gap-2.5 rounded-control border border-line p-2"
              >
                <span
                  className="size-8 shrink-0 rounded-md border border-line"
                  style={{ backgroundColor: swatch.value }}
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-[12px] font-semibold text-ink">{swatch.label}</span>
                  <span className="block font-mono text-[10px] uppercase text-muted">
                    {swatch.value}
                  </span>
                </span>
                <span className="shrink-0 rounded bg-subtle px-1.5 py-0.5 font-mono text-[9px] text-muted">
                  {swatch.token}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section>
          <SectionHeader title="Typography" />
          <div className="space-y-1.5">
            <div className="rounded-control border border-line p-2.5">
              <p className="text-[10px] uppercase tracking-wide text-muted">Heading</p>
              <p className="text-[13px] font-semibold text-ink">{brandKit.heading_font}</p>
            </div>
            <div className="rounded-control border border-line p-2.5">
              <p className="text-[10px] uppercase tracking-wide text-muted">Body</p>
              <p className="text-[13px] text-ink">{brandKit.body_font}</p>
            </div>
          </div>
        </section>

        <Hint>
          A template using <span className="font-mono text-[10px]">@accent_color</span> picks these
          up automatically. Edit them on the Brand Kit page.
        </Hint>
        <Link
          to="/brand-kit"
          className="inline-flex items-center gap-1.5 rounded-control border border-line px-2.5 py-1.5 text-[12px] font-medium text-ink transition hover:bg-hover"
        >
          Open brand kit
          <IconArrowRight className="size-3.5 text-muted" />
        </Link>
      </div>
    </Scroll>
  )
}

// -- exported helpers --------------------------------------------------------

/** Exported for the page's "is this element an image slot" check, so the
 *  image tabs and the toolbar agree on what counts. */
export function isImageElement(element: ResolvedElement | null): boolean {
  return element !== null && elementKind(element) === 'image'
}

/** Tracks which tool is open. Nothing, by default: the editor opens on the
 *  design, and every panel is one click away on the rail. */
export function useLeftPanelTab(initial: LeftPanelTab | null = null) {
  return useState<LeftPanelTab | null>(initial)
}
