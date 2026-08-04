/**
 * Approach B — structured rendering (Satori + resvg), no browser.
 *
 * Two stages, both in-process:
 *
 *   1. satori()  — lays out a constrained element tree and emits SVG. It is a
 *      layout engine, not a browser: flexbox and absolute positioning only.
 *   2. resvg     — rasterises that SVG to PNG (Rust, via native binding).
 *
 * They are timed separately below, because they have very different cost
 * curves: Satori scales with element count, resvg with output pixel area.
 *
 * The significant constraint is fonts. Satori has NO system-font fallback and
 * no @font-face support — every family used in the template must be handed in
 * as a buffer, or text silently disappears. That is a real operational
 * difference from the browser approach, not a detail.
 */

import { readFileSync } from 'node:fs'

import { Resvg } from '@resvg/resvg-js'
import satori from 'satori'
import { html as toVNode } from 'satori-html'

export const id = 'satori'
export const label = 'B — Structured render (Satori + resvg)'

/** Candidate font files, in preference order. */
const FONT_CANDIDATES = [
  {
    family: 'DejaVu Sans',
    weight: 400,
    paths: ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
  },
  {
    family: 'DejaVu Sans',
    weight: 700,
    paths: ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'],
  },
]

function loadFonts() {
  const fonts = []
  for (const candidate of FONT_CANDIDATES) {
    const path = candidate.paths.find((option) => {
      try {
        readFileSync(option)
        return true
      } catch {
        return false
      }
    })
    if (!path) {
      throw new Error(
        `Satori needs a font file for "${candidate.family}" ${candidate.weight}. ` +
          `Looked in: ${candidate.paths.join(', ')}. ` +
          `Install fonts-dejavu-core, or point FONT_CANDIDATES at your own file.`,
      )
    }
    fonts.push({
      name: candidate.family,
      weight: candidate.weight,
      style: 'normal',
      data: readFileSync(path),
    })
  }
  return fonts
}

export function createRenderer({ width, height, scale }) {
  let fonts = null
  /** Per-stage timings from the most recent render. */
  let lastBreakdown = null

  return {
    id,
    label,

    /** Cold start: read the font files. Milliseconds, not seconds. */
    async init() {
      fonts = loadFonts()
    },

    async render(html) {
      const svgStarted = performance.now()

      // satori-html turns the HTML string into the element tree Satori wants.
      // It reads inline `style` attributes only — no classes, no <style>.
      const tree = toVNode(html)

      const svg = await satori(tree, { width, height, fonts })
      const svgMs = performance.now() - svgStarted

      // Satori outlines every glyph to <path> (its `embedFont` default), so
      // the SVG carries no <text> and resvg needs no font configuration to
      // rasterise it correctly. Worth asserting rather than assuming: if a
      // future version emitted <text> instead, the words would silently
      // vanish from the PNG.
      if (svg.includes('<text')) {
        throw new Error(
          'Satori emitted <text> rather than outlined paths; resvg would need ' +
            'fonts configured to render it. Check satori\'s embedFont option.',
        )
      }

      const rasterStarted = performance.now()
      // NOTE: do not add a `font` option here. In @resvg/resvg-js 2.6.2,
      // passing `font` alongside `fitTo` causes `fitTo` to be ignored
      // entirely — the output silently comes back at 1x. Cost us a debugging
      // round; leaving the warning for the next person.
      const resvg = new Resvg(svg, {
        fitTo: { mode: 'width', value: width * scale },
      })
      const png = resvg.render().asPng()
      const rasterMs = performance.now() - rasterStarted

      lastBreakdown = {
        svg_ms: svgMs,
        rasterise_ms: rasterMs,
        svg_bytes: Buffer.byteLength(svg),
      }
      return png
    },

    getBreakdown() {
      return lastBreakdown
    },

    async dispose() {
      fonts = null
    },
  }
}
