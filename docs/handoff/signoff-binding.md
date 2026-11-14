# Handoff: signoff-binding

- **Feature**: suite feature 7 follow-up to #99: a second officer's sign-off on an urgent bank hold covers only the exact details they approved
- **Issue**: #132
- **Branch**: `feat/signoff-binding`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: done in #133, waiting for review

## Done

- Confirmed the gap: `freeze_requests.approval(case_id, kind, user)` found any signed-off `bank-freeze` row for the case, so `POST /trace/{id}/notice` printed "Approved by a second officer" on a letter with any account, IFSC, amount or order.
- `notice_letters.fingerprint(case_id, to, details)`: SHA-256 over a canonical JSON of the case id, the notice and the hold's details as the letter prints them (`_hold`: account without spaces, IFSC upper-cased, amount as two-decimal rupees or none). `None` for the notices without a sign-off. The hold's draft prints its first 16 hex characters.
- `freeze_requests`: a bank hold is put up for sign-off (`POST /requests` or `PATCH /requests/{id}` to `awaiting_signoff`) only with `details`; only the fingerprint is stored (`details_fingerprint`, migration `g7_signoff_binding_1`). The sign-off (`POST /requests/{id}/signoff`) must carry the details on the second officer's screen, and they must give the same fingerprint (409 if not). `approval()` counts a hold's sign-off only for a letter whose details give that fingerprint.
- The audit rows `request.signoff_ask` and `request.signoff` carry the request id only, no part of the fingerprint (pre-review: an unkeyed hash over guessable details does not belong in the audit log). The full fingerprint lives on the request row only.
- A signed-off hold is logged as sent (or acknowledged, frozen, declined) only with `details` that give the signed-off fingerprint (400 otherwise); the Letters tab's Mark as sent sends them. From the requests log, which has no details, a hold cannot be marked sent. Closing never needs them.
- Putting a waiting hold up again with new details is audited as `request.signoff_ask`, not `request.update`.
- Letters tab: Ask for sign-off and Sign off send the hold's typed details; the Second officer card shows the fingerprint the request covers.
- Tests: `backend/tests/test_notice_letters.py` (reproduces the bug for each detail, normalisation, refusals, fresh sign-off, audit and store hold no account number); `frontend/src/components/case/NoticeForm.test.jsx` (three).

## Decisions

- A new column rather than reusing one: no existing column of `freeze_requests` means "what was approved" (`notes` and `reference` are the drafter's to edit).
- The fingerprint covers what the letter prints, so typing differences the letter erases ("2,50,000" vs 250000, spaces in the account, lower-case IFSC) still match; any printed difference (bank name, source, order, amount) needs a fresh sign-off.
- Plain SHA-256, not keyed: the deployment has no general server secret. The fingerprint covers free text (order, source) as well as the account number, which makes guessing an account from it impractical.
- A hold signed off before this change has no fingerprint, so its letter reads "Awaiting" until the drafter closes the request and asks again.

## Next

1. Review and merge #133. If #122 or #124 merges first, re-point `down_revision` of `backend/migrations/versions/g7_signoff_binding_1.py` to the new head.

## Open questions

- none

## Files mid-change (do not touch)

- none
