# Handoff: custody-wallets

- **Feature**: suite feature 9 (custody wallet tooling): records of the unit's multisig custody wallets, a signing log for every movement in and out, and the officer's written procedure. The server never holds a key.
- **Issue**: #128
- **Branch**: `feat/custody-wallets` (then stacked `feat/custody-signing-log`, `feat/custody-screen`, `feat/custody-procedure`)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: claimed; part 1 (server records) in progress

## Done

- Claimed: issue #128, this file, draft PR.

## Decisions

- Builds on the asset register (`assets.py`, #101): reuses its `looks_like_secret` check on every text field, its exact-decimal amounts and its transaction-hash check.
- Behind `EXCHEQUER_CUSTODY_WALLETS` (config.py FLAGS), off by default.

## Next

1. Part 1: `backend/app/custody.py`, `backend/app/routes/custody.py`, model `CustodyWallet`, migration `g7_custody_1`, `backend/tests/test_custody.py`.

## Open questions

- none yet

## Files mid-change (do not touch)

- none
