/**
 * The stacking order of everything in the design, top layer first.
 *
 * ORDERING, STATED ONCE
 * ---------------------------------------------------------------------------
 * The canvas paints back to front: the lowest `z_index` is drawn first and
 * sits furthest away. This list is the inverse — index 0 of what you see is
 * the TOP of the stack — because that is how every layers panel reads, and
 * because "move this up" should move a row up. `elements` arrives in paint
 * order and is reversed here, in one place.
 *
 * WHAT EVERY ROW CAN DO
 * ---------------------------------------------------------------------------
 * Select, rename (double-click), hide, lock, reorder by drag, duplicate,
 * delete. Every one of those is available on every element, including ones
 * copied from a template — there is no tier that withholds them any more.
 *
 * A locked row is the one exception, and it withholds exactly one thing:
 * dragging to reorder. That is not policy, it is what the lock is for — you
 * locked it so you would stop moving it by accident. The lock toggle sits on
 * the same row, so undoing it is one click, and it is the same `locked`
 * boolean the canvas reads.
 *
 * Duplicate and delete are deliberately the SAME callbacks the canvas context
 * menu uses. Two entry points to one behaviour; the alternative is two code
 * paths that drift until "delete" means something subtly different depending
 * on where you clicked it.
 */

import { useEffect, useRef, useState } from 'react'

import type { DesignElement } from '../../api/templates.ts'
import {
  IconCopy,
  IconEye,
  IconEyeOff,
  IconLock,
  IconTrash,
  IconUnlock,
} from '../icons.tsx'
import { elementKind, isAgentOwned } from './elementKind.ts'

const KIND_ICON: Record<string, string> = {
  text: 'T',
  image: '▣',
  shape: '◆',
  background: '▦',
}

type Props = {
  /** In paint order (lowest z first) — reversed here, see the module note. */
  elements: DesignElement[]
  selectedId: string | null
  onSelect: (id: string) => void
  onRename: (id: string, name: string) => void
  onToggleVisible: (id: string) => void
  onToggleLocked: (id: string) => void
  /** The dragged element and the row it was dropped onto. */
  onReorder: (movedId: string, targetId: string) => void
  onDuplicate: (id: string) => void
  onDelete: (id: string) => void
}

export default function LayersPanel({
  elements,
  selectedId,
  onSelect,
  onRename,
  onToggleVisible,
  onToggleLocked,
  onReorder,
  onDuplicate,
  onDelete,
}: Props) {
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dropTargetId, setDropTargetId] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)

  const topFirst = [...elements].reverse()

  return (
    <div className="space-y-2">
      <p className="text-[11px] leading-relaxed text-muted">
        Top layer first. Drag to reorder, double-click to rename.
      </p>

      <ul className="space-y-1">
        {topFirst.map((element) => {
          const selected = element.id === selectedId
          const isDropTarget = dropTargetId === element.id && draggingId !== element.id

          return (
            <li key={element.id}>
              <div
                // A locked layer refuses the drag: you locked it to stop
                // moving it. The padlock beside it undoes that in one click.
                draggable={!element.locked && renamingId !== element.id}
                onDragStart={() => setDraggingId(element.id)}
                onDragEnd={() => {
                  setDraggingId(null)
                  setDropTargetId(null)
                }}
                onDragOver={(event) => {
                  if (!draggingId || element.locked) return
                  event.preventDefault()
                  setDropTargetId(element.id)
                }}
                onDrop={(event) => {
                  event.preventDefault()
                  if (draggingId && !element.locked && draggingId !== element.id) {
                    onReorder(draggingId, element.id)
                  }
                  setDraggingId(null)
                  setDropTargetId(null)
                }}
                onClick={() => onSelect(element.id)}
                onDoubleClick={() => setRenamingId(element.id)}
                className={`group flex w-full items-center gap-1.5 rounded-control border px-2 py-1.5 text-left text-xs transition ${
                  selected
                    ? 'border-brand/40 bg-active'
                    : 'border-transparent hover:border-line hover:bg-hover'
                } ${isDropTarget ? 'ring-2 ring-brand/50' : ''} ${
                  draggingId === element.id ? 'opacity-40' : ''
                } ${element.locked ? 'cursor-pointer' : 'cursor-grab'}`}
              >
                <span
                  aria-hidden="true"
                  className={`w-3 shrink-0 text-center ${
                    element.locked ? 'text-muted/40' : 'text-muted'
                  }`}
                >
                  ☰
                </span>

                <span className="flex size-4 shrink-0 items-center justify-center rounded bg-beige text-[9px] font-bold text-brand">
                  {KIND_ICON[elementKind(element)] ?? '◆'}
                </span>

                {renamingId === element.id ? (
                  <RenameField
                    initial={element.name}
                    onCommit={(name) => {
                      setRenamingId(null)
                      if (name && name !== element.name) onRename(element.id, name)
                    }}
                    onCancel={() => setRenamingId(null)}
                  />
                ) : (
                  <span
                    className={`min-w-0 flex-1 truncate ${
                      element.visible ? 'text-ink' : 'text-muted line-through'
                    }`}
                  >
                    {element.name}
                    {isAgentOwned(element) && <span className="text-muted"> · added</span>}
                  </span>
                )}

                <RowAction
                  label={element.visible ? 'Hide this layer' : 'Show this layer'}
                  onClick={() => onToggleVisible(element.id)}
                  // A hidden or locked layer keeps its icon on show: those are
                  // states you need to see without hovering every row to find
                  // which one you turned off.
                  alwaysVisible={!element.visible}
                >
                  {element.visible ? (
                    <IconEye className="size-3.5" />
                  ) : (
                    <IconEyeOff className="size-3.5" />
                  )}
                </RowAction>

                <RowAction
                  label={element.locked ? 'Unlock this layer' : 'Lock this layer'}
                  onClick={() => onToggleLocked(element.id)}
                  alwaysVisible={element.locked}
                >
                  {element.locked ? (
                    <IconLock className="size-3.5" />
                  ) : (
                    <IconUnlock className="size-3.5" />
                  )}
                </RowAction>

                <RowAction label="Duplicate" onClick={() => onDuplicate(element.id)}>
                  <IconCopy className="size-3.5" />
                </RowAction>

                <RowAction label="Delete" danger onClick={() => onDelete(element.id)}>
                  <IconTrash className="size-3.5" />
                </RowAction>
              </div>
            </li>
          )
        })}
      </ul>

      {elements.length === 0 && (
        <p className="rounded-control border border-dashed border-line px-3 py-6 text-center text-[11px] text-muted">
          This canvas is empty. Add something from the Elements tab, or reset
          the design to start again from the template.
        </p>
      )}
    </div>
  )
}

function RowAction({
  label,
  onClick,
  children,
  danger,
  alwaysVisible,
}: {
  label: string
  onClick: () => void
  children: React.ReactNode
  danger?: boolean
  alwaysVisible?: boolean
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation()
        onClick()
      }}
      className={`shrink-0 rounded p-0.5 transition focus-visible:opacity-100 group-hover:opacity-100 ${
        alwaysVisible ? 'opacity-100' : 'opacity-0'
      } ${danger ? 'text-muted hover:text-danger' : 'text-muted hover:text-ink'}`}
    >
      {children}
    </button>
  )
}

/** Inline rename. Enter commits, Escape and blur-after-Escape cancel. */
function RenameField({
  initial,
  onCommit,
  onCancel,
}: {
  initial: string
  onCommit: (name: string) => void
  onCancel: () => void
}) {
  const ref = useRef<HTMLInputElement>(null)
  const cancelled = useRef(false)

  useEffect(() => {
    ref.current?.focus()
    ref.current?.select()
  }, [])

  return (
    <input
      ref={ref}
      defaultValue={initial}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault()
          onCommit(ref.current?.value.trim() ?? '')
        }
        if (event.key === 'Escape') {
          event.preventDefault()
          cancelled.current = true
          ref.current?.blur()
        }
      }}
      onBlur={() => {
        if (cancelled.current) onCancel()
        else onCommit(ref.current?.value.trim() ?? '')
      }}
      className="min-w-0 flex-1 rounded border border-brand/50 bg-surface px-1 py-0.5 text-xs text-ink outline-none"
    />
  )
}
