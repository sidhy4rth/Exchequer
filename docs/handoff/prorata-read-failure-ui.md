# Handoff: pro-rata read failure on the trace screen

- **Feature**: when the pro-rata amount check failed at the data provider, the trace screen says so next to the pro-rata line, and that tracing again later should give a complete score
- **Issue**: #322
- **Branch**: `feat/prorata-read-failure-ui` (stacked on `fix/prorata-read-failure`, PR #321)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: done, PR #323 ready for review (retarget to `main` after #321 merges)

## Done

- PR #323: `frontend/src/components/case/ProrataReadFailure.jsx` (+ `.css`) shows, under the trace screen's pro-rata line, "Amount not checked: The amount check could not be done: <words>. Trace again later for a complete score." when `prorata.status` is `unknown` and `prorata.read_failure` is set; nothing otherwise. The words come from `readFailureWording.js`, which mirrors `READ_FAILURE_WORDING` in `backend/app/prorata.py`; one mount line in `frontend/src/routes/TraceView.jsx`.
- Tests: `ProrataReadFailure.test.jsx` (every kind, unknown kind, field absent, other statuses), two in `TraceView.test.jsx` (shown; absent leaves the line unchanged), and `test_the_trace_screen_uses_the_same_read_failure_wording` in `backend/tests/test_prorata_read_failure.py` pins the two wording maps together.

## Decisions

- The module is `readFailureWording.js`, not `prorataReadFailure.js`: on a case-insensitive disk (macOS) that name collides with `ProrataReadFailure.jsx`.
- Said in words with a bold label and a grey rule, not colour: it is a disclosure, not a risk finding.

## Next

1. none

## Open questions

- none

## Files mid-change (do not touch)

- none
