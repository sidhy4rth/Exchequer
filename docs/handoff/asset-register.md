# Handoff: asset-register

- **Feature**: suite feature 9 (custody wallet tooling): a register of every amount frozen or seized in a case, where it is held, and its court deadline
- **Issue**: #100
- **Branch**: `feat/asset-register`
- **Current**: Barenyam
- **Last worked on**: Barenyam, 2026-11-12
- **Status**: claimed; plan written, no code yet

## The nine features (see `docs/suite-features.md`)

1 Attribution data (Sidhyarth, #91) · 2 Mobile and computer forensics · 3 Memory and disk tools · 4 OSINT · 5 Telecom and bank analysis · 6 Case management and evidence locker · 7 Request and letter generator (bank and telecom notices merged in #99) · 8 Government platforms · **9 Custody wallet tooling (Barenyam, this file)**. Unnamed ones are unclaimed.

## Done

- Read `freeze_requests.py`: a request already records status "frozen" with `amount_frozen` and `asset`. An asset row can point at the request that froze it (`request_id`) instead of copying it.

## Decisions

- Never store a private key, seed phrase or extended key. Free-text fields refuse text shaped like one; key holders are names only.
- Amounts are kept as exact decimal text, not floats: a register of seized funds must not drift by rounding.
- The court deadline is 45 days from the seizure date (BNSS s.497 as read by the Karnataka High Court in Mukesh Jain); shown as a count of days, the source named in the UI.

## Next

1. Server PR: Alembic migration (one new table, `seized_assets`, after `g6_queue_2`), model, `backend/app/assets.py`, routes `GET/POST /trace/{case_id}/assets` and `PATCH /assets/{asset_id}` (each takes `current_user` and calls `audit.record`), tests first.
2. Screen PR: an "Assets" tab in the case, listing rows with days left to the deadline, a form to add one, and the outcome buttons.

## Open questions

- Should the home page show assets whose deadline is within 7 days? (Sidhyarth: the home page is platform.)

## Files mid-change (do not touch)

- none yet
