# CLAUDE.md

Agent context for this repo. Kept short on purpose — the exhaustive reference
is [README.md](README.md), and the reasoning behind big decisions lives in
[docs/adr/](docs/adr/). This file is only the things that apply everywhere.

## What this is

**Listing Studio** — a real-estate marketing tool. An agent picks a template,
attaches a listing, and exports on-brand artwork (social post, story, flyer)
without a designer. The distinctive part is **template import**: an uploaded
PDF or image of a flyer is turned into an *editable* template.

## Stack

- **Backend** — Django 5.2 + DRF, Celery (Redis), Postgres. Python 3.12.
- **Renderer** — a separate Node/Chromium service (`renderer/`) that takes HTML
  and returns an image. It owns no template logic.
- **Frontend** — React + TypeScript + Vite (`frontend/`).

## Commands

The suite needs Python 3.12 + PyMuPDF + Postgres, so run it in Docker, not on a
bare host:

```bash
docker compose run --rm backend python manage.py test        # backend tests
docker compose run --rm backend python manage.py test apps.templates  # one app
cd frontend && npm run typecheck && npm run build            # frontend
docker compose up                                            # full dev stack
```

CI (`.github/workflows/ci.yml`) runs the same on every push. If you can't run a
test locally, say so — don't claim it passed.

## Architecture map

- `backend/apps/templates/` — the heart of the product.
  - `importing.py` — the import pipeline (rasterise → extract → align → normalise → bake → build).
  - `pdf_extraction.py` — structural read of a text PDF (no model call).
  - `html_builder.py` — elements → HTML. **The renderer and the editor must render identically to this.**
  - `document.py` — the element document schema + validation.
  - `extraction_validation.py` / `extraction_debug.py` — render-and-compare scoring + debug gallery.
- `renderer/` — HTML-in, image-out. Never give it template logic.
- `frontend/src/components/design-editor/` — the canvas editor.

## Conventions

- **Explain *why*, not *what*.** This codebase documents reasoning heavily (see
  the module docstrings in `importing.py`). Match that density; a comment that
  restates the code earns nothing, one that records a decision earns its place.
- **Geometry is fractional** (0..1 of the canvas), so one template renders at
  every dimension. Never store pixels on an element.
- **Untrusted model output is clamped, never rejected.** A bad element is
  skipped or bounded; one bad element must not fail a 40-element import.
- **Three places must agree** on shrink-to-fit (`FIT_MIN_SCALE`/`FIT_STEPS`):
  `html_builder.py`, `renderer/src/server.js`, `ElementLayer.tsx`. Change one,
  change all three — the parity tests enforce it.
- **Prefer PowerShell-safe, cross-platform code.** Primary dev is Windows.

## Security — do not weaken these

- `clip-path`, `background-image` gradients, and dot patterns are built from
  **numbers only**, never a pass-through string — those CSS properties accept
  `url(...)`, so a string is an exfiltration hole. See `_clip_path`,
  `_dot_pattern`, `GRADIENT_RE`.
- The renderer runs with **JavaScript disabled and no network**; every asset is
  inlined. Keep it that way.
- A **logo is never baked** from source artwork (it asserts who published the
  design); it binds to `brokerage.logo` and readiness gates on it.

## Directories to leave alone unless asked

- `backend/apps/templates/migrations/` — never hand-edit; generate.
- `renderer/` — a deliberately dumb box; resist adding logic to it.
- `.claude/`, `Listing-Studio-Proposal.md` (gitignored) — not app code.

## Anti-patterns (don't)

- Don't make imports pixel-identical by baking the flyer as one image — it must
  stay editable.
- Don't try to match the original's fonts — they aren't installed and can't be
  licensed by code. This is a known limit, not a bug.
- Don't add a vision-model call to the text-PDF path — structural reads are
  free and exact; that property is the point.
- Don't commit or push unless asked. Branch off `main` first if asked to.
