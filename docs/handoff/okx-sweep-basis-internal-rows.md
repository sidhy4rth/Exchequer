# Handoff: okx-sweep-basis-internal-rows

- **Feature**: the `sweep_basis` of #277's 47 OKX Ethereum sweep-destination labels counts only rows that are still customer-deposit sweeps, after the label-store build's internal-wallet filter dropped OKX-funded rows
- **Issue**: #328
- **Branch**: `labels/okx-sweep-basis-internal-rows`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: claimed

## Done

- nothing yet

## Decisions

- The labels stay: each is on OKX's own PoR file (Non Staking) and the classification classes it exchange_wallet.

## Next

1. Amend each affected row's `sweep_basis` in `backend/data/exchange_labels.json` and `_meta.okx_sweep_destinations_2026_11_15`; add tests.

## Open questions

- none

## Files mid-change (do not touch)

- `backend/data/exchange_labels.json`: the 47 `sweep_basis` rows and `_meta.okx_sweep_destinations_2026_11_15`
