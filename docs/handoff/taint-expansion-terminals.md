# Handoff: taint expansion keeps known exchanges under the share

- **Feature**: with EXCHEQUER_TAINT_EXPANSION on, a payment under the 1% share straight to a known exchange or flagged address is still in the case
- **Issue**: #382
- **Branch**: `feat/taint-expansion-terminals`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: PR open for review; the flag stays off by default

## Done

- `backend/app/graph_builder.py` `_choose_branches`: the share rule also keeps counterparties `is_terminal` names (never expanded, so no extra read), within the same hard cap. Below-share ordinary addresses stay untraced and reported as before.
- Tests in `backend/tests/test_taint_expansion.py`, one through the pipeline with the flag on.

## Decisions

- Kept terminals are bounded by `TRACE_MAX_BRANCHES_HARD` separately from the carrying branches, so a wallet paying many exchanges cannot grow the graph without bound.

## Next

1. None for this fix. Found by the flag sweep (every FLAGS flag on, full backend suite).

## Open questions

- none

## Files mid-change (do not touch)

- none
