/**
 * Runs ONE approach and writes its PNG plus a JSON result.
 *
 * Deliberately a separate process per approach. Node does not return freed
 * heap to the OS promptly, so measuring both approaches in one process would
 * attribute whatever the first one allocated to the second. A fresh process
 * per approach is the only way to get a memory number worth reading.
 *
 * Not intended to be run by hand — src/index.js spawns it.
 */

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { buildAssets } from './lib/assets.js'
import { PeakMemorySampler, processTreeRss, round, summarise } from './lib/measure.js'
import { readFileSync } from 'node:fs'

const here = dirname(fileURLToPath(import.meta.url))

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
const approach = args.approach
const iterations = Number(args.iterations ?? 10)
const scale = Number(args.scale ?? 2)
const templateName = args.template ?? 'listing-card'
const outDir = args.out ?? join(here, '..', 'output')

const RENDERERS = {
  playwright: () => import('./render/playwright.js'),
  satori: () => import('./render/satori.js'),
}

async function main() {
  if (!RENDERERS[approach]) {
    throw new Error(`Unknown approach '${approach}'. Expected one of: ${Object.keys(RENDERERS).join(', ')}`)
  }

  mkdirSync(outDir, { recursive: true })

  const baselineRss = processTreeRss(process.pid)

  const template = await import(`./templates/${templateName}.js`)
  const data = JSON.parse(readFileSync(join(here, 'data', 'property.json'), 'utf8'))
  const assets = buildAssets()

  // The HTML is built once, outside the timed section: both approaches get the
  // identical string, and string interpolation is not what is being compared.
  const html = template.render(data, assets)

  const module = await RENDERERS[approach]()
  const renderer = module.createRenderer({
    width: template.width,
    height: template.height,
    scale,
  })

  const sampler = new PeakMemorySampler().start()

  // Cold start: browser launch, or font loading.
  const initStarted = performance.now()
  await renderer.init()
  const initMs = performance.now() - initStarted

  // First render separately: it carries one-off costs (page setup, JIT warmup)
  // that would distort the steady-state numbers if averaged in.
  const firstStarted = performance.now()
  let png = await renderer.render(html)
  const firstRenderMs = performance.now() - firstStarted

  const samples = []
  for (let i = 0; i < iterations; i += 1) {
    const started = performance.now()
    png = await renderer.render(html)
    samples.push(performance.now() - started)
  }

  const breakdown = renderer.getBreakdown?.() ?? null
  const peakRss = sampler.stop()
  const rssBeforeDispose = processTreeRss(process.pid)

  await renderer.dispose()

  const pngPath = join(outDir, `${approach}.png`)
  writeFileSync(pngPath, png)

  const result = {
    approach,
    label: module.label,
    template: templateName,
    output: {
      path: pngPath,
      bytes: png.length,
      logical_size: [template.width, template.height],
      pixel_size: [template.width * scale, template.height * scale],
      scale,
    },
    timing: {
      cold_start_ms: round(initMs),
      first_render_ms: round(firstRenderMs),
      warm: summarise(samples),
      // What one image costs from a cold process — the number that matters if
      // rendering happens in a short-lived worker rather than a warm service.
      cold_total_ms: round(initMs + firstRenderMs),
    },
    memory: {
      baseline_rss_bytes: baselineRss,
      peak_rss_bytes: peakRss,
      peak_over_baseline_bytes:
        peakRss !== null && baselineRss !== null ? peakRss - baselineRss : null,
      rss_at_end_bytes: rssBeforeDispose,
      note:
        peakRss === null
          ? 'Memory unavailable: /proc not present (run this in the Linux container).'
          : 'Peak RSS across this process and all descendants, sampled every 40ms.',
    },
    stage_breakdown: breakdown,
    node_version: process.version,
  }

  writeFileSync(join(outDir, `${approach}.json`), JSON.stringify(result, null, 2))
  process.stdout.write(`${approach}: done\n`)
}

main().catch((error) => {
  process.stderr.write(`${approach}: FAILED\n${error?.stack ?? error}\n`)
  process.exitCode = 1
})
