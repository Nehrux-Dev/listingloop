# ADR-0002: Elements use fractional geometry

- **Status:** Accepted
- **Date:** 2026-08-18 (records a decision made earlier in the code)

## Context

One design has to render at several sizes — Instagram Post (1080×1080), Story
(1080×1920), Facebook and LinkedIn (wide), and portrait flyer — and, for
imports, at the source raster's own size. Storing element positions in pixels
would mean one hand-built layout per format, and every re-render at a new size
would be wrong.

## Decision

Store every element's position and size as a **fraction of the canvas** (0..1),
not pixels. Font size and spacing scale against the **shorter side**
(`min(width, height)`), because scaling against height overflowed boxes on tall
formats and against width overflowed them on wide ones. Mapping a design onto a
target dimension is then arithmetic, done once in `html_builder.py`.

## Consequences

- One template renders at every dimension for free; the safe-area insets of a
  format are applied at render time.
- Everything downstream must respect this: extraction converts pixels to
  fractions in `normalise_elements`, and nothing may store a pixel on an element.
- Sub-pixel rounding exists but is negligible (4 dp at 2000px ≈ 0.2px).
- The three shrink-to-fit implementations (backend, renderer, editor) must agree
  on the same scale reference, or canvas and export diverge.
