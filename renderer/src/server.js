/**
 * Render service: HTML in, image out. Nothing else.
 *
 * Deliberately dumb. All template logic lives in Django; this process owns
 * exactly one thing — a warm Chromium — because the prototype showed that
 * launching a browser per image costs ~430 ms while reusing one costs nothing.
 *
 * Security posture: this endpoint renders arbitrary HTML, so it must never be
 * reachable from outside the compose network. Two guards:
 *   1. A shared token (RENDERER_TOKEN) that Django sends and this checks.
 *   2. The browser context is created with JavaScript disabled and no network
 *      access — every asset arrives inlined as a data URI, so a template can
 *      neither call out nor be used to probe internal services.
 */

import { createServer } from 'node:http'

import { getPage, releasePage, startBrowser, stopBrowser } from './browser.js'
import { fetchRendered } from './fetching.js'

const PORT = Number(process.env.PORT ?? 8080)
const TOKEN = process.env.RENDERER_TOKEN ?? ''
const MAX_BODY_BYTES = 24 * 1024 * 1024
const MAX_PIXELS = 30_000_000

function send(response, status, body, contentType = 'application/json') {
  const payload = contentType === 'application/json' ? JSON.stringify(body) : body
  response.writeHead(status, {
    'Content-Type': contentType,
    'Content-Length': Buffer.byteLength(payload),
  })
  response.end(payload)
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = []
    let total = 0
    request.on('data', (chunk) => {
      total += chunk.length
      if (total > MAX_BODY_BYTES) {
        reject(new Error('Request body too large'))
        request.destroy()
        return
      }
      chunks.push(chunk)
    })
    request.on('end', () => resolve(Buffer.concat(chunks)))
    request.on('error', reject)
  })
}

async function handleRender(request, response) {
  // Constant-ish token check. The service is network-isolated as well; this is
  // the second layer, not the only one.
  if (TOKEN && request.headers['x-renderer-token'] !== TOKEN) {
    send(response, 401, { detail: 'Invalid renderer token.' })
    return
  }

  let payload
  try {
    payload = JSON.parse((await readBody(request)).toString('utf8'))
  } catch (error) {
    send(response, 400, { detail: `Could not read request: ${error.message}` })
    return
  }

  const { html, width, height, format = 'png', quality = 90, scale = 1 } = payload

  if (typeof html !== 'string' || !html) {
    send(response, 400, { detail: 'html is required.' })
    return
  }
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    send(response, 400, { detail: 'width and height must be positive numbers.' })
    return
  }
  if (width * height * scale * scale > MAX_PIXELS) {
    send(response, 400, { detail: 'Requested image is too large.' })
    return
  }
  if (!['png', 'jpg', 'jpeg', 'pdf'].includes(format)) {
    send(response, 400, { detail: `Unsupported format '${format}'.` })
    return
  }

  const started = Date.now()
  let page
  try {
    page = await getPage({ width: Math.round(width), height: Math.round(height), scale })

    await page.setContent(html, { waitUntil: 'load' })
    await page.evaluate(() => document.fonts.ready)

    let buffer, contentType
    if (format === 'pdf') {
      // A genuinely different Chromium pipeline from screenshot() — it prints
      // the page rather than capturing pixels, and printing suppresses
      // backgrounds by default. Without printBackground:true every PDF export
      // would come back with the template's background stripped out: readable
      // as "it worked" (200, a PDF, the right page size) while actually
      // producing a broken file, so this is the one line in this branch that
      // is easy to remove by accident and hardest to notice was missing.
      buffer = await page.pdf({
        width: `${Math.round(width)}px`,
        height: `${Math.round(height)}px`,
        printBackground: true,
        margin: { top: 0, right: 0, bottom: 0, left: 0 },
        pageRanges: '1',
      })
      contentType = 'application/pdf'
    } else {
      buffer = await page.screenshot({
        type: format === 'png' ? 'png' : 'jpeg',
        ...(format === 'png' ? {} : { quality: Math.min(100, Math.max(1, quality)) }),
        clip: { x: 0, y: 0, width: Math.round(width), height: Math.round(height) },
      })
      contentType = format === 'png' ? 'image/png' : 'image/jpeg'
    }

    response.writeHead(200, {
      'Content-Type': contentType,
      'Content-Length': buffer.length,
      'X-Render-Ms': String(Date.now() - started),
    })
    response.end(buffer)
  } catch (error) {
    console.error('render failed:', error)
    send(response, 500, { detail: `Render failed: ${error.message}` })
  } finally {
    if (page) await releasePage(page)
  }
}

/**
 * POST /fetch — load a public page in a browser, return its rendered HTML.
 *
 * Separate from /render on purpose. /render takes HTML and must never touch
 * the network; this takes a URL and must. Keeping them apart keeps that
 * distinction enforceable rather than a comment.
 */
async function handleFetch(request, response) {
  if (TOKEN && request.headers['x-renderer-token'] !== TOKEN) {
    send(response, 401, { detail: 'Invalid renderer token.' })
    return
  }

  let payload
  try {
    payload = JSON.parse((await readBody(request)).toString('utf8'))
  } catch (error) {
    send(response, 400, { detail: `Could not read request: ${error.message}` })
    return
  }

  const { url } = payload
  if (typeof url !== 'string' || !url) {
    send(response, 400, { detail: 'url is required.' })
    return
  }

  const started = Date.now()
  try {
    const result = await fetchRendered(url)
    send(response, 200, { ...result, fetch_ms: Date.now() - started })
  } catch (error) {
    console.error('fetch failed:', error.message)
    send(response, 502, { detail: `Could not load the page: ${error.message}` })
  }
}

const server = createServer((request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    send(response, 200, { status: 'ok' })
    return
  }
  if (request.method === 'POST' && request.url === '/render') {
    void handleRender(request, response)
    return
  }
  if (request.method === 'POST' && request.url === '/fetch') {
    void handleFetch(request, response)
    return
  }
  send(response, 404, { detail: 'Not found.' })
})

async function main() {
  await startBrowser()
  server.listen(PORT, '0.0.0.0', () => {
    console.log(`renderer listening on :${PORT}`)
  })
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    server.close()
    void stopBrowser().then(() => process.exit(0))
  })
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
