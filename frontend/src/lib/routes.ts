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
