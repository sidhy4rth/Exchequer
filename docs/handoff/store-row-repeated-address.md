# Handoff: store-row-repeated-address

- **Feature**: the label-store add script handles an address its CSV lists more than once (ADR-0012 deposit rows)
- **Issue**: #273
- **Branch**: `fix/store-row-repeated-address`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: PR open, ready; flag `EXCHEQUER_STORE_EXCHANGE_ROWS` stays off

## Done

- `backend/scripts/add_store_exchange_rows.py` `add`: an address repeated with the same type is one row, the
  later one (what `INSERT OR REPLACE` already kept); before, two deposit rows for one address stopped the run with
  `sqlite3.IntegrityError`. An address listed both as an own wallet and as a deposit is left out, every row of it,
  with "repeated: ..." in `<csv>.left_out.tsv`; before, the later row won, so the store's reading of it hung on
  row order.
- `backend/tests/test_store_deposit_rows.py`: two tests (three cases) that fail on main without the fix.

## Decisions

- Two deposit rows for one address with different sweeps are not a conflict: the later basis is kept.

## Next

1. Merge once CI is green.

## Open questions

- none

## Files mid-change (do not touch)

- none
