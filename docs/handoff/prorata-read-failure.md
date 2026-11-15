# Handoff: pro-rata read failure

- **Feature**: when the pro-rata window read fails at the provider, retry it once and, if it still fails, say so plainly instead of silently lowering the score
- **Issue**: #320
- **Branch**: `fix/prorata-read-failure`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: claimed, in progress

## Done

- Claimed.

## Decisions

- Scoring unchanged: [ADR-0007](../adr/0007-pro-rata-not-all-or-nothing.md) says a wallet that could not be read in full earns the amount no credit, so "unknown" stays 0; only the disclosure is added.

## Next

1. Re-read on a transient failure, disclose a failed read in the score, report and letter, flag `prorata.read_failure`.

## Open questions

- none

## Files mid-change (do not touch)

- none
