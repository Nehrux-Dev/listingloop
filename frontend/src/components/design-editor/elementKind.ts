/**
 * Which family of controls an element gets.
 *
 * The document's eight `type`s are finer-grained than the *panels* need — a
 * button is styled like a shape and typed like text, a logo behaves exactly
 * like an image — so this collapses them to the four shapes the panels branch
 * on. Kept in one place so the toolbar, the layers panel and the properties
 * panel can never disagree about what is selected.
 *
 * Note what is NOT here any more: `canMove`. Position and size used to be
 * FREE-tier only, so every surface had to ask permission before offering a
 * drag handle. There is no tier now — `element.locked` is the only thing that
 * restricts anything, and it is read directly.
 */

import type { DesignElement, ElementType } from '../../api/templates.ts'

/** The panel family an element belongs to. */
export type ElementKind = 'text' | 'image' | 'shape' | 'background'

const KIND_BY_TYPE: Record<ElementType, ElementKind> = {
  text: 'text',
  // A button is a shape with a label inside it, so it needs both families.
  // It is filed under text because that is the control set you reach for
  // first when you select one; ButtonPanel adds the shape controls back.
  button: 'text',
  image: 'image',
  logo: 'image',
  icon: 'image',
  shape: 'shape',
  line: 'shape',
  background: 'background',
}

export function elementKind(element: Pick<DesignElement, 'type'>): ElementKind {
  return KIND_BY_TYPE[element.type] ?? 'shape'
}

/**
 * True for an element the agent added, as opposed to one copied from the
 * template. The distinction is not about what may be edited — everything may
 * — but about whether "reset to template" has anything to reset to.
 */
export function isAgentOwned(element: Pick<DesignElement, 'original_element_id'>): boolean {
  return element.original_element_id === null
}

/** True for an element that came from the template and can be reset to it. */
export function canReset(element: Pick<DesignElement, 'original_element_id'>): boolean {
  return element.original_element_id !== null
}

/**
 * Whether this element may be manipulated on the canvas right now.
 *
 * The whole rule, in one line. It used to consult a four-tier permission the
 * template set; it now consults a boolean the user set and can unset in one
 * click from the layers panel.
 */
export function isInteractive(element: Pick<DesignElement, 'locked' | 'visible'>): boolean {
  return !element.locked && element.visible
}
