# Handoff: custody-wallets

- **Feature**: suite feature 9 (custody wallet tooling): records of the unit's multisig custody wallets, a signing log for every movement in and out, and the officer's written procedure. The server never holds a key.
- **Issue**: #128
- **Branch**: `feat/custody-wallets` (then stacked `feat/custody-signing-log`, `feat/custody-screen`, `feat/custody-procedure`)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: part 1 (server records, #129) ready for review; part 2 (signing log) next

## Done

- Claimed: issue #128, this file, draft PR #129.
- Part 1 (#129): `backend/app/custody.py`, `backend/app/routes/custody.py` (`GET/POST /trace/{case_id}/custody`, `PATCH /custody/{wallet_id}`), model `CustodyWallet`, migration `g7_custody_1` (one table, `custody_wallets`), flag `EXCHEQUER_CUSTODY_WALLETS`. 40 tests in `backend/tests/test_custody.py`, including the migration going down and up.

## Decisions

- Builds on the asset register (`assets.py`, #101): reuses its `looks_like_secret` check on every text field, its exact-decimal amounts and its transaction-hash check.
- Behind `EXCHEQUER_CUSTODY_WALLETS` (config.py FLAGS), off by default. Switched off, `GET /trace/{case_id}/custody` answers `enabled: false` (the screen hides itself) and every write is 403.
- A custody wallet needs a threshold of at least 2 and no more than its signers: one person alone must never move seized money.
- Signers are names, roles and units only, compared ignoring case and spacing, so the same person cannot be two of n. A seed split across a signer's fields is caught too.
- The chain, address, scheme, threshold and signers never change after the record is made; only notes and the linked asset-register rows do. A change of signers is a new record (see open questions).
- Linked asset-register rows must be in the same case, readable by the viewer, and held in custody.
- One wallet per case per address; the same unit wallet may be recorded in several cases.

## Next

1. Part 2 (branch `feat/custody-signing-log`, stacked on part 1): the signing log, model `CustodyMovement`, migration `g7_custody_2`.
2. Part 3: the panel on the Letters tab under the asset register, `frontend/src/api/custody.js`.
3. Part 4: `docs/custody-procedure.md` and suite-features row 9.

## Open questions

- Migration `g7_custody_1` revises `g7_domain_lookups_1` (main's head on 14 Nov). If #122 (`g7_tasks_1`) or #126 merge first with their own migrations, re-point its `down_revision` before merging.
- Signer rotation (replacing an owner of the same Safe) is not modelled: today it means a new record. Sidhyarth to decide whether that is enough.

## Files mid-change (do not touch)

- none
