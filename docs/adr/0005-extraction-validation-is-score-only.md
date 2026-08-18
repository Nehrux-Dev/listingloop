# ADR-0005: Extraction validation scores, never auto-corrects

- **Status:** Accepted
- **Date:** 2026-08-18

## Context

Extraction measures each element on its own and never checks the whole against
the source page. A render-and-compare loop can close that gap — rebuild the
layout, screenshot it, diff it against the upload. The tempting next step is to
*auto-correct* geometry from the diff. But attributing a pixel difference to a
specific element and computing a safe correction is hard, and a naive corrector
moves correct elements as readily as it fixes wrong ones. Pixel-perfect is also
the wrong target: it is reached by baking the whole flyer as one flat image,
which destroys editability (the product's whole premise).

## Decision

`extraction_validation.py` renders the extracted layout through the same
`html_builder`/renderer an export uses, computes a deterministic similarity
score and per-element offsets, and **reports** them — as an import warning and,
in batch, through `run_extraction_evals`. It does **not** rewrite geometry. It is
**off by default** (`TEMPLATE_IMPORT_VALIDATE`), skipped for text PDFs (whose
geometry is exact), and a renderer outage is swallowed, never fatal.

## Consequences

- A reconstruction that came back wrong is surfaced with a number, at upload
  time and in CI-able evals, instead of discovered weeks later.
- No risk of the validator making a template worse.
- Fidelity has a deliberate ceiling: fonts are substituted (ADR-0006) and the
  design stays editable, so the score targets "visually close", not "identical".
- Enabling validation makes the import worker depend on the renderer being up.
