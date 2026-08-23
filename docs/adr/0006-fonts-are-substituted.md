# ADR-0006: Fonts are substituted, not matched

- **Status:** Accepted
- **Date:** 2026-08-18

## Context

Imported artwork is set in whatever typeface the original designer used —
usually a proprietary Canva or foundry font. The renderer image ships a fixed
set of open fonts (DejaVu, Liberation, Roboto Condensed, Dancing Script…). We
cannot legally bundle arbitrary proprietary fonts, and letting the browser pick
an unknown family makes the export silently disagree with the editor.

## Decision

Templates store a font **role** (`body`, `display`, `serif`, `mono`, `script`),
not a family name. `html_builder.FONT_STACKS` maps each role to an installed
family, chosen to be close in feel — `display` is condensed because flyer
headlines usually are, `script` approximates calligraphy. An imported headline's
family is re-picked by role, and the admin can adjust it in the editor.

## Consequences

- Rendered type will **not** match the source exactly. This is a licensing
  limitation, not a bug, and cannot be fixed in code — it is a hard cap on
  visual fidelity (see ADR-0005).
- A too-large measured font can overflow its box in the wider substitute; the
  renderer's shrink-to-fit and the import-time text-box widening handle that.
- Adding a new role means installing its family in `renderer/Dockerfile` and
  registering it in both `FONT_STACKS` and `document.FONT_FAMILIES`.
