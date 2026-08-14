/**
 * The editor's top bar: where you are, what state the document is in, and
 * the actions that apply to the whole design.
 *
 * Split out of TopToolbar, which previously carried two stacked rows — one
 * document-level, one contextual to the selection. Those are different
 * things: this one never changes as you click around, while the contextual
 * row changes constantly. Separating them is what lets the document actions
 * sit still while the selection controls move.
 *
 * Presentation only. Every handler here is the one that was already wired;
 * Rename, Duplicate and Delete moved into the overflow menu rather than
 * being removed.
 */

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  IconChevronRight,
  IconCheckCircle,
  IconEye,
  IconMinus,
  IconMore,
  IconPanel,
  IconPencil,
  IconPlus,
  IconRedo,
  IconUndo,
} from '../icons.tsx'

const MIN_ZOOM = 25
const MAX_ZOOM = 200

type SaveState = 'saved' | 'unsaved' | 'saving' | 'error'

type Props = {
  designName: string
  /** ISO timestamp of the last persisted change. */
  updatedAt: string

  canUndo: boolean
  canRedo: boolean
  onUndo: () => void
  onRedo: () => void

  zoom: number
  onZoomChange: (zoom: number) => void
  onFit: () => void

  onPreview: () => void
  onSave: () => void
  onExport: () => void
  saveState: SaveState
  saveError: string | null
  busy: boolean

  onRename: () => void
  onDuplicate: () => void
  onDelete: () => void

  /** The secondary surfaces. They used to be stacked under the canvas, where
   *  they competed with the design for the workspace; they are drawers now,
   *  and this menu is how you get at them. */
  variationsOpen: boolean
  onToggleVariations: () => void
  advancedOpen: boolean
  onToggleAdvanced: () => void
}

/** "2 minutes ago" — precise enough to reassure, vague enough to stay true
 *  between renders without a ticking timer. */
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.round(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

export default function EditorHeader({
  designName,
  updatedAt,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  zoom,
  onZoomChange,
  onFit,
  onPreview,
  onSave,
  onExport,
  saveState,
  saveError,
  busy,
  onRename,
  onDuplicate,
  onDelete,
  variationsOpen,
  onToggleVariations,
  advancedOpen,
  onToggleAdvanced,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [menuOpen])

  // Re-render on a slow tick so "2 minutes ago" does not sit at "just now"
  // for the length of an editing session.
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 30_000)
    return () => window.clearInterval(id)
  }, [])

  return (
    <header className="flex h-16 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
      {/* -- where you are --------------------------------------------- */}
      <Link
        to="/designs"
        title="Back to designs"
        className="flex size-9 shrink-0 items-center justify-center rounded-control border border-line text-muted transition hover:bg-hover hover:text-ink"
      >
        <IconPanel />
      </Link>

      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-1.5">
          <Link
            to="/designs"
            className="shrink-0 text-[13px] font-medium text-muted transition hover:text-ink"
          >
            Designs
          </Link>
          <IconChevronRight className="size-3.5 shrink-0 text-muted/60" />
          <span className="truncate text-[13px] font-semibold">{designName}</span>
          <button
            type="button"
            onClick={onRename}
            title="Rename design"
            aria-label="Rename design"
            className="flex size-6 shrink-0 items-center justify-center rounded text-muted transition hover:bg-hover hover:text-ink"
          >
            <IconPencil className="size-3.5" />
          </button>
        </div>
        <SavedLine saveState={saveState} saveError={saveError} updatedAt={updatedAt} />
      </div>

      {/* -- view controls, centred ------------------------------------ */}
      <div className="mx-auto flex items-center gap-1.5">
        <div className="flex items-center gap-0.5 rounded-control border border-line p-0.5">
          <HeaderIconButton onClick={onUndo} disabled={!canUndo} label="Undo">
            <IconUndo />
          </HeaderIconButton>
          <HeaderIconButton onClick={onRedo} disabled={!canRedo} label="Redo">
            <IconRedo />
          </HeaderIconButton>
        </div>

        <div className="flex items-center gap-0.5 rounded-control border border-line p-0.5">
          <HeaderIconButton
            onClick={() => onZoomChange(Math.max(MIN_ZOOM, zoom - 10))}
            disabled={zoom <= MIN_ZOOM}
            label="Zoom out"
          >
            <IconMinus />
          </HeaderIconButton>
          <span className="w-12 text-center text-[12px] font-semibold tabular-nums">{zoom}%</span>
          <HeaderIconButton
            onClick={() => onZoomChange(Math.min(MAX_ZOOM, zoom + 10))}
            disabled={zoom >= MAX_ZOOM}
            label="Zoom in"
          >
            <IconPlus />
          </HeaderIconButton>
          <span className="mx-0.5 h-5 w-px bg-line" />
          <button
            type="button"
            onClick={onFit}
            className="rounded px-2 py-1 text-[12px] font-medium text-muted transition hover:bg-hover hover:text-ink"
          >
            Fit
          </button>
          <button
            type="button"
            onClick={() => onZoomChange(100)}
            className="rounded px-2 py-1 text-[12px] font-medium text-muted transition hover:bg-hover hover:text-ink"
          >
            100%
          </button>
        </div>
      </div>

      {/* -- document actions ------------------------------------------ */}
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={onPreview}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-control border border-line px-3 py-2 text-[13px] font-medium transition hover:bg-hover disabled:opacity-50"
        >
          <IconEye className="size-4 text-muted" />
          Preview
        </button>

        <button
          type="button"
          onClick={onSave}
          disabled={busy || saveState === 'saving' || saveState === 'saved'}
          className="rounded-control border border-line px-3 py-2 text-[13px] font-medium transition hover:bg-hover disabled:opacity-60"
        >
          {saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? 'Saved' : 'Save'}
        </button>

        <button
          type="button"
          onClick={onExport}
          disabled={busy}
          className="rounded-control bg-brand px-4 py-2 text-[13px] font-semibold text-white shadow-panel transition hover:bg-brand-strong disabled:opacity-60"
        >
          Export
        </button>

        <div ref={menuRef} className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-label="More actions"
            title="More actions"
            className="flex size-9 items-center justify-center rounded-control border border-line text-muted transition hover:bg-hover hover:text-ink"
          >
            <IconMore />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full z-30 mt-1.5 w-56 overflow-hidden rounded-panel border border-line bg-surface py-1 shadow-pop">
              <MenuItem onClick={() => { setMenuOpen(false); onRename() }}>Rename…</MenuItem>
              <MenuItem onClick={() => { setMenuOpen(false); onDuplicate() }}>Duplicate</MenuItem>
              <div className="my-1 h-px bg-line" />
              <MenuItem checked={variationsOpen} onClick={() => { setMenuOpen(false); onToggleVariations() }}>
                Variations
              </MenuItem>
              <MenuItem checked={advancedOpen} onClick={() => { setMenuOpen(false); onToggleAdvanced() }}>
                Every element as a list
              </MenuItem>
              <div className="my-1 h-px bg-line" />
              <MenuItem danger onClick={() => { setMenuOpen(false); onDelete() }}>
                Delete design
              </MenuItem>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

/** The one line that tells you whether your work is safe. */
function SavedLine({
  saveState,
  saveError,
  updatedAt,
}: {
  saveState: SaveState
  saveError: string | null
  updatedAt: string
}) {
  if (saveState === 'error') {
    return (
      <p role="status" title={saveError ?? undefined} className="text-[11px] font-medium text-danger">
        Not saved — changes are still here
      </p>
    )
  }
  if (saveState === 'saving') {
    return (
      <p role="status" className="flex items-center gap-1.5 text-[11px] text-muted">
        <span className="size-1.5 animate-pulse rounded-full bg-muted" />
        Saving…
      </p>
    )
  }
  if (saveState === 'unsaved') {
    return (
      <p role="status" className="flex items-center gap-1.5 text-[11px] text-warning">
        <span className="size-1.5 rounded-full bg-warning" />
        Unsaved changes
      </p>
    )
  }
  return (
    <p role="status" className="flex items-center gap-1.5 text-[11px] text-muted">
      <IconCheckCircle className="size-3.5 text-success" />
      Last saved {relativeTime(updatedAt)}
    </p>
  )
}

function HeaderIconButton({
  onClick,
  disabled,
  label,
  children,
}: {
  onClick: () => void
  disabled?: boolean
  label: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="flex size-7 items-center justify-center rounded text-muted transition hover:bg-hover hover:text-ink disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  )
}

function MenuItem({
  onClick,
  danger,
  checked,
  children,
}: {
  onClick: () => void
  danger?: boolean
  /** Present on the entries that toggle a drawer, so the menu says whether
   *  the thing is currently showing rather than only how to show it. */
  checked?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      role={checked === undefined ? undefined : 'menuitemcheckbox'}
      aria-checked={checked}
      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] font-medium transition hover:bg-hover ${
        danger ? 'text-danger' : 'text-ink'
      }`}
    >
      {checked !== undefined && (
        <span className={`w-3 shrink-0 text-brand ${checked ? '' : 'opacity-0'}`}>✓</span>
      )}
      {children}
    </button>
  )
}
