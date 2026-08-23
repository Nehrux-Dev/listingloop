/**
 * The font roles the editor can draw and offer — one list, shared by the
 * canvas (ElementLayer) and the font picker (PropertiesSidebar), mirroring
 * `html_builder.FONT_STACKS` family for family.
 *
 * A role, never a family name, is what an element stores (`font_family:
 * "elegant"`), and these stacks are the only place family names appear on the
 * frontend — same contract as the backend. Every family named here is
 * installed in the renderer image (renderer/Dockerfile) and vendored as a
 * woff2 in public/fonts + canvas-fonts.css, so the canvas, the export and
 * the picker's previews are all shaped by the same glyphs. Add a role in one
 * of those places and not the others and the preview starts lying — that is
 * the failure canvas-fonts.css documents.
 */

/** Matches html_builder.SAFE_FONT_STACK. */
export const SAFE_FONT_STACK =
  "'DejaVu Sans', 'Liberation Sans', 'Noto Sans', 'Helvetica Neue', Arial, sans-serif"

/** Mirrors `html_builder.FONT_STACKS` — same roles, same families, same
 *  fallback order. */
export const FONT_STACKS: Record<string, string> = {
  body: SAFE_FONT_STACK,
  display: `'Roboto Condensed', 'Liberation Sans Narrow', 'DejaVu Sans Condensed', ${SAFE_FONT_STACK}`,
  serif: "'Liberation Serif', 'DejaVu Serif', Georgia, serif",
  mono: "'Liberation Mono', 'DejaVu Sans Mono', monospace",
  // Calligraphic headlines. The renderer installs Dancing Script; a browser
  // previewing the canvas may not have it and will fall back to its own
  // cursive, so the canvas can look slightly different here from the export.
  script: "'Dancing Script', 'Kaushan Script', 'Lobster Two', cursive",
  // The authoring palette — see html_builder.FONT_STACKS for the reasoning.
  elegant: "'EB Garamond', 'Liberation Serif', Georgia, serif",
  modern: `'Lato', ${SAFE_FONT_STACK}`,
  rounded: `'Quicksand', 'Trebuchet MS', ${SAFE_FONT_STACK}`,
  slab: "'Roboto Slab', 'Liberation Serif', Georgia, serif",
  retro: "'Lobster Two', 'Dancing Script', cursive",
  soft: `'Comfortaa', 'Quicksand', ${SAFE_FONT_STACK}`,
}

/** What the picker shows for each role: a human name and the lead family, in
 *  a stable, deliberate order (workhorses first, decorative last). */
export const FONT_OPTIONS: { role: string; label: string; family: string }[] = [
  { role: 'body', label: 'Body', family: 'DejaVu Sans' },
  { role: 'modern', label: 'Modern', family: 'Lato' },
  { role: 'display', label: 'Display', family: 'Roboto Condensed' },
  { role: 'serif', label: 'Serif', family: 'Liberation Serif' },
  { role: 'elegant', label: 'Elegant', family: 'EB Garamond' },
  { role: 'slab', label: 'Slab', family: 'Roboto Slab' },
  { role: 'rounded', label: 'Rounded', family: 'Quicksand' },
  { role: 'soft', label: 'Soft', family: 'Comfortaa' },
  { role: 'script', label: 'Script', family: 'Dancing Script' },
  { role: 'retro', label: 'Retro', family: 'Lobster Two' },
  { role: 'mono', label: 'Mono', family: 'Liberation Mono' },
]
