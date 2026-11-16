# Handoff: demo3-refresh

- **Feature**: DEMO.md trace 3 says what the live trace shows again, so the demo check passes honestly
- **Issue**: #259
- **Branch**: `demos/demo3-refresh`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: merged in #260 (`2985a4b4`); demo 3 was then replaced by #286

## Done

- Live trace of demo 3 run (save: false) and the wallet's history checked on Blockscout's public list: about 700-800 transactions a day since 9 Nov, so the 200 newest records cover a few hours.
- DEMO.md section 3 and README demo row updated to the 15 Nov result (no exchange within 3 hops); `demo_expectations.json` re-recorded with `check_demos.py --record` (only demo 3 changed).

## Decisions

- Record what the trace shows (no exchange) rather than pin it: the trace request has no block or time window to pin to.

## Next

1. None. ~~If demo 3 should stay a reliable on-stage demo, the owner picks a quieter documented wallet.~~ Done: the owner approved a quiet documented phishing wallet for demo 3 on 15 Nov, merged in #286 (`dde8e1ee`, `demo3-candidate-a.md`).

## Open questions

- ~~Demo 3 now flips between an exchange and none within hours. Keep it as the "attribution that moves" demo, or replace it with a quieter wallet?~~ Answered: replaced (#286).

## Files mid-change (do not touch)

- none
