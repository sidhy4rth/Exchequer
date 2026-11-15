# Handoff: label-store exchange rows typed as deposit addresses, with their basis shown

- **Feature**: a trace that reaches an address an exchange's proof-of-reserves list holds, but that behaves as a customer's deposit address, is read as a probable deposit (the letter asks the exchange to name the customer), and the report and letter say what the attribution stands on
- **Issue**: #264
- **Branch**: `labels/deposit-rows-basis` (ADR + contract), then stacked: `labels/deposit-rows-store` (store + add script), `labels/deposit-rows-read` (matcher, scoring, report, letter)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: in progress; flag `EXCHEQUER_STORE_EXCHANGE_ROWS` stays off

## Done

- [ADR-0012](../adr/0012-deposit-rows-in-the-label-store.md), amending ADR-0011: a store exchange row may be typed
  `deposit_wallet` when it states its basis (`sweeps_to`, `sweep_tx`, `checked_on`); such a row reads as a probable
  deposit, never as the exchange's own wallet.
- Contract: `matches[].attribution_basis.deposit` (`docs/contracts/case.md`).

## Decisions

- A deposit row's match takes the inferred-deposit path (`wallet_type` `inferred_deposit`), scored lower (ADR-0004).
- `sweeps_to` must be a wallet the curated label file names as the same exchange's own wallet; a PoR listing alone
  is not enough.
- The basis is kept as raw bytes in its own optional table (`exchange_deposits`), not in `texts`, which the reader
  loads into memory.

## Next

1. Store + add script PR, then the read-side PR (see Branch).
2. Release agent: classify each PoR row before adding it (ADR-0012 (4)); re-classify OKX's 474,529 Tron rows.

## Open questions

- Owner: the flag must not be turned on with the `labels-2026-11-15` store, whose OKX Tron rows are all typed
  `exchange_wallet` from before ADR-0012.

## Files mid-change (do not touch)

- none
