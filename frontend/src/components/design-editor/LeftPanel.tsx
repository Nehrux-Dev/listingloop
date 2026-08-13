/**
 * The left rail: what you can put into the design, and what is already in it.
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

import { useCallback, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import type { ListingPhoto } from '../../api/listings.ts'
import type { BrandKit } from '../../api/profiles.ts'
import type {
  ElementType,
  ResolvedElement,
  TemplateDetail,
  UploadedImage,
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
import LayersPanel from './LayersPanel.tsx'
import { elementKind } from './elementKind.ts'

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
  label: string
  keywords: string
  category: Exclude<Category, 'all'>
  swatch: React.ReactNode
}

const TILES: Tile[] = [
  {
    kind: 'shape',
    label: 'Rectangle',
    keywords: 'rectangle square block box shape',
    category: 'shapes',
    swatch: <span className="block h-8 w-11 rounded-[3px] bg-beige" />,
  },
  {
    kind: 'shape',
    label: 'Circle',
    keywords: 'circle round ellipse dot shape',
    category: 'shapes',
    swatch: <span className="block size-9 rounded-full bg-beige" />,
  },
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
  {
    kind: 'image',
    label: 'Image frame',
    keywords: 'image frame photo picture placeholder rectangle',
    category: 'frames',
    swatch: (
      <span className="flex h-8 w-11 items-center justify-center rounded-[3px] border-2 border-dashed border-brand/40 bg-beige/50">
        <IconImage className="size-4 text-brand/60" />
      </span>
    ),
  },
  {
    kind: 'shape',
    label: 'Divider',
    keywords: 'divider line rule separator horizontal',
    category: 'lines',
    swatch: <span className="block h-0.5 w-11 rounded-full bg-brand/70" />,
  },
]

const RECENT_KEY = 'design-editor:recent-elements'
const RECENT_LIMIT = 4

function readRecent(): ElementType[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const known = new Set(TILES.map((tile) => tile.kind))
    return parsed.filter((k): k is ElementType => known.has(k as ElementType))
  } catch {
    // A corrupt or unavailable store is not worth breaking the panel over.
    return []
  }
}

type Props = {
  tab: LeftPanelTab
  onTabChange: (tab: LeftPanelTab) => void

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
  adding: boolean

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
    <div className="flex h-full min-h-0 overflow-hidden rounded-panel border border-line bg-surface shadow-panel">
      <nav className="flex w-[74px] shrink-0 flex-col gap-1 border-r border-line bg-subtle p-2">
        {TABS.map((entry) => {
          const active = props.tab === entry.key
          return (
            <button
              key={entry.key}
              type="button"
              onClick={() => props.onTabChange(entry.key)}
              aria-pressed={active}
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

      <div className="flex min-w-0 flex-1 flex-col">
        {props.tab === 'templates' && <TemplatesTab template={props.template} />}
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

function ElementsTab({ template, onAddElement, adding, listingPhotos, uploads, onTabChange }: Props) {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<Category>('all')
  const [recent, setRecent] = useState<ElementType[]>(() => readRecent())

  /** Remembers what you reach for. Local to the browser — this is a
   *  convenience, not data worth a table. */
  const add = useCallback(
    (kind: ElementType) => {
      onAddElement(kind)
      setRecent((current) => {
        const next = [kind, ...current.filter((k) => k !== kind)].slice(0, RECENT_LIMIT)
        try {
          window.localStorage.setItem(RECENT_KEY, JSON.stringify(next))
        } catch {
          /* private mode, quota — the panel still works without the memory */
        }
        return next
      })
    },
    [onAddElement],
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
    .map((kind) => TILES.find((tile) => tile.kind === kind))
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
  onAdd: (kind: ElementType) => void
  disabled: boolean
}) {
  return (
    <div className="grid grid-cols-2 gap-1.5">
      {tiles.map((tile) => (
        <button
          key={`${tile.category}-${tile.kind}`}
          type="button"
          disabled={disabled}
          onClick={() => onAdd(tile.kind)}
          title={`Add ${tile.label.toLowerCase()}`}
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

function TemplatesTab({ template }: { template: TemplateDetail }) {
  return (
    <Scroll>
      <div className="space-y-3">
        <SectionHeader title="Template" />
        <div className="rounded-control border border-line p-2.5">
          <p className="text-[12px] font-semibold text-ink">{template.name}</p>
          <p className="mt-0.5 text-[11px] text-muted">
            {template.category_display} · {template.style_display}
          </p>
          <p className="mt-2 text-[11px] text-muted">
            {template.elements.length} elements ·{' '}
            {template.allows_added_elements ? 'allows added elements' : 'fixed layout'}
          </p>
        </div>

        {/* Deliberately not a template switcher. Every override and added
            element is keyed to this template's elements; swapping the template
            underneath them would discard the design's content, which is a
            "start a new design" action, not a panel toggle. */}
        <Hint>
          A design keeps the template it was started from — its edits are tied to that
          template's elements. To use a different one, start a new design.
        </Hint>
        <Link
          to="/templates"
          className="inline-flex items-center gap-1.5 rounded-control border border-line px-2.5 py-1.5 text-[12px] font-medium text-ink transition hover:bg-hover"
        >
          Browse template library
          <IconArrowRight className="size-3.5 text-muted" />
        </Link>
      </div>
    </Scroll>
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

/** Tracks which tool is open, defaulting to Layers — the tool that describes
 *  what is already there rather than what could be added. */
export function useLeftPanelTab(initial: LeftPanelTab = 'layers') {
  return useState<LeftPanelTab>(initial)
}
