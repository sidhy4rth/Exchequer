# Handoff: letter-of-request-store-basis

- **Feature**: the letter of request (feature 7) prints what a label-store exchange row's attribution stands on, in the report's words
- **Issue**: #348
- **Branch**: `feat/lor-deposit-basis`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: PR #349 open for review; shows only with `EXCHEQUER_STORE_EXCHANGE_ROWS` on (off), since only a store row carries the field

## Done

- Claimed (this file, draft PR #349).
- `backend/app/letters_of_request.py`: in the Statement of Facts, after the claim (which already says "own published
  address list, below"), the draft prints `report.basis_lines(report.store_basis(trace), exchange)`, each line
  wrapped like the rest of the letter (never a hash split). Nothing when the case's match has no basis.
- Tests: `backend/tests/test_letter_of_request_store_basis.py`: own-wallet row, deposit row (the inference wording),
  and four cases without a basis (no matches, no basis, a basis with no source, another address's row) pinned to the
  SHA-256 of the draft on main before this change.

## Decisions

- Same lines as the report and the exchange letter (`report.basis_lines`), no new wording and no lead-in: the claim
  above them already points to them, as in `request_letters.py`.

## Next

1. Review and merge #349. Nothing else here; turning the flag on is `store-deposit-rows.md` Next 3.

## Open questions

- none

## Files mid-change (do not touch)

- none
