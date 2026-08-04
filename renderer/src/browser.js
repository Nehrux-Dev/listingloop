/**
 * A single warm Chromium, with a small pool of reusable pages.
 *
 * The prototype measured ~430 ms to launch a browser versus ~280 ms to render
 * an image, so launching per request would more than double the cost of every
 * export. One browser, kept alive, with pages checked out per render.
 *
 * Pages are keyed by viewport because changing a page's viewport forces a
 * relayout; four social dimensions means at most four resident pages.
 */

import { chromium } from 'playwright'

const MAX_PAGES_PER_VIEWPORT = Number(process.env.RENDERER_PAGES_PER_VIEWPORT ?? 2)

let browser = null
/** viewportKey -> { idle: Page[], waiters: ((page) => void)[], created: number } */
const pools = new Map()

export async function startBrowser() {
  if (browser) return browser
  browser = await chromium.launch({
    args: [
      // /dev/shm defaults to 64 MB in Docker; Chromium crashes rendering
      // large images without this.
      '--disable-dev-shm-usage',
      '--no-sandbox',
      '--font-render-hinting=none',
    ],
  })
  console.log('chromium launched')
  return browser
}

export async function stopBrowser() {
  for (const pool of pools.values()) {
    for (const page of pool.idle) await page.close().catch(() => {})
  }
  pools.clear()
  await browser?.close().catch(() => {})
  browser = null
}

function keyFor({ width, height, scale }) {
  return `${width}x${height}@${scale}`
}

async function createPage({ width, height, scale }, poolKey) {
  const context = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: scale,
    // Templates are static HTML with inlined assets. Disabling JavaScript
    // removes a whole class of risk from rendering user-influenced markup,
    // and costs nothing because nothing in a template needs it.
    javaScriptEnabled: false,
  })

  // Nothing should reach the network: every image is a data URI. Anything that
  // tries is a bug or an attempt to make the renderer fetch something.
  await context.route('**/*', (route) => {
    const url = route.request().url()
    if (url.startsWith('data:') || url.startsWith('about:')) {
      return route.continue()
    }
    console.warn('blocked outbound request from template:', url.slice(0, 120))
    return route.abort()
  })

  const page = await context.newPage()
  page.__context = context
  // Tagged so releasePage returns it to the pool it came from. Looking the
  // pool up by inspecting page lists is ambiguous once there is more than one
  // viewport in play.
  page.__poolKey = poolKey
  return page
}

function discardPage(page) {
  const pool = pools.get(page.__poolKey)
  if (pool) pool.created = Math.max(0, pool.created - 1)
  return page.__context?.close().catch(() => {})
}

export async function getPage(viewport) {
  if (!browser) await startBrowser()

  const key = keyFor(viewport)
  if (!pools.has(key)) pools.set(key, { idle: [], waiters: [], created: 0 })
  const pool = pools.get(key)

  const idle = pool.idle.pop()
  if (idle) return idle

  if (pool.created < MAX_PAGES_PER_VIEWPORT) {
    pool.created += 1
    try {
      return await createPage(viewport, key)
    } catch (error) {
      pool.created -= 1
      throw error
    }
  }

  // At capacity: queue until a page comes back. Bounded concurrency is
  // deliberate — Chromium's memory grows with the number of live pages, and
  // an unbounded pool is how a render service gets OOM-killed.
  return new Promise((resolve) => pool.waiters.push(resolve))
}

export async function releasePage(page) {
  const pool = pools.get(page.__poolKey)

  // Blank the page so a large previous render is not held in memory while the
  // page sits idle.
  try {
    await page.setContent('<!doctype html><html><body></body></html>')
  } catch {
    // The page died mid-render. Drop it; the pool will make a fresh one, and
    // anyone queued gets served by the next release rather than waiting on a
    // page that no longer exists.
    await discardPage(page)
    const waiter = pool?.waiters.shift()
    if (waiter && pool) {
      pool.created += 1
      waiter(await createPage(parseKey(page.__poolKey), page.__poolKey))
    }
    return
  }

  if (!pool) {
    await discardPage(page)
    return
  }

  const waiter = pool.waiters.shift()
  if (waiter) {
    waiter(page)
    return
  }
  pool.idle.push(page)
}

function parseKey(key) {
  const [size, scale] = key.split('@')
  const [width, height] = size.split('x').map(Number)
  return { width, height, scale: Number(scale) }
}
