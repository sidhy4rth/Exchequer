# Handoff: contract-wallet-roles

- **Feature**: a deposit address that sweeps into an exchange's contract-held hot wallet is read as a deposit, because that contract wallet's role is measured on chain and recorded
- **Issue**: #253
- **Branch**: `labels/contract-wallet-roles`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: in progress

## Done

- Claimed.

## Decisions

- A role comes only from a source or a keyless on-chain measurement (the #248 method), never a guess.

## Next

1. `backend/scripts/measure_contract_wallet_roles.py --record`, then set the measured roles.

## Open questions

- none yet

## Files mid-change (do not touch)

- `backend/data/exchange_labels*.json`: roles being added
