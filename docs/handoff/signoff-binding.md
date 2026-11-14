# Handoff: signoff-binding

- **Feature**: suite feature 7 follow-up to #99: a second officer's sign-off on an urgent bank hold covers only the exact details they approved
- **Issue**: #132
- **Branch**: `feat/signoff-binding`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: claimed; tests and fix in progress

## Done

- Confirmed the gap: `freeze_requests.approval(case_id, kind, user)` finds any signed-off `bank-freeze` row for the case, and `POST /trace/{id}/notice` prints "Approved by a second officer" on a letter with whatever account, IFSC, amount and order the body carries.

## Decisions

- Bind with a fingerprint: SHA-256 over a canonical JSON of the case id, the notice kind and the details as the letter prints them (after its own normalisation), stored on the request when it is put up for sign-off.

## Next

1. Tests first in `backend/tests/test_notice_letters.py`, then the fix.

## Open questions

- none

## Files mid-change (do not touch)

- `backend/app/notice_letters.py`, `backend/app/freeze_requests.py`, `backend/app/routes/evidence.py`, `backend/app/routes/requests.py`: the binding
