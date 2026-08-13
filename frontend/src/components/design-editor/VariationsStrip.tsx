/**
 * The strip along the bottom of the workspace: every design built from this
 * template, with the one you are editing highlighted.
 *
 * WHY THESE ARE CALLED VARIATIONS AND NOT PAGES
 * ---------------------------------------------------------------------------
 * A `Design` is exactly one canvas. There is no page model, no page number
 * and no ordering column — `Design.Meta.ordering` is `-updated_at`. So the
 * things in this strip are sibling designs from one template: each has its
 * own overrides, its own compliance result and its own export. Calling them
 * "pages" would promise something the export path does not do — pages of one
 * document come out as one file, and these do not. Naming them for what they
 * are keeps that expectation straight.
 *
 * Platform formats (Instagram Post, Story, Facebook, ...) are a different
 * axis entirely and stay where they were, above the canvas: one design
 * renders at every size. They are deliberately not mixed in here.
 */

import { useEffect, useRef, useState } from 'react'

import type { Design } from '../../api/templates.ts'
import { IconMore, IconPlus } from '../icons.tsx'

type Props = {
  /** Every design on this template, newest first from the API. */
  variations: Design[]
  currentId: number
  /** Aspect of the format currently being edited, so thumbnails match it. */
  aspect: number
  /** The template's canvas colour, used when a variation has no export to
   *  show yet — better than an empty grey box. */
  backgroundColor: string
  busy: boolean
  onOpen: (id: number) => void
  onAdd: () => void
  onDuplicate: (design: Design) => void
  onRename: (design: Design) => void
  onDelete: (design: Design) => void
}

/** The most recent rendered export, if this design has ever been exported.
 *  Nothing is rendered on demand here — a strip that fired a render per
 *  variation on every editor load would be a lot of Chromium for a thumbnail. */
function thumbnailOf(design: Design): string | null {
  return design.exports.find((entry) => entry.image_url)?.image_url ?? null
}

export default function VariationsStrip({
  variations,
  currentId,
  aspect,
  backgroundColor,
  busy,
  onOpen,
  onAdd,
  onDuplicate,
  onRename,
  onDelete,
}: Props) {
  /**
   * The open menu, with the viewport rect of the button that opened it.
   *
   * The rect is not decoration. The card row scrolls horizontally, and a box
   * with `overflow-x: auto` computes `overflow-y` to `auto` as well — so an
   * absolutely-positioned menu drawn above a card is clipped clean away by
   * the scroller. It stays in the DOM and reads as visible to a test, but
   * `elementFromPoint` lands on the strip behind it and no click ever reaches
   * it. Positioning the menu `fixed` against this rect takes it out of the
   * scroller's clip entirely.
   */
  const [menu, setMenu] = useState<{ id: number; anchor: DOMRect } | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menu) return
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenu(null)
    }
    // A fixed menu cannot follow its card, so anything that moves the card
    // dismisses the menu rather than leaving it stranded.
    const dismiss = () => setMenu(null)
    window.addEventListener('mousedown', close)
    window.addEventListener('resize', dismiss)
    window.addEventListener('scroll', dismiss, true)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('resize', dismiss)
      window.removeEventListener('scroll', dismiss, true)
    }
  }, [menu])

  // Oldest first, so the numbering reads like a sequence rather than
  // reshuffling every time one is edited.
  const ordered = [...variations].sort((a, b) => a.id - b.id)

  return (
    <div className="shrink-0 rounded-panel border border-line bg-surface px-3 py-2.5 shadow-panel">
      <div className="mb-2 flex items-baseline gap-2">
        <h3 className="text-[11px] font-semibold text-ink">Variations</h3>
        <span className="text-[10px] text-muted">
          {ordered.length} design{ordered.length === 1 ? '' : 's'} from this template
        </span>
      </div>

      <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
        <button
          type="button"
          onClick={onAdd}
          disabled={busy}
          title="Create another design from this template"
          className="flex h-[74px] w-[62px] shrink-0 flex-col items-center justify-center gap-1 rounded-control border border-dashed border-line bg-subtle text-[10px] font-medium text-muted transition hover:border-brand/50 hover:bg-hover hover:text-ink disabled:opacity-50"
        >
          <IconPlus className="size-4" />
          Add
        </button>

        {ordered.map((design, index) => {
          const active = design.id === currentId
          const thumbnail = thumbnailOf(design)

          return (
            <div key={design.id} className="group relative shrink-0">
              <button
                type="button"
                onClick={() => !active && onOpen(design.id)}
                title={design.name}
                aria-current={active}
                className={`block h-[74px] overflow-hidden rounded-control border-2 transition ${
                  active
                    ? 'border-brand shadow-pop'
                    : 'border-line hover:border-brand/40'
                }`}
                style={{ width: Math.max(44, Math.round(74 * aspect)) }}
              >
                {thumbnail ? (
                  <img src={thumbnail} alt="" className="size-full object-cover" />
                ) : (
                  <span
                    className="flex size-full items-center justify-center text-[9px] text-muted"
                    style={{ backgroundColor }}
                  >
                    No export
                  </span>
                )}
              </button>

              <span
                className={`pointer-events-none absolute bottom-1 left-1 rounded px-1 py-px text-[9px] font-bold tabular-nums ${
                  active ? 'bg-brand text-white' : 'bg-surface/85 text-muted'
                }`}
              >
                {String(index + 1).padStart(2, '0')}
              </span>

              <button
                type="button"
                onClick={(event) =>
                  setMenu(
                    menu?.id === design.id
                      ? null
                      : { id: design.id, anchor: event.currentTarget.getBoundingClientRect() },
                  )
                }
                aria-label={`Actions for ${design.name}`}
                title="Actions"
                className={`absolute right-0.5 top-0.5 flex size-5 items-center justify-center rounded bg-surface/85 text-muted transition hover:text-ink focus-visible:opacity-100 group-hover:opacity-100 ${
                  menu?.id === design.id ? 'text-ink opacity-100' : 'opacity-0'
                }`}
              >
                <IconMore className="size-3.5" />
              </button>

              {menu?.id === design.id && (
                <div
                  ref={menuRef}
                  className="fixed z-50 w-36 overflow-hidden rounded-panel border border-line bg-surface py-1 shadow-pop"
                  style={{
                    right: Math.max(8, window.innerWidth - menu.anchor.right),
                    bottom: window.innerHeight - menu.anchor.top + 4,
                  }}
                >
                  <MenuItem
                    onClick={() => {
                      setMenu(null)
                      onRename(design)
                    }}
                  >
                    Rename…
                  </MenuItem>
                  <MenuItem
                    onClick={() => {
                      setMenu(null)
                      onDuplicate(design)
                    }}
                  >
                    Duplicate
                  </MenuItem>
                  {/* Deleting the design you are currently editing is offered
                      once, in the header's overflow menu — not here, where it
                      would sit a stray click away from the thumbnail you are
                      working in. */}
                  {!active && (
                    <>
                      <div className="my-1 h-px bg-line" />
                      <MenuItem
                        danger
                        onClick={() => {
                          setMenu(null)
                          onDelete(design)
                        }}
                      >
                        Delete
                      </MenuItem>
                    </>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MenuItem({
  onClick,
  danger,
  children,
}: {
  onClick: () => void
  danger?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`block w-full px-3 py-1.5 text-left text-[12px] font-medium transition hover:bg-hover ${
        danger ? 'text-danger' : 'text-ink'
      }`}
    >
      {children}
    </button>
  )
}
