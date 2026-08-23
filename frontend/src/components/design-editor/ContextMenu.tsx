/**
 * The right-click menu for the canvas — the same surface Canva opens on an
 * element: copy/paste, duplicate, delete, restacking, page alignment, lock.
 *
 * It renders nothing an element can't already have done to it elsewhere in
 * the editor; every row calls back into the page's existing handlers, so the
 * menu introduces no second way to mutate a design — only a faster route to
 * the first one. That is also why the actions arrive as props rather than
 * being computed here: the page owns the draft, history and autosave, and
 * this component only owns where the menu sits and when it closes.
 *
 * Three menus share this component, keyed off `element`:
 *  - null            → the empty-canvas menu (just Paste)
 *  - a locked one    → Copy + Unlock, because a locked element is meant to
 *                      resist everything else (mirrors Canva's behaviour)
 *  - anything else   → the full menu
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { ResolvedElement } from '../../api/templates.ts'
import {
  IconAlignBottom,
  IconAlignCenterH,
  IconAlignLeft,
  IconAlignMiddleV,
  IconAlignRight,
  IconAlignTop,
  IconChevronRight,
  IconClipboard,
  IconCopy,
  IconLayers,
  IconLock,
  IconPaintRoller,
  IconPlus,
  IconTrash,
  IconUnlock,
} from '../icons.tsx'

export type LayerAction = 'forward' | 'front' | 'backward' | 'back'
export type AlignAction = 'left' | 'center' | 'right' | 'top' | 'middle' | 'bottom'

type Props = {
  /** Where the pointer was, in viewport pixels. The menu clamps itself so it
   *  never runs off screen near an edge. */
  x: number
  y: number
  /** The element under the pointer, or null for the empty-canvas menu. */
  element: ResolvedElement | null
  canPaste: boolean
  canPasteStyle: boolean
  onCopy: () => void
  onCopyStyle: () => void
  onPaste: () => void
  onPasteStyle: () => void
  onDuplicate: () => void
  onDelete: () => void
  onLayer: (action: LayerAction) => void
  onAlign: (action: AlignAction) => void
  onToggleLock: () => void
  onClose: () => void
}

/** Breathing room the clamp keeps between the menu and the viewport edge. */
const EDGE_MARGIN = 8
/** Menu and submenu widths, matching the Tailwind classes below — needed as
 *  numbers to decide whether a submenu must open leftward. */
const MENU_WIDTH = 240
const SUBMENU_WIDTH = 200

export default function CanvasContextMenu({
  x,
  y,
  element,
  canPaste,
  canPasteStyle,
  onCopy,
  onCopyStyle,
  onPaste,
  onPasteStyle,
  onDuplicate,
  onDelete,
  onLayer,
  onAlign,
  onToggleLock,
  onClose,
}: Props) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ left: x, top: y })
  const [openSub, setOpenSub] = useState<'layer' | 'align' | null>(null)

  // Measure after mount, then clamp — the menu's height depends on which of
  // the three variants rendered, so it can't be predicted from constants.
  useLayoutEffect(() => {
    const node = menuRef.current
    if (!node) return
    setPosition({
      left: Math.max(EDGE_MARGIN, Math.min(x, window.innerWidth - node.offsetWidth - EDGE_MARGIN)),
      top: Math.max(EDGE_MARGIN, Math.min(y, window.innerHeight - node.offsetHeight - EDGE_MARGIN)),
    })
    setOpenSub(null)
  }, [x, y, element])

  // Dismissal: click anywhere else, Escape, scrolling or resizing the
  // workspace (which would leave the menu floating over the wrong spot).
  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (
        menuRef.current &&
        event.target instanceof Node &&
        menuRef.current.contains(event.target)
      ) {
        return
      }
      onClose()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onClose, true)
    window.addEventListener('resize', onClose)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onClose, true)
      window.removeEventListener('resize', onClose)
    }
  }, [onClose])

  /** Run the action, then close — every row behaves this way. */
  const run = (action: () => void) => () => {
    action()
    onClose()
  }

  const closeSub = () => setOpenSub(null)
  const flipSubmenu = position.left + MENU_WIDTH + SUBMENU_WIDTH > window.innerWidth

  return (
    <div
      ref={menuRef}
      role="menu"
      className="fixed z-50 w-60 rounded-panel border border-line bg-surface py-1.5 shadow-pop"
      style={{ left: position.left, top: position.top }}
      // A second right-click inside the menu should not open the browser's own.
      onContextMenu={(event) => event.preventDefault()}
      // The mat's click handler deselects; a menu click must not reach it.
      onClick={(event) => event.stopPropagation()}
    >
      {element === null ? (
        <MenuItem
          icon={<IconClipboard className="size-4" />}
          label="Paste"
          shortcut="Ctrl+V"
          disabled={!canPaste}
          onSelect={run(onPaste)}
        />
      ) : element.locked ? (
        <>
          <MenuItem
            icon={<IconCopy className="size-4" />}
            label="Copy"
            shortcut="Ctrl+C"
            onSelect={run(onCopy)}
          />
          <Separator />
          <MenuItem
            icon={<IconUnlock className="size-4" />}
            label="Unlock"
            shortcut="Alt+Shift+L"
            onSelect={run(onToggleLock)}
          />
        </>
      ) : (
        <>
          <MenuItem
            icon={<IconCopy className="size-4" />}
            label="Copy"
            shortcut="Ctrl+C"
            onSelect={run(onCopy)}
            onHover={closeSub}
          />
          <MenuItem
            icon={<IconPaintRoller className="size-4" />}
            label="Copy style"
            shortcut="Ctrl+Alt+C"
            onSelect={run(onCopyStyle)}
            onHover={closeSub}
          />
          <MenuItem
            icon={<IconClipboard className="size-4" />}
            label="Paste"
            shortcut="Ctrl+V"
            disabled={!canPaste}
            onSelect={run(onPaste)}
            onHover={closeSub}
          />
          <MenuItem
            icon={<IconPaintRoller className="size-4" />}
            label="Paste style"
            shortcut="Ctrl+Alt+V"
            disabled={!canPasteStyle}
            onSelect={run(onPasteStyle)}
            onHover={closeSub}
          />
          <MenuItem
            icon={<IconPlus className="size-4" />}
            label="Duplicate"
            shortcut="Ctrl+D"
            onSelect={run(onDuplicate)}
            onHover={closeSub}
          />
          <MenuItem
            icon={<IconTrash className="size-4" />}
            label="Delete"
            shortcut="DELETE"
            onSelect={run(onDelete)}
            onHover={closeSub}
          />

          <Separator />

          <SubmenuItem
            icon={<IconLayers className="size-4" />}
            label="Layer"
            open={openSub === 'layer'}
            onOpen={() => setOpenSub('layer')}
            flip={flipSubmenu}
          >
            <MenuItem label="Bring forward" shortcut="Ctrl+]" onSelect={run(() => onLayer('forward'))} />
            <MenuItem label="Bring to front" shortcut="Ctrl+Alt+]" onSelect={run(() => onLayer('front'))} />
            <MenuItem label="Send backward" shortcut="Ctrl+[" onSelect={run(() => onLayer('backward'))} />
            <MenuItem label="Send to back" shortcut="Ctrl+Alt+[" onSelect={run(() => onLayer('back'))} />
          </SubmenuItem>

          <SubmenuItem
            icon={<IconAlignLeft className="size-4" />}
            label="Align to page"
            open={openSub === 'align'}
            onOpen={() => setOpenSub('align')}
            flip={flipSubmenu}
          >
            <MenuItem icon={<IconAlignLeft className="size-4" />} label="Left" onSelect={run(() => onAlign('left'))} />
            <MenuItem icon={<IconAlignCenterH className="size-4" />} label="Center" onSelect={run(() => onAlign('center'))} />
            <MenuItem icon={<IconAlignRight className="size-4" />} label="Right" onSelect={run(() => onAlign('right'))} />
            <MenuItem icon={<IconAlignTop className="size-4" />} label="Top" onSelect={run(() => onAlign('top'))} />
            <MenuItem icon={<IconAlignMiddleV className="size-4" />} label="Middle" onSelect={run(() => onAlign('middle'))} />
            <MenuItem icon={<IconAlignBottom className="size-4" />} label="Bottom" onSelect={run(() => onAlign('bottom'))} />
          </SubmenuItem>

          <Separator />

          <MenuItem
            icon={<IconLock className="size-4" />}
            label="Lock"
            shortcut="Alt+Shift+L"
            onSelect={run(onToggleLock)}
            onHover={closeSub}
          />
        </>
      )}
    </div>
  )
}

function Separator() {
  return <div className="mx-3 my-1 h-px bg-line" />
}

function MenuItem({
  icon,
  label,
  shortcut,
  disabled,
  onSelect,
  onHover,
}: {
  icon?: React.ReactNode
  label: string
  shortcut?: string
  disabled?: boolean
  onSelect: () => void
  /** Lets a plain row close any open submenu as the pointer travels the
   *  list — otherwise a submenu opened above would linger over the rows. */
  onHover?: () => void
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onSelect}
      onMouseEnter={onHover}
      className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[13px] text-ink transition hover:bg-hover disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
    >
      {icon && <span className="shrink-0 text-muted">{icon}</span>}
      <span className="flex-1 truncate">{label}</span>
      {shortcut && (
        <kbd className="rounded bg-hover px-1.5 py-0.5 font-sans text-[10px] font-medium text-muted">
          {shortcut}
        </kbd>
      )}
    </button>
  )
}

function SubmenuItem({
  icon,
  label,
  open,
  onOpen,
  flip,
  children,
}: {
  icon: React.ReactNode
  label: string
  open: boolean
  onOpen: () => void
  /** Open leftward when the parent menu sits too close to the right edge for
   *  the submenu to fit beside it. */
  flip: boolean
  children: React.ReactNode
}) {
  return (
    <div className="relative" onMouseEnter={onOpen}>
      <button
        type="button"
        role="menuitem"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={onOpen}
        className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[13px] text-ink transition hover:bg-hover ${
          open ? 'bg-hover' : ''
        }`}
      >
        <span className="shrink-0 text-muted">{icon}</span>
        <span className="flex-1 truncate">{label}</span>
        <IconChevronRight className="size-3.5 text-muted" />
      </button>
      {open && (
        <div
          role="menu"
          className={`absolute top-0 z-10 rounded-panel border border-line bg-surface py-1.5 shadow-pop ${
            flip ? 'right-full mr-1' : 'left-full ml-1'
          }`}
          style={{ width: SUBMENU_WIDTH }}
        >
          {children}
        </div>
      )}
    </div>
  )
}
