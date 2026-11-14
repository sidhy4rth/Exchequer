# Handoff: assets-amount-length

- **Feature**: the asset register refuses an amount too long for its column with a clear 400, instead of a 500 on Postgres
- **Issue**: #171
- **Branch**: `fix/assets-amount-length`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: open for review

## Done

- `backend/app/assets.py`: `AMOUNT_CHARS = 48` (the `SeizedAsset.amount` column). `_amount` refuses a typed amount longer than that (before parsing, so a pasted wall of digits costs nothing) and one that is longer once written out in full (`1e-60` is 62 characters). The message names the limit.
- `backend/tests/test_assets.py`: four too-long shapes refused, exactly 48 characters kept, the route answers 400 with the reason.

## Decisions

- Refused, never truncated or rounded: a register of seized money must keep the amount exactly.
- The custody signing log (`custody_log.py`, PR #139) reuses `_amount` and has its own 48-character check; both stay correct once both are merged.

## Next

1. Review and merge.

## Open questions

- none

## Files mid-change (do not touch)

- none
