/**
 * "Do you want to customize this template?" — the step between browsing and
 * editing.
 *
 * WHY THIS EXISTS AT ALL
 * ---------------------------------------------------------------------------
 * Clicking a card used to create a design and throw the agent straight into
 * the editor. Two things were wrong with that. A card is a 200px tile, so the
 * first proper look at a template was the editor itself — and by then a design
 * already existed, which meant browsing five templates left five abandoned
 * designs behind. And there was no moment at which the agent could say "no,
 * not that one" without using the back button.
 *
 * So: a bigger look, a named decision, and nothing is created until the
 * decision is yes.
 *
 * ONE DESIGN PER TEMPLATE, UNLESS YOU ASK FOR TWO
 * ---------------------------------------------------------------------------
 * Every visit to a template used to POST a new design, so an agent who opened
 * "Just Listed" on Monday, Tuesday and Wednesday ended up with three
 * near-identical entries in their designs panel and no idea which one held
 * Wednesday's edits. Saving was never the duplicating step — the editor has
 * always PATCHed the design it is on. *Opening* was.
 *
 * The rule is enforced on the server, in `DesignSerializer.create`, because
 * this dialog is only one of four screens that open templates. The lookup
 * below is not what makes it true — it is what lets the dialog *say* so
 * before the agent clicks, which a redirect after the fact cannot.
 *
 * Making a second copy deliberately is still one click ("Start a fresh copy",
 * which sets `fresh`), because two flyers from one template for two different
 * properties is a real thing an agent does. The difference is that it is now a
 * choice rather than the only behaviour.
 *
 * OPENING IN A NEW TAB
 * ---------------------------------------------------------------------------
 * The window has to be opened in the click handler, not after `createDesign`
 * resolves — a browser only trusts `window.open` while it can still see the
 * user gesture that led to it, and an `await` in between is exactly what makes
 * it stop trusting it. So the tab is opened blank and pointed at the editor
 * once the design comes back, and closed again if it never does. The existing-
 * design lookup runs on mount for the same reason: by click time the answer
 * has to already be in hand.
 */

import { useEffect, useRef, useState } from 'react'

import {
  createDesign,
  fetchDesigns,
  type Design,
  type TemplateSummary,
} from '../api/templates.ts'
import { ApiError } from '../lib/apiClient.ts'
import { designEditorPath } from '../lib/routes.ts'
import { lastEdited } from '../lib/time.ts'
import { Alert } from './FormControls.tsx'
import TemplateThumb from './TemplateThumb.tsx'
import { IconExternal } from './icons.tsx'

/** Loading is a third state and has to be one: `null` means "looked, and there
 *  is none", which is a different button than "have not looked yet". */
type Existing = Design | null | 'loading'

export default function UseTemplateDialog({
  template,
  format,
  aspect,
  onClose,
  onOpen,
}: {
  template: TemplateSummary
  /** Human label for the template's format — "Instagram Post", not "ig_post". */
  format: string
  /** Width ÷ height, so the preview is the shape of the thing being chosen. */
  aspect: number
  onClose: () => void
  /** Same-tab route change. The dialog does not navigate itself: the gallery
   *  owns the router, and a new tab must not navigate the gallery at all. */
  onOpen: (designId: number) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [existing, setExisting] = useState<Existing>('loading')
  const confirmRef = useRef<HTMLButtonElement>(null)

  /**
   * Have I already started one of these?
   *
   * `mine=1` because the permission scope is wider than the question: a
   * brokerage admin can read their whole firm's designs, and offering to
   * "continue" a colleague's flyer would be a surprising answer to clicking a
   * template. Newest first, so resuming means resuming the one last worked on.
   *
   * A failed lookup falls back to the create path rather than blocking. The
   * cost of being wrong here is one extra design; the cost of blocking is an
   * agent who cannot start work because a list request failed.
   */
  useEffect(() => {
    let live = true
    fetchDesigns({ mine: '1', template: String(template.id) })
      .then((page) => {
        if (!live) return
        const newest = [...page.results].sort((a, b) =>
          b.updated_at.localeCompare(a.updated_at),
        )[0]
        setExisting(newest ?? null)
      })
      .catch(() => {
        if (live) setExisting(null)
      })
    return () => {
      live = false
    }
  }, [template.id])

  // Escape closes, and the primary action takes focus on open — this dialog
  // is one decision, so the keyboard should be able to make it immediately.
  useEffect(() => {
    confirmRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const resumable = existing !== 'loading' && existing !== null ? existing : null

  /**
   * @param newTab open the editor beside the gallery rather than replacing it
   * @param fresh  create a new design even though one already exists
   */
  async function start(newTab: boolean, fresh: boolean) {
    if (busy || existing === 'loading') return
    // Claimed before any await, while the click is still trusted. See above.
    const tab = newTab ? window.open('', '_blank', 'noopener') : null

    // Resuming creates nothing, so there is nothing to await and nothing that
    // can fail — this is the path that stops the designs panel filling up.
    if (resumable && !fresh) {
      if (tab) {
        tab.location.href = designEditorPath(resumable.id)
        onClose()
        return
      }
      onOpen(resumable.id)
      return
    }

    setBusy(true)
    setError(null)
    try {
      const design = await createDesign({
        name: `${template.name} — ${new Date().toLocaleDateString()}`,
        template: template.id,
        // No property. A template is opened as itself, and the listing is
        // attached later from inside the editor — so what an agent picked last
        // week stops silently deciding what every template they open this week
        // is about.
        listing: null,
        // Without this the server would resume the existing design and the
        // "Start a fresh copy" button would silently do nothing.
        fresh,
      })
      if (tab) {
        tab.location.href = designEditorPath(design.id)
        onClose()
        return
      }
      onOpen(design.id)
    } catch (err) {
      tab?.close()
      setError(err instanceof ApiError ? err.message : 'Could not start that design.')
      setBusy(false)
    }
  }

  const checking = existing === 'loading'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="use-template-title"
      onMouseDown={(event) => {
        // Backdrop only: a drag that starts inside the panel and ends outside
        // it should not count as a click away.
        if (event.target === event.currentTarget && !busy) onClose()
      }}
    >
      <div className="max-h-full w-full max-w-md overflow-y-auto rounded-panel border border-line bg-surface p-6 shadow-pop">
        <TemplateThumb
          template={template}
          className="w-full rounded-control p-4"
          style={{ aspectRatio: String(aspect) }}
        />

        <h2 id="use-template-title" className="mt-5 text-lg font-semibold tracking-tight">
          {resumable ? 'Carry on with this one?' : 'Customize this template?'}
        </h2>
        <p className="mt-1 text-sm text-muted">
          <span className="font-medium text-ink">{template.name}</span> · {format} ·{' '}
          {template.category_display}
        </p>

        {/* The whole point of the lookup, said out loud. An agent who does not
            know a design already exists cannot make a sensible choice between
            these two buttons. */}
        {resumable ? (
          <p className="mt-3 rounded-control border border-line bg-subtle px-3 py-2.5 text-sm text-muted">
            You already have{' '}
            <span className="font-medium text-ink">{resumable.name}</span> from this
            template, edited {lastEdited(resumable.updated_at)}. Opening it keeps
            everything you have done — saving updates that design rather than adding
            another.
          </p>
        ) : (
          <p className="mt-3 text-sm text-muted">
            You will get your own copy to edit. The template itself stays as it is,
            and you can add a property to it once you are in the editor.
          </p>
        )}

        {error && (
          <div className="mt-4">
            <Alert kind="error">{error}</Alert>
          </div>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-2">
          <button
            ref={confirmRef}
            type="button"
            onClick={() => void start(false, false)}
            disabled={busy || checking}
            className="rounded-control bg-brand px-4 py-2.5 text-sm font-semibold text-white shadow-panel transition hover:bg-brand-strong disabled:opacity-60"
          >
            {checking
              ? 'Checking…'
              : busy
                ? 'Opening…'
                : resumable
                  ? 'Continue editing'
                  : 'Customize this template'}
          </button>

          {/* Only offered once there is something to be a copy *of*. Before
              that the primary button already is "make me one". */}
          {resumable && (
            <button
              type="button"
              onClick={() => void start(false, true)}
              disabled={busy}
              title="Leave that design alone and start a second one from this template"
              className="rounded-control border border-line px-3 py-2.5 text-sm font-medium transition hover:bg-hover disabled:opacity-60"
            >
              Start a fresh copy
            </button>
          )}

          <button
            type="button"
            onClick={() => void start(true, false)}
            disabled={busy || checking}
            title={
              resumable
                ? 'Open that design in a new tab and keep browsing here'
                : 'Open the editor in a new tab and keep browsing here'
            }
            className="flex items-center gap-1.5 rounded-control border border-line px-3 py-2.5 text-sm font-medium transition hover:bg-hover disabled:opacity-60"
          >
            <IconExternal className="size-4 text-muted" />
            New tab
          </button>

          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="ml-auto rounded-control px-3 py-2.5 text-sm font-medium text-muted transition hover:bg-hover hover:text-ink disabled:opacity-60"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
