# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-08-18

## Context

The codebase documents *why* heavily in code comments, which is excellent for
the file you are already reading — but a cross-cutting decision (why geometry is
fractional, why the PDF path skips the model) is invisible until you happen to
open the right file. New contributors, and AI coding agents that start each
session with no memory, re-litigate settled decisions or unknowingly break them.

## Decision

Keep Architecture Decision Records in `docs/adr/`, one file per significant
decision, in Nygard's Context/Decision/Consequences format. Record a decision
here when it is cross-cutting and expensive to reverse. Leave local, single-file
reasoning where it is — in the code.

## Consequences

- A findable, append-only history of the big choices, readable by people and
  agents alike.
- A small discipline cost: a non-trivial architectural change should come with
  an ADR. Superseding a decision means a new ADR, not editing the old one.
- ADRs will lag reality if not kept up; the index in the README is the check.
