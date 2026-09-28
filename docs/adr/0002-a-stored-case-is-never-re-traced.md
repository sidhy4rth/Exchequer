# ADR-0002: A stored case is never re-traced

**Date**: 2026-09-05
**Status**: accepted
**Deciders**: Sidhyarth

## Context

The chain keeps moving. A pattern rule is a threshold comparison against live
data, so a wallet that met the amount-split threshold this morning may not
meet it this afternoon once more money has arrived (DEMO.md trace 02 is exactly
that). An investigator needs the evidence as it stood when it was taken.

## Decision

Every trace is saved as a case with its own id (`app/models.py`). Opening
`/case/<id>` reads that stored result back and never runs the traversal again
(`frontend/src/App.jsx`, `routes/cases.py: get_trace`). Re-tracing is a
separate, explicit button.

## Alternatives Considered

### Re-run the trace whenever a case is opened
- **Pros**: always current.
- **Cons**: the findings can silently change between two people reading "the same case".
- **Why not**: evidence that changes when you look at it is not evidence.

## Consequences

### Positive
- A report, a letter and a screenshot of the same case always agree.
- Opening a case costs no provider requests, so it is instant and free.

### Negative
- A stored case can be out of date; the header shows when it was archived.

### Risks
- Anyone can add cases to the public demo store. Noted in the 28 Sep audit; a cap or pruning job would bound it.
