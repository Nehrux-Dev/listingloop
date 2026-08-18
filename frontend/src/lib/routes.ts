/**
 * The handful of paths that more than one screen needs to build.
 *
 * Here because the editor moved to its own route: browsing designs and
 * editing one are different screens now, and six call sites hardcoding
 * `/designs/${id}` is how they silently drift apart.
 */

/** The full-screen editor for one design. */
export function designEditorPath(id: number | string): string {
  return `/designs/${id}/edit`
}

/**
 * The two halves of the studio, and they are deliberately two.
 *
 * `TEMPLATES_HOME` is the catalogue of what you could start — product content,
 * the same for everybody. `DESIGNS_HOME` is your own work in progress. They
 * were briefly one screen; splitting them back means each can be what it is,
 * and neither has to be scrolled past to reach the other.
 */
export const TEMPLATES_HOME = '/templates'
export const DESIGNS_HOME = '/designs'

/**
 * Which dashboard belongs to whom, and where each one starts.
 *
 * There are three shells and only one of them is at "/". These two helpers are
 * what stop a user being sent somewhere that is not theirs — see
 * `landingPathFor` for the bug that made them necessary.
 */
const PLATFORM_AREA = /^\/platform(\/|$)/
const AGENCY_AREA = /^\/admin(\/|$)/

type Viewer = {
  role: string
  administers_brokerage?: boolean
}

/** The front door for this user's own dashboard. */
export function homePathFor(user: Viewer | null | undefined): string {
  if (user?.role === 'nehrux_admin') return '/platform'
  if (user?.role === 'brokerage_admin') return '/admin'
  return '/'
}

/** True when this user's role can open that path at all. */
export function canEnter(path: string, user: Viewer | null | undefined): boolean {
  if (!user) return false
  if (PLATFORM_AREA.test(path)) return user.role === 'nehrux_admin'
  if (AGENCY_AREA.test(path)) {
    return (
      user.role === 'nehrux_admin' ||
      user.role === 'brokerage_admin' ||
      Boolean(user.administers_brokerage)
    )
  }
  return true
}

/**
 * Where to send someone the moment they sign in.
 *
 * `intended` is the path a guard bounced them off before they had a session —
 * honouring it is what makes a bookmarked deep link work. But it survives a
 * *change of account*: visit /platform while signed out, sign in as an agent,
 * and the login page cheerfully returned them to /platform, where the role
 * guard threw them at /forbidden. An agent's first sight of the product was a
 * permission error about a dashboard they had never asked for.
 *
 * So an intended path is only honoured when this user could actually open it,
 * and otherwise they go to their own front door.
 */
export function landingPathFor(
  user: Viewer | null | undefined,
  intended?: string | null,
): string {
  if (intended && intended !== '/' && canEnter(intended, user)) return intended
  return homePathFor(user)
}

/**
 * The listings panel, told which design sent the agent there.
 *
 * The design id travels in the URL rather than in router state because this
 * trip is not one hop: the agent may go on to the import screen or the new
 * listing form and come back, and a query parameter survives that where
 * `navigate(..., { state })` does not.
 */
export function listingsForDesignPath(designId: number | string): string {
  return `/listings?${FOR_DESIGN_PARAM}=${designId}`
}

/** The query parameter carrying that design id. */
export const FOR_DESIGN_PARAM = 'for'

/** Reads the design id back out, ignoring anything that is not a number. */
export function designIdFromParams(params: URLSearchParams): number | null {
  const raw = params.get(FOR_DESIGN_PARAM)
  if (!raw) return null
  const id = Number(raw)
  return Number.isInteger(id) && id > 0 ? id : null
}

/**
 * Carry the "I am doing this for a design" context onto the next path.
 *
 * Used on every hop the listings side can take — import, new listing, the
 * listing being reviewed — because the agent who set out to fill in a design
 * is still doing that three screens later, and losing the thread halfway
 * strands them on a screen with no way back to what they were making.
 */
export function keepForDesign(path: string, params: URLSearchParams): string {
  const id = designIdFromParams(params)
  if (id === null) return path
  return `${path}${path.includes('?') ? '&' : '?'}${FOR_DESIGN_PARAM}=${id}`
}
