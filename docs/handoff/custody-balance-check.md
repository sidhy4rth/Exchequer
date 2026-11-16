# Handoff: custody-balance-check

- **Feature**: suite feature 9, part 2: read each custody address's balance on chain and flag where it differs from what the asset register records
- **Issue**: #332
- **Branch**: `feat/custody-balance-check` (then stacked `feat/custody-balance-panel`)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: claimed; server PR in progress

## Done

- Claimed: issue #332, this file, a draft PR.

## Decisions

- Behind a new flag `EXCHEQUER_CUSTODY_BALANCE_CHECK` (config.py FLAGS), off by default.

## Next

1. Server: `backend/app/custody_balance.py`, routes in `backend/app/routes/custody.py`, a table for each check run, tests with fake provider clients.
2. Panel: show each result on the Letters tab under the asset register, in words, not colour only.

## Open questions

- none yet

## Files mid-change (do not touch)

- none yet
