/**
 * Load a public page in a real browser and return the rendered HTML.
 *
 * WHY THIS EXISTS
 * ---------------
 * Django's importer is a plain HTTP client. That is the right default — it is
 * fast and cheap — but a growing share of property sites ship an empty shell
 * and build the listing in JavaScript. To `requests` those pages look blank,
 * so an agent pastes a perfectly good link and gets an empty draft back.
 *
 * A real browser executes the page and sees what a person sees. That is all
 * this does. There is no attempt to disguise what we are: no stealth patches,
 * no fingerprint spoofing, no proxy rotation. A site that turns away honest
 * automation is entitled to, and we take the refusal.
 *
 * SECURITY
 * --------
 * This is the only part of the system that points a browser at a URL a user
 * chose, which makes it the sharpest SSRF edge in the codebase. Django screens
 * the URL first, but that alone is not enough: a page can redirect, and it can
 * pull subresources from anywhere. So every single request the browser makes —
 * the navigation, its redirects, and every asset — is resolved and checked
 * here, and aborted unless it lands on a public address.
 *
 * It also runs in a context of its own. The rendering pool has JavaScript
 * disabled and no network at all, which is exactly right for pasting arbitrary
 * template HTML into, and exactly wrong here — so the two never share.
 */

import dns from 'node:dns/promises'
import net from 'node:net'

import { chromium } from 'playwright'

const NAV_TIMEOUT_MS = 25_000
const SETTLE_MS = 2_500
const MAX_HTML_BYTES = 3 * 1024 * 1024

/** Resource types that cost time and tell us nothing about the listing data. */
const SKIPPED_RESOURCES = new Set(['image', 'media', 'font'])

function isPrivateIPv4(ip) {
  const [a, b] = ip.split('.').map(Number)
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 169 && b === 254) || // link-local, incl. cloud metadata
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 100 && b >= 64 && b <= 127) || // carrier-grade NAT
    a >= 224 // multicast and reserved
  )
}

function isPrivateIPv6(ip) {
  const value = ip.toLowerCase()
  if (value === '::' || value === '::1') return true
  // Unique-local and link-local.
  if (/^f[cd]/.test(value) || value.startsWith('fe80')) return true
  // ::ffff:10.0.0.1 and friends — an IPv4 private address in v6 clothing.
  const mapped = value.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/)
  if (mapped) return isPrivateIPv4(mapped[1])
  return false
}

function isPublicAddress(ip) {
  if (net.isIPv4(ip)) return !isPrivateIPv4(ip)
  if (net.isIPv6(ip)) return !isPrivateIPv6(ip)
  return false
}

/**
 * True when every address `hostname` resolves to is publicly routable.
 *
 * Every address, not just the first: a name that resolves to one public and
 * one loopback address is a classic way to slip past a check that stops at the
 * first answer.
 */
async function hostIsPublic(hostname) {
  if (net.isIP(hostname)) return isPublicAddress(hostname)
  try {
    const records = await dns.lookup(hostname, { all: true })
    return records.length > 0 && records.every((record) => isPublicAddress(record.address))
  } catch {
    return false
  }
}

async function requestIsAllowed(url) {
  let parsed
  try {
    parsed = new URL(url)
  } catch {
    return false
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false
  return hostIsPublic(parsed.hostname)
}

/**
 * Fetch `url` with a real browser.
 *
 * Returns { html, status, finalUrl }. Throws when the page cannot be loaded;
 * the caller decides what that means for the import.
 */
export async function fetchRendered(url) {
  if (!(await requestIsAllowed(url))) {
    throw new Error('That address is not publicly routable.')
  }

  // A dedicated browser, not the warm rendering one: this needs JavaScript and
  // a network, and the rendering pool must keep neither.
  const browser = await chromium.launch({ args: ['--no-sandbox'] })
  let context
  try {
    context = await browser.newContext({
      javaScriptEnabled: true,
      // No stored state, so nothing from one import can reach another.
      storageState: undefined,
    })
    context.setDefaultNavigationTimeout(NAV_TIMEOUT_MS)

    await context.route('**/*', async (route) => {
      const request = route.request()
      if (SKIPPED_RESOURCES.has(request.resourceType())) {
        await route.abort()
        return
      }
      if (await requestIsAllowed(request.url())) {
        await route.continue()
      } else {
        // Covers redirects into private space and any subresource that tries
        // to reach an internal service.
        await route.abort()
      }
    })

    const page = await context.newPage()
    const response = await page.goto(url, { waitUntil: 'domcontentloaded' })

    // Client-rendered pages populate shortly after DOMContentLoaded. A fixed
    // settle beats networkidle here: ad and analytics traffic on a listing page
    // often means networkidle never arrives.
    await page.waitForTimeout(SETTLE_MS)

    let html = await page.content()
    if (Buffer.byteLength(html) > MAX_HTML_BYTES) {
      html = html.slice(0, MAX_HTML_BYTES)
    }

    return {
      html,
      status: response ? response.status() : 0,
      finalUrl: page.url(),
    }
  } finally {
    if (context) await context.close()
    await browser.close()
  }
}
