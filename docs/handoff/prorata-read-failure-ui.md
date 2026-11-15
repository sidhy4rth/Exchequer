# Handoff: pro-rata read failure on the trace screen

- **Feature**: when the pro-rata amount check failed at the data provider, the trace screen says so next to the pro-rata line, and that tracing again later should give a complete score
- **Issue**: #322
- **Branch**: `feat/prorata-read-failure-ui` (stacked on `fix/prorata-read-failure`, PR #321)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: claimed, in progress

## Done

- nothing yet

## Decisions

- none yet

## Next

1. Add a small frontend module with the `read_failure` wording (mirrors `READ_FAILURE_WORDING` in `backend/app/prorata.py`), a component that renders the sentence, and one mount line in `frontend/src/routes/TraceView.jsx` under the pro-rata line.

## Open questions

- none

## Files mid-change (do not touch)

- none
