/**
 * The small pill of actions floating above the selected element — the piece
 * of Canva's selection UI that earns its place on the canvas. Everything
 * style-shaped moved to the docked TopToolbar; what remains here is the
 * handful of whole-element verbs you want at the pointer: lock, duplicate,
 * delete, and the door to the full properties panel.
 *
 * Deliberately tiny. The old floating toolbar was a full control strip that
 * buried neighbouring elements; this pill is four icons, so there is nothing
 * it can meaningfully cover. It rides the same unscaled floating slot in
 * Canvas that the old toolbar used.
 *
 * A locked element shows only the unlock button: locked means "resists
 * everything else", and offering delete on it would contradict the state the
 * user chose. Same rule the context menu follows.
 */

import { IconCopy, IconLock, IconSliders, IconTrash, IconUnlock } from '../icons.tsx'

type Props = {
  locked: boolean
  onToggleLock: () => void
  onDuplicate: () => void
  onDelete: () => void
  /** Opens/closes the full properties panel (PropertiesSidebar). */
  onMore: () => void
}

export default function QuickActions({
  locked,
  onToggleLock,
  onDuplicate,
  onDelete,
  onMore,
}: Props) {
  return (
    <div className="flex items-center gap-0.5 rounded-panel border border-line bg-surface px-1 py-1 shadow-pop">
      <PillButton
        label={locked ? 'Unlock (Alt+Shift+L)' : 'Lock (Alt+Shift+L)'}
        onClick={onToggleLock}
      >
        {locked ? <IconUnlock className="size-4" /> : <IconLock className="size-4" />}
      </PillButton>
      {!locked && (
        <>
          <PillButton label="Duplicate (Ctrl+D)" onClick={onDuplicate}>
            <IconCopy className="size-4" />
          </PillButton>
          <PillButton label="Delete (DELETE)" onClick={onDelete} danger>
            <IconTrash className="size-4" />
          </PillButton>
          <span className="mx-0.5 h-4 w-px bg-line" />
          <PillButton label="Position and all properties" onClick={onMore}>
            <IconSliders className="size-4" />
          </PillButton>
        </>
      )}
    </div>
  )
}

function PillButton({
  label,
  onClick,
  danger,
  children,
}: {
  label: string
  onClick: () => void
  danger?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={`flex size-7 items-center justify-center rounded-control text-muted transition hover:bg-hover ${
        danger ? 'hover:text-danger' : 'hover:text-ink'
      }`}
    >
      {children}
    </button>
  )
}
