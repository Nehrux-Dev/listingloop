/**
 * Timing and memory measurement.
 *
 * Memory is the awkward one. Satori runs in-process, so `process.memoryUsage()`
 * would cover it — but Playwright's Chromium is a *separate process tree*, and
 * ignoring that would flatter it enormously. So both approaches are measured
 * the same way: peak resident set size of this process plus every descendant,
 * sampled on an interval, read from /proc.
 *
 * That is Linux-only, which is why the prototype runs in a container. On any
 * other platform the memory numbers are reported as null rather than as a
 * plausible-looking wrong answer.
 */

import { readFileSync, readdirSync } from 'node:fs'

const SUPPORTS_PROC = process.platform === 'linux'

function readRssBytes(pid) {
  try {
    const status = readFileSync(`/proc/${pid}/status`, 'utf8')
    const match = status.match(/^VmRSS:\s+(\d+)\s+kB$/m)
    return match ? Number(match[1]) * 1024 : 0
  } catch {
    // The process exited between listing and reading it.
    return 0
  }
}

function readParentPid(pid) {
  try {
    const stat = readFileSync(`/proc/${pid}/stat`, 'utf8')
    // The comm field can contain spaces and parentheses, so index from the
    // last ')' rather than splitting the whole line.
    const after = stat.slice(stat.lastIndexOf(')') + 2).split(' ')
    return Number(after[1])
  } catch {
    return 0
  }
}

/** Sum RSS across `rootPid` and everything descended from it. */
export function processTreeRss(rootPid) {
  if (!SUPPORTS_PROC) return null

  const pids = readdirSync('/proc').filter((entry) => /^\d+$/.test(entry)).map(Number)

  const children = new Map()
  for (const pid of pids) {
    const parent = readParentPid(pid)
    if (!children.has(parent)) children.set(parent, [])
    children.get(parent).push(pid)
  }

  let total = 0
  const stack = [rootPid]
  const seen = new Set()
  while (stack.length > 0) {
    const pid = stack.pop()
    if (seen.has(pid)) continue
    seen.add(pid)
    total += readRssBytes(pid)
    stack.push(...(children.get(pid) ?? []))
  }
  return total
}

/** Samples peak process-tree RSS in the background. */
export class PeakMemorySampler {
  constructor(intervalMs = 40) {
    this.intervalMs = intervalMs
    this.peak = 0
    this.timer = null
  }

  start() {
    if (!SUPPORTS_PROC) return this
    this.peak = processTreeRss(process.pid) ?? 0
    this.timer = setInterval(() => {
      const current = processTreeRss(process.pid) ?? 0
      if (current > this.peak) this.peak = current
    }, this.intervalMs)
    // Do not hold the event loop open.
    this.timer.unref?.()
    return this
  }

  stop() {
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    return SUPPORTS_PROC ? this.peak : null
  }
}

export function percentile(sortedValues, p) {
  if (sortedValues.length === 0) return null
  const index = Math.min(
    sortedValues.length - 1,
    Math.ceil((p / 100) * sortedValues.length) - 1,
  )
  return sortedValues[Math.max(0, index)]
}

export function summarise(samples) {
  const sorted = [...samples].sort((a, b) => a - b)
  const sum = sorted.reduce((total, value) => total + value, 0)
  return {
    runs: sorted.length,
    min_ms: round(sorted[0]),
    median_ms: round(percentile(sorted, 50)),
    p95_ms: round(percentile(sorted, 95)),
    max_ms: round(sorted[sorted.length - 1]),
    mean_ms: round(sum / sorted.length),
  }
}

export function round(value, digits = 1) {
  if (value === null || value === undefined) return null
  const factor = 10 ** digits
  return Math.round(value * factor) / factor
}

export async function timed(fn) {
  const started = performance.now()
  const result = await fn()
  return { ms: performance.now() - started, result }
}
