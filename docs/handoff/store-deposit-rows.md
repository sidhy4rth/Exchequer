# Handoff: label-store exchange rows typed as deposit addresses, with their basis shown

- **Feature**: a trace that reaches an address an exchange's proof-of-reserves list holds, but that behaves as a customer's deposit address, is read as a probable deposit (the letter asks the exchange to name the customer), and the report and letter say what the attribution stands on
- **Issue**: #264
- **Branch**: `labels/deposit-rows-basis` (ADR + contract), then stacked: `labels/deposit-rows-store` (store + add script), `labels/deposit-rows-read` (matcher, scoring, report, letter)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: three stacked PRs open for review; flag `EXCHEQUER_STORE_EXCHANGE_ROWS` stays off

## Done

- [ADR-0012](../adr/0012-deposit-rows-in-the-label-store.md), amending ADR-0011: a store exchange row may be typed
  `deposit_wallet` when it states its basis (`sweeps_to`, `sweep_tx`, `checked_on`); such a row reads as a probable
  deposit, never as the exchange's own wallet.
- Contract: `matches[].attribution_basis.deposit` (`docs/contracts/case.md`).
- Store + add script (PR 2 of 3): `add_store_exchange_rows.py` takes `deposit_wallet` rows with `sweeps_to`,
  `sweep_tx`, `checked_on` (refuses the CSV without them; leaves out a row whose `sweeps_to` is not a label-file
  wallet of the same exchange, or an own-wallet row stating a sweep); basis in table `exchange_deposits`;
  `LabelStore.exchange_row` returns it as `basis.deposit`. Tests: `backend/tests/test_store_deposit_rows.py`.
- Read side (PR 3 of 3): `ExchangeMatcher.annotate` turns a deposit row into an `inferred_deposit` match
  (`_listed_deposit`); scoring explains it; the report's FINDING and the exchange letter print the basis of any
  store row (`report.store_basis`, `report.basis_lines`). Tests: `backend/tests/test_store_deposit_trace.py`
  (deposit row -> letter asks for the customer; own-wallet row unchanged; flag off -> result, report and letter
  byte-identical to a trace with no store).

## Decisions

- A deposit row's match takes the inferred-deposit path (`wallet_type` `inferred_deposit`), scored lower (ADR-0004).
- `sweeps_to` must be a wallet the curated label file names as the same exchange's own wallet; a PoR listing alone
  is not enough.
- The basis is kept as raw bytes in its own optional table (`exchange_deposits`), not in `texts`, which the reader
  loads into memory.

## Next

1. Release agent: classify each PoR row before adding it (ADR-0012 (4)); re-classify OKX's 474,529 Tron rows.
   CSV columns: the ten of ADR-0011 plus `sweeps_to`, `sweep_tx`, `checked_on` (blank on own-wallet rows).
2. Not done here: the letter of request (`letters_of_request.py`) and the UI do not print the basis yet; the
   letter of request already words a deposit row as an inferred deposit (it reads `attribution_kind`).
3. Turning the flag on (separate PR): needs a store built under ADR-0012 and the demo re-record (ADR-0011).

## Open questions

- Owner: the flag must not be turned on with the `labels-2026-11-15` store, whose OKX Tron rows are all typed
  `exchange_wallet` from before ADR-0012.

## Files mid-change (do not touch)

- none
