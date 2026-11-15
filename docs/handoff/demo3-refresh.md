# Handoff: demo3-refresh

- **Feature**: DEMO.md trace 3 says what the live trace shows again, so the demo check passes honestly
- **Issue**: #259
- **Branch**: `demos/demo3-refresh`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: PR open, ready for merge by the owner

## Done

- Live trace of demo 3 run (save: false) and the wallet's history checked on Blockscout's public list: about 700-800 transactions a day since 9 Nov, so the 200 newest records cover a few hours.
- DEMO.md section 3 and README demo row updated to the 15 Nov result (no exchange within 3 hops); `demo_expectations.json` re-recorded with `check_demos.py --record` (only demo 3 changed).

## Decisions

- Record what the trace shows (no exchange) rather than pin it: the trace request has no block or time window to pin to.

## Next

1. Nothing for this branch. If demo 3 should stay a reliable on-stage demo, the owner picks a quieter documented wallet (see open question).

## Open questions

- Demo 3 now flips between an exchange and none within hours, and with its expectation at none the daily check can no longer fail on it. Keep it as the "attribution that moves" demo, or replace it with a quieter wallet? Owner to decide.

## Files mid-change (do not touch)

- none
