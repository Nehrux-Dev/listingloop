# ADR-0003: Structural PDF read, vision model as fallback

- **Status:** Accepted
- **Date:** 2026-08-18 (records the decision behind `pdf_extraction.py`)

## Context

An uploaded flyer must become an editable template — a list of elements with
geometry, colours and text. A PDF exported from a design tool already contains
that answer: every text run carries its string, box, size and colour; every
photo its rectangle; every panel a filled path. Rasterising that and asking a
vision model to measure it back is slower, costs money per import, needs an API
key, and is *less* accurate than reading the file.

## Decision

Route text PDFs through a **structural read** (`extract_pdf_layout`, via
PyMuPDF) that reconstructs the layout from the content stream. Everything else —
scans, JPEG/PNG uploads, PDFs whose text was converted to outlines — goes to the
**vision model** (`extract_layout`). `is_text_pdf()` decides. Both paths emit
the **same payload shape**, so normalisation, baking and template-building can't
tell which ran. A structural read that fails falls through to the model rather
than failing the import.

## Consequences

- Text-PDF imports are exact, instant, free, and need no API key.
- The structural path cannot infer semantic role, so it binds only where the
  text is unambiguous (a price, a phone, a URL) and leaves the rest for the
  admin — inventing bindings from weak signals is worse than none.
- Two code paths to keep in sync on payload shape; the shared shape is the
  contract, guarded by tests.
- **Do not** add a model call to the text-PDF path — its freedom and exactness
  are the entire point.
