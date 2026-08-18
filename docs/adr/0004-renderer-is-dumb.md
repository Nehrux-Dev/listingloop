# ADR-0004: The renderer is HTML-in, image-out

- **Status:** Accepted
- **Date:** 2026-08-18 (records the `renderer/` service design)

## Context

Exporting a design to an image needs a browser (Chromium). Launching one per
image costs ~430ms; reusing a warm one costs nothing. But a browser is ~700MB
and renders arbitrary HTML, which is a security surface.

## Decision

Keep Chromium in its **own service** (`renderer/`) that does exactly one thing:
take HTML + a size, return an image. **All template logic stays in Django**
(`html_builder.py` composes the HTML). The renderer is network-isolated, guarded
by a shared token, and runs pages with **JavaScript disabled and no network** —
every asset is inlined as a data URI. The shrink-to-fit pass runs as renderer
code (`page.evaluate`), not as a script in the untrusted document.

## Consequences

- The renderer can be scaled, restarted or swapped without any template logic
  moving, and everything up to the screenshot is testable in Python.
- A template can neither call out nor probe internal services.
- CSS that can fetch (`clip-path`, `background-image`) must be built from
  numbers, never a pass-through string — see ADR-0002's downstream rule and the
  `GRADIENT_RE`/`_clip_path` guards.
- **Resist adding logic to the renderer.** Its dumbness is what keeps the
  security boundary enforceable rather than a comment.
