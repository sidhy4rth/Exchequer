# Handoff: okx-tron-own-wallets

- **Feature**: OKX Tron deposit addresses that sweep into an OKX wallet other than Hot Wallet 8 can get an ADR-0012 deposit row, because OKX's own Tron wallets from its proof-of-reserves list are labelled
- **Issue**: #298
- **Branch**: `labels/okx-tron-own-wallets`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: in progress

## Done

- Claimed.

## Decisions

- Only wallets OKX's own PoR file lists, and that keyless on-chain reads show to be OKX's own operating wallets by recorded rules, are labelled. Deposit-like addresses are left out.

## Next

1. Record the classification and add the rows to `backend/data/exchange_labels_tron.json`.

## Open questions

- none

## Files mid-change (do not touch)

- none
