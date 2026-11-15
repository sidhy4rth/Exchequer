# Handoff: trace screen shows a label-store row's basis

- **Feature**: when the trace's case address came from a label-store exchange row, the trace screen says what the attribution stands on (the exchange's own list, and for a deposit row the sweep), in the report's words
- **Issue**: #336
- **Branch**: `feat/trace-deposit-basis`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: claimed; draft PR open

## Done

- nothing yet

## Decisions

- Reads `matches[].attribution_basis` (`docs/contracts/case.md`), already in the trace result since #267; no backend change.

## Next

1. `frontend/src/components/case/StoreRowBasis.jsx` (+ `.css`, test), mounted once in `frontend/src/routes/TraceView.jsx` under the address to cite.

## Open questions

- none

## Files mid-change (do not touch)

- none
