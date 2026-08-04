/**
 * Approach A — headless browser (Playwright + Chromium).
 *
 * The template HTML is loaded into a page sized to the template and
 * screenshotted. Whatever a browser can render, this can render: grid, custom
 * fonts, filters, SVG, transforms, web components, the lot.
 *
 * The costs are a browser process, its memory, and a cold start measured in
 * seconds rather than milliseconds — which is why `init()` is separate from
 * `render()`. In production the browser would be launched once and kept warm;
 * paying the launch cost per image would make this look far worse than it is.
 */

import { chromium } from 'playwright'

export const id = 'playwright'
export const label = 'A — Headless browser (Playwright/Chromium)'

export function createRenderer({ width, height, scale }) {
  let browser = null
  let context = null
  let page = null

  return {
    id,
    label,

    /** Cold start: launch Chromium and open a page. Done once. */
    async init() {
      browser = await chromium.launch({
        args: [
          // Standard container flags. --disable-dev-shm-usage matters: the
          // default /dev/shm in Docker is 64 MB and Chromium will crash
          // rendering large images without it.
          '--disable-dev-shm-usage',
          '--no-sandbox',
          '--font-render-hinting=none',
        ],
      })
      context = await browser.newContext({
        viewport: { width, height },
        deviceScaleFactor: scale,
      })
      page = await context.newPage()
    },

    async render(html) {
      // A full document wrapper: margin reset only. All the styling that
      // matters is inline in the template, so both engines see the same input.
      const document = `<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html, body { margin: 0; padding: 0; }
  body { width: ${width}px; height: ${height}px; overflow: hidden; }
</style>
</head><body>${html}</body></html>`

      // 'load' rather than 'networkidle': every asset is a data URI, so there
      // is no network to wait for and networkidle would just add ~500ms.
      await page.setContent(document, { waitUntil: 'load' })
      // Guarantees fonts are laid out before the screenshot; without it the
      // first render can capture a fallback face.
      await page.evaluate(() => document.fonts.ready)

      return page.screenshot({
        type: 'png',
        clip: { x: 0, y: 0, width, height },
      })
    },

    async dispose() {
      await context?.close()
      await browser?.close()
      browser = context = page = null
    },
  }
}
