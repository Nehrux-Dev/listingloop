/**
 * Orchestrates the comparison: runs each approach in its own process, then
 * diffs the two PNGs and writes a report.
 *
 *   node src/index.js [--iterations 10] [--scale 2] [--template listing-card]
 */

import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { comparePngs } from './lib/compare.js'
import { round } from './lib/measure.js'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..')

function parseArgs(argv) {
  const args = {}
  for (let i = 0; i < argv.length; i += 1) {
    if (!argv[i].startsWith('--')) continue
    const key = argv[i].slice(2)
    const next = argv[i + 1]
    args[key] = next && !next.startsWith('--') ? next : 'true'
  }
  return args
}

const args = parseArgs(process.argv.slice(2))
const iterations = Number(args.iterations ?? 10)
const scale = Number(args.scale ?? 2)
const templateName = args.template ?? 'listing-card'
const outDir = args.out ?? join(root, 'output')

const APPROACHES = ['playwright', 'satori']

function runApproach(approach) {
  return new Promise((resolve) => {
    const child = spawn(
      process.execPath,
      [
        join(here, 'run-one.js'),
        '--approach', approach,
        '--iterations', String(iterations),
        '--scale', String(scale),
        '--template', templateName,
        '--out', outDir,
      ],
      { stdio: ['ignore', 'inherit', 'inherit'] },
    )
    child.on('close', (code) => resolve(code))
  })
}

function mib(bytes) {
  return bytes === null || bytes === undefined ? null : round(bytes / 1024 / 1024, 1)
}

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return 'n/a'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${round(bytes / 1024)} KB`
  return `${round(bytes / 1024 / 1024)} MB`
}

function ms(value) {
  return value === null || value === undefined ? 'n/a' : `${value} ms`
}

function buildMarkdown(results, comparison) {
  const [a, b] = results
  const lines = []

  lines.push('# Rendering approach comparison')
  lines.push('')
  lines.push(`Template: \`${templateName}\` · ${a.output.logical_size.join('×')} logical, ` +
    `${a.output.pixel_size.join('×')} px at ${scale}× · ${iterations} warm iterations each.`)
  lines.push(`Node ${a.node_version}. Each approach ran in its own process.`)
  lines.push('')

  lines.push('## Speed')
  lines.push('')
  lines.push('| | A — Playwright | B — Satori + resvg |')
  lines.push('| --- | ---: | ---: |')
  lines.push(`| Cold start (engine init) | ${ms(a.timing.cold_start_ms)} | ${ms(b.timing.cold_start_ms)} |`)
  lines.push(`| First render | ${ms(a.timing.first_render_ms)} | ${ms(b.timing.first_render_ms)} |`)
  lines.push(`| **One image from cold** | **${ms(a.timing.cold_total_ms)}** | **${ms(b.timing.cold_total_ms)}** |`)
  lines.push(`| Warm median | ${ms(a.timing.warm.median_ms)} | ${ms(b.timing.warm.median_ms)} |`)
  lines.push(`| Warm p95 | ${ms(a.timing.warm.p95_ms)} | ${ms(b.timing.warm.p95_ms)} |`)
  lines.push(`| Warm min / max | ${ms(a.timing.warm.min_ms)} / ${ms(a.timing.warm.max_ms)} | ${ms(b.timing.warm.min_ms)} / ${ms(b.timing.warm.max_ms)} |`)
  lines.push('')

  if (b.stage_breakdown) {
    lines.push(`Satori stage split on the last render: layout to SVG ` +
      `${round(b.stage_breakdown.svg_ms)} ms, rasterise ${round(b.stage_breakdown.rasterise_ms)} ms ` +
      `(SVG was ${formatBytes(b.stage_breakdown.svg_bytes)}).`)
    lines.push('')
  }

  lines.push('## Memory')
  lines.push('')
  lines.push('| | A — Playwright | B — Satori + resvg |')
  lines.push('| --- | ---: | ---: |')
  lines.push(`| Node baseline RSS | ${formatBytes(a.memory.baseline_rss_bytes)} | ${formatBytes(b.memory.baseline_rss_bytes)} |`)
  lines.push(`| **Peak RSS (process tree)** | **${formatBytes(a.memory.peak_rss_bytes)}** | **${formatBytes(b.memory.peak_rss_bytes)}** |`)
  lines.push(`| Peak above baseline | ${formatBytes(a.memory.peak_over_baseline_bytes)} | ${formatBytes(b.memory.peak_over_baseline_bytes)} |`)
  lines.push('')
  lines.push(`_${a.memory.note}_`)
  lines.push('')

  lines.push('## Output')
  lines.push('')
  lines.push('| | A — Playwright | B — Satori + resvg |')
  lines.push('| --- | ---: | ---: |')
  lines.push(`| PNG size | ${formatBytes(a.output.bytes)} | ${formatBytes(b.output.bytes)} |`)
  lines.push(`| Pixel dimensions | ${a.output.pixel_size.join('×')} | ${b.output.pixel_size.join('×')} |`)
  lines.push('')

  lines.push('## Visual fidelity')
  lines.push('')
  if (!comparison.comparable) {
    lines.push(`The two outputs are not directly comparable: ${comparison.reason}`)
  } else {
    lines.push(`\`${comparison.differing_percent}%\` of pixels differ ` +
      `(${comparison.differing_pixels.toLocaleString()} of ${comparison.total_pixels.toLocaleString()}), ` +
      `at pixelmatch's default threshold with antialiasing differences ignored.`)
    lines.push('')
    lines.push('A percentage alone does not settle this — look at `diff.png`. ' +
      'Scattered edge noise means the two agree; solid blocks mean something ' +
      'moved or failed to render.')
  }
  lines.push('')
  lines.push('Files: `output/playwright.png`, `output/satori.png`, `output/diff.png`.')
  lines.push('')

  return lines.join('\n')
}

async function main() {
  mkdirSync(outDir, { recursive: true })

  console.log(`Template '${templateName}' at ${scale}x, ${iterations} warm iterations per approach.\n`)

  for (const approach of APPROACHES) {
    console.log(`--- running ${approach} ---`)
    const code = await runApproach(approach)
    if (code !== 0) {
      console.error(`\n${approach} failed (exit ${code}). See the error above.`)
      process.exitCode = 1
    }
  }

  const results = []
  for (const approach of APPROACHES) {
    const path = join(outDir, `${approach}.json`)
    if (!existsSync(path)) {
      console.error(`\nNo result for ${approach} — cannot produce a comparison.`)
      return
    }
    results.push(JSON.parse(readFileSync(path, 'utf8')))
  }

  const comparison = comparePngs(
    readFileSync(join(outDir, 'playwright.png')),
    readFileSync(join(outDir, 'satori.png')),
  )
  if (comparison.comparable) {
    writeFileSync(join(outDir, 'diff.png'), comparison.diff_png)
    delete comparison.diff_png
  }

  const report = {
    template: templateName,
    scale,
    iterations,
    generated_by: 'prototypes/render-comparison',
    results,
    comparison,
  }
  writeFileSync(join(outDir, 'report.json'), JSON.stringify(report, null, 2))

  const markdown = buildMarkdown(results, comparison)
  writeFileSync(join(outDir, 'report.md'), markdown)

  console.log(`\n${markdown}`)
  console.log(`Wrote ${outDir}/{playwright,satori,diff}.png, report.json, report.md`)
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
