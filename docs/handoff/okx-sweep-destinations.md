# Handoff: okx-sweep-destinations

- **Feature**: the OKX Ethereum deposit addresses that sweep only into OKX proof-of-reserves wallets the label file did not name can get a deposit row, because those destination wallets are labelled
- **Issue**: #276
- **Branch**: `labels/okx-sweep-destinations`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: in progress

## Done

- nothing yet

## Decisions

- Only wallets OKX's own PoR file lists (Non Staking) and the release's on-chain classification (`okx_por_ethereum_classified.csv`) classes `exchange_wallet` are labelled.

## Next

1. Add the passing destinations to `backend/data/exchange_labels.json` with `scripts.import_por_labels` functions.

## Open questions

- none

## Files mid-change (do not touch)

- `backend/data/exchange_labels.json`
