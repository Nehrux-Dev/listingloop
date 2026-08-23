# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Group entries under **Added / Changed / Fixed / Removed**, newest section on top,
and move them from *Unreleased* into a dated version when you cut a release.

## [Unreleased]

### Added
- **Embedded-state tier in the listing importer** (`extraction.py`): reads the
  JSON a JavaScript-built site ships its own page data in — `__NEXT_DATA__`
  data islands, `window.__INITIAL_STATE__`-style assignments, Rightmove-style
  `PAGE_MODEL` — parsed strictly as JSON, never evaluated. Only unambiguous
  keys are read; a value is used only when every listing-shaped object on the
  page agrees on it; arrays of listing cards (search results, "similar homes")
  are skipped wholesale. Often answers from the plain fetch, saving the
  browser re-fetch. Sits between the schema.org tiers and Open Graph, keeping
  the never-invent-data rule.
- **Responsive layout across the app**: below `md` the navigation rail becomes
  a hamburger-and-drawer with a sticky top bar (all three shells share it via
  `DashboardShell`); the template gallery's filter column and the editor's
  tool/properties panels float over the content instead of squeezing it off a
  phone screen; the editor header folds Preview/Import-listing into the
  overflow menu on small screens and drops the zoom cluster. Editor and wide
  pages use `h-dvh` so mobile URL-bar chrome doesn't clip the workspace.
  Verified headlessly at 390/768/1440 px — no horizontal overflow, no errors.
- **Agent dashboard**: the front door now answers "what should I do next?" —
  quick-create tiles, a resume-your-designs row, listings with no marketing
  made for them yet, the next occasions from the content calendar, and recent
  enquiries with a new-count. Every block is a doorway to an existing screen;
  the dashboard owns no feature of its own, and each section loads and fails
  independently. Backend health moved to Settings (diagnostic, not actionable).
- **Format adaptation** (`layout_adaptation.py` + `POST .../adapt`): re-lays a
  design out for a different output format (square post → story → banner)
  structurally, with no model call — uniform contain scale, edge anchoring,
  full-span stretch, and cluster grouping. Runs once server-side when a design
  is copied for a format; the output is an ordinary, hand-editable document.
  Designs record a `preferred_dimension` so exports default to the right shape.
- **Font library**: six new authoring families (EB Garamond, Lato, Quicksand,
  Roboto Slab, Lobster Two, Comfortaa), vendored as WOFF2 for the editor and
  installed from Debian in the renderer image, so both surfaces render the
  same glyphs. Fonts load lazily — a face costs nothing until an element uses it.
- **Shape toolbox** (`shapeLibrary.ts`, `LeftPanel.tsx`): a drag-and-drop
  Elements panel of ready-made shapes, lines, and frames.
- **Canvas context menu + shortcuts** (`ContextMenu.tsx`, `elementClipboard.ts`):
  right-click copy/paste/duplicate/layer-order/lock plus the matching keyboard
  shortcuts; the clipboard is module-level so elements paste across designs.
- **Color presets** (`colorPresets.ts`): curated swatches in the color controls.
- **CI** (`.github/workflows/ci.yml`): runs the backend test suite against
  Postgres and the frontend type-check/build on every push and pull request.
  The suite cannot run on a bare dev host (needs Python 3.12 + PyMuPDF), so this
  is where tests actually run.
- **Extraction evals** (`run_extraction_evals` management command + `backend/eval/`):
  scores the extraction pipeline over a golden set of real flyers and diffs
  against a baseline to catch silent regressions.
- **Extraction validation** (`extraction_validation.py`): renders an extracted
  layout back to a raster and scores it against the source. Off by default
  (`TEMPLATE_IMPORT_VALIDATE`); diagnostic only, never rewrites geometry.
- **Import debug gallery** (`extraction_debug.py`, `TEMPLATE_IMPORT_DEBUG`):
  per-stage images (extracted/aligned boxes, difference) plus a JSON report.
- **Structural PDF extraction** (`pdf_extraction.py`): reads a text PDF's own
  content stream instead of paying for a vision call; vision remains the
  fallback for scans and images.
- Project scaffolding: `CLAUDE.md`, `docs/adr/` (ADR-0001…0006), this changelog.

### Changed
- **Selection UI reworked Canva-style**: a docked top toolbar for the selected
  element's properties, a floating quick-actions pill (`QuickActions.tsx`) at
  the selection, and the full properties sidebar opened on demand via the
  Position button instead of being always present.
- **Import fidelity upgrades** (`pdf_extraction.py`, `importing.py`): letter
  tracking compensation, five-bucket font classification for substitutes,
  offset auto-correction, rotated-text support, alignment inference,
  gradient/texture rescue for decorated backgrounds, embedded-image baking,
  and structural (no-render) scoring.
- **Smart geometry tidy-up** at import (`TEMPLATE_IMPORT_SMART_GEOMETRY`, default
  on): size-aware edge snapping, spacing regularisation, alignment-relationship
  metadata, and crop-geometry preservation for photos that bleed off-canvas.

### Fixed
- Clipped prices at import (`$1,300,000` rendering as `$1,300,00`): too-narrow
  text boxes are now widened to fit the substitute font, anchored by text-align.

## Notes

Known limits that are **not** bugs (see `docs/adr/`): rendered fonts do not match
the source (ADR-0006), and an imported template is deliberately editable rather
than a pixel copy (ADR-0005).
