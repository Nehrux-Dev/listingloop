# Rendering approach prototype

Standalone comparison of two ways to turn an HTML/CSS template plus property
data into a PNG. **Not wired into the app** — it is here to inform one
decision, and can be deleted once that decision is made.

- **A — Headless browser**: Playwright + Chromium, screenshot the page.
- **B — Structured render**: Satori (element tree → SVG) + resvg (SVG → PNG),
  no browser.

Both consume the **same HTML string** from the same template module, so the
comparison is like-for-like.

## Run it

```bash
docker build -t render-comparison prototypes/render-comparison
docker run --rm -v "$PWD/prototypes/render-comparison/output:/app/output" \
  render-comparison node src/index.js --iterations 12 --scale 2
```

PowerShell:

```powershell
docker build -t render-comparison e:\Real_Estate\prototypes\render-comparison
docker run --rm -v e:\Real_Estate\prototypes\render-comparison\output:/app/output `
  render-comparison node src/index.js --iterations 12 --scale 2
```

Flags: `--iterations N` (warm runs, default 10), `--scale N` (output pixel
ratio, default 2), `--template <name>` (module in `src/templates/`).

Writes to `output/`: `playwright.png`, `satori.png`, `diff.png`, `report.md`,
`report.json`, plus a per-approach JSON.

It runs in Docker on purpose: the numbers should reflect Linux, which is where
this would deploy, and the memory measurement reads `/proc`.

---

## Results

1080×1350 card, 12 warm iterations, Node 22, Linux container on this machine.
Each approach ran in its own process so memory is not cross-contaminated.

### At 2× (2160×2700 output)

| | A — Playwright | B — Satori + resvg |
| --- | ---: | ---: |
| Cold start (engine init) | 429 ms | **2.4 ms** |
| First render | 1027 ms | 1578 ms |
| One image from cold | **1456 ms** | 1580 ms |
| Warm median | **283 ms** | 763 ms |
| Warm p95 | **423 ms** | 1160 ms |
| Peak RSS (process tree) | 722 MB | **93 MB** |
| PNG size | 266 KB | 259 KB |
| Pixels differing from A | — | 0.84% |

### At 1× (1080×1350 output)

| | A — Playwright | B — Satori + resvg |
| --- | ---: | ---: |
| Warm median | **120 ms** | 297 ms |
| Warm p95 | **203 ms** | 519 ms |
| Peak RSS | 618 MB | **92 MB** |
| PNG size | 112 KB | 95 KB |
| Pixels differing from A | — | 0.89% |

---

## What the numbers mean

**Satori is not the fast one.** That was the surprise. The expectation going in
was that avoiding a browser would be faster; it is roughly 2.5× *slower* per
image at both scales. The stage split explains it: layout to SVG is genuinely
quick (~64–81 ms), but rasterising is 215 ms at 1× and 561 ms at 2×. Satori
outlines every glyph to a `<path>`, producing a 185 KB SVG of vector text that
resvg then has to fill. Chromium's rasteriser is simply better optimised for
this, and it scales better with pixel count.

**Playwright's memory cost is the real trade.** 620–720 MB peak versus a flat
~92 MB. Satori's footprint barely moves between 1× and 2×; Chromium's grows
with the output. On a small VPS that difference decides how many concurrent
renders fit before the OOM killer arrives.

**Cold start differs by 180×** (429 ms vs 2.4 ms). This only matters if
rendering happens in a short-lived process. Keep a browser warm and it is a
startup cost paid once; render in a per-request Lambda-style worker and
Playwright pays it every time.

**Fidelity is closer than expected: 0.84%.** The diff image is what settles
it. Yellow is antialiasing noise and can be ignored. The red — actual
differences — is concentrated at the *ends of long text lines*: the word
"Terrace" at the end of the address, the tail of the disclaimer sentence.
Glyph advances accumulate slightly differently, so a long line drifts one or
two pixels by its end. Every box, gradient, border-radius, image and chip lands
in the same place. For marketing collateral this is invisible; for anything
pixel-matched against a design comp, it is a real (if small) divergence.

## The constraint that does not show up in the numbers

To get a fair comparison the template had to be authored in **Satori's subset**,
and that subset is narrow:

- Inline `style` attributes only — no `<style>` blocks, no classes, no external
  CSS. `satori-html` reads nothing else.
- Flexbox and absolute positioning only, declared explicitly. No grid, no
  float, no `display:block` with multiple children.
- No pseudo-elements, filters, blend modes, transforms, or `@font-face`.
- Fonts must be supplied as buffers. Satori has **no system-font fallback** — a
  missing family means missing text, not substituted text.
- Images as data URIs or fetched separately.

Chromium renders that template happily. The reverse is not true: an arbitrary
designer-authored template will not run in Satori without being rewritten.
That asymmetry is the strategic question — it is about who authors templates
and how, not about milliseconds.

## Suggested reading of this

Neither result is a knockout, and they point in different directions:

- If templates will be **designer-authored, varied, and visually ambitious**,
  Approach A. It costs memory and needs a warm browser pool, but any template
  that renders in a browser renders here, and it is faster per image.
- If templates will be **a fixed, code-owned set** built to the constraints
  above, Approach B. The memory profile is dramatically better and there is no
  browser to supervise, at the cost of ~2.5× render time and a narrow
  authoring surface.

## Not measured

Worth doing before committing, if the decision is close:

- **Concurrency and throughput.** The decisive number for a template library is
  images/second under load, not one image in isolation. Chromium amortises
  across pages in one browser; Satori is CPU-bound and would scale by forking
  workers. This prototype measures neither.
- Real designer templates, especially any using grid, custom web fonts or
  effects — that is where Approach B either works or does not.
- Image size/complexity beyond one sample, and non-Latin text (Satori needs a
  font buffer per script; Chromium falls back on system fonts).

## Files

```
src/
  index.js              orchestrates, diffs, writes the report
  run-one.js            runs ONE approach in its own process (clean memory)
  render/playwright.js  approach A
  render/satori.js      approach B
  templates/            the sample template — swap in your own here
  data/property.json    sample data, shaped like the real API payloads
  lib/measure.js        timing + /proc process-tree RSS sampling
  lib/compare.js        pixelmatch diff
  lib/assets.js         procedurally generated sample imagery (no binaries)
```

To try your own design, add `src/templates/<name>.js` exporting `width`,
`height` and `render(data, assets)`, then pass `--template <name>`. If it is
regular designer HTML/CSS it will likely render under A immediately and need
rewriting for B — which is itself the answer to the question this prototype
asks.
