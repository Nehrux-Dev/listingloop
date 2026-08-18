/**
 * Relative timestamps, in the one phrasing the product uses.
 *
 * Shared rather than copied because two screens date the same field — the
 * designs panel and the resume prompt in the template dialog — and "3 days
 * ago" on one next to "3d" on the other reads as two different systems.
 */

/** "3 days ago". Empty string for anything that is not a parseable date. */
export function lastEdited(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60_000))
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  return new Date(then).toLocaleDateString()
}
