# Architecture Decision Records

Each ADR captures one significant, hard-to-reverse decision: the context that
forced it, the choice made, and what it costs. They exist because the *reasoning*
behind a decision outlives the person who made it — and because a new
contributor (or an AI agent) that can read *why* the PDF path skips the model, or
why geometry is fractional, makes far better changes than one that has to guess.

This project already documents reasoning unusually well in code comments; ADRs
lift the **cross-cutting** decisions out of the file they happen to live in and
into one findable place.

## Format

[Michael Nygard's format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions):
**Context → Decision → Consequences**, plus a **Status**. Copy
[`template.md`](template.md) for a new one, number it in sequence, and never
edit an accepted ADR to reverse it — write a new one that supersedes it.

Status values: `Proposed`, `Accepted`, `Superseded by ADR-XXXX`, `Deprecated`.

## Index

- [ADR-0001](0001-record-architecture-decisions.md) — Record architecture decisions
- [ADR-0002](0002-fractional-geometry.md) — Elements use fractional geometry
- [ADR-0003](0003-structural-pdf-then-vision.md) — Structural PDF read, vision as fallback
- [ADR-0004](0004-renderer-is-dumb.md) — The renderer is HTML-in, image-out
- [ADR-0005](0005-extraction-validation-is-score-only.md) — Extraction validation scores, never auto-corrects
- [ADR-0006](0006-fonts-are-substituted.md) — Fonts are substituted, not matched
