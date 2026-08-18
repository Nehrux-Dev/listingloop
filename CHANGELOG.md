# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Group entries under **Added / Changed / Fixed / Removed**, newest section on top,
and move them from *Unreleased* into a dated version when you cut a release.

## [Unreleased]

### Added
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
