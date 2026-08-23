/**
 * The editor's element/style clipboard.
 *
 * Module-level rather than component state so a copy survives closing one
 * design and opening another within the session — the same reach Canva's
 * element clipboard has. Deliberately NOT the OS clipboard: an element is a
 * JSON document whose image content can be a multi-megabyte data URI, and
 * writing that to `navigator.clipboard` would both stomp whatever text the
 * user actually copied and require a permission prompt for no gain.
 *
 * Nothing here is reactive. The menu and the shortcut handler read it at the
 * moment they act, which is the only moment its value matters.
 */

import type { ElementType, Transform } from '../../api/templates.ts'

export type CopiedElement = {
  /** Where the copy came from, so a paste can tell whether the element's
   *  template pointer (`source_key`) still means anything. */
  designId: number
  templateId: number
  type: ElementType
  name: string
  transform: Transform
  style: Record<string, unknown>
  content: string
  sourceKey: string | null
}

export type CopiedStyle = {
  sourceType: ElementType
  style: Record<string, unknown>
}

let copiedElement: CopiedElement | null = null
let copiedStyle: CopiedStyle | null = null
/** Pastes since the last copy. Each paste lands one nudge further down-right
 *  so repeated Ctrl+V doesn't stack copies invisibly on top of each other. */
let pasteCount = 0

export function setCopiedElement(entry: CopiedElement): void {
  copiedElement = entry
  pasteCount = 0
}

export function getCopiedElement(): CopiedElement | null {
  return copiedElement
}

export function nextPasteStep(): number {
  pasteCount += 1
  return pasteCount
}

export function setCopiedStyle(entry: CopiedStyle): void {
  copiedStyle = entry
}

export function getCopiedStyle(): CopiedStyle | null {
  return copiedStyle
}
