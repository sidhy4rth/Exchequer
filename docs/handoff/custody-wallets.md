# Handoff: custody-wallets

- **Feature**: suite feature 9 (custody wallet tooling): records of the unit's multisig custody wallets, a signing log for every movement in and out, and the officer's written procedure. The server never holds a key.
- **Issue**: #128
- **Branch**: `feat/custody-wallets` (then stacked `feat/custody-signing-log`, `feat/custody-screen`, `feat/custody-procedure`)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: part 1 (#129) and part 2 (signing log) ready for review; part 3 (screen) next

## Done

- Claimed: issue #128, this file, draft PR #129.
- Part 1 (#129): `backend/app/custody.py`, `backend/app/routes/custody.py` (`GET/POST /trace/{case_id}/custody`, `PATCH /custody/{wallet_id}`), model `CustodyWallet`, migration `g7_custody_1` (one table, `custody_wallets`), flag `EXCHEQUER_CUSTODY_WALLETS`. 40 tests in `backend/tests/test_custody.py`, including the migration going down and up.
- Part 2 (branch `feat/custody-signing-log`): `backend/app/custody_log.py`, routes `POST /custody/{wallet_id}/movements` and `POST /custody/movements/{movement_id}/{approve|broadcast|confirm|cancel}`, movements listed under each wallet in `GET /trace/{case_id}/custody`, model `CustodyMovement`, migration `g7_custody_2`. 29 tests in `backend/tests/test_custody_log.py`.

## Decisions

- Builds on the asset register (`assets.py`, #101): reuses its `looks_like_secret` check on every text field, its exact-decimal amounts and its transaction-hash check.
- Behind `EXCHEQUER_CUSTODY_WALLETS` (config.py FLAGS), off by default. Switched off, `GET /trace/{case_id}/custody` answers `enabled: false` (the screen hides itself) and every write is 403.
- A custody wallet needs a threshold of at least 2 and no more than its signers: one person alone must never move seized money.
- Signers are names, roles and units only, compared ignoring case and spacing, so the same person cannot be two of n. A seed split across a signer's fields is caught too.
- The chain, address, scheme, threshold and signers never change after the record is made; only notes and the linked asset-register rows do. A change of signers is a new record (see open questions).
- Linked asset-register rows must be in the same case, readable by the viewer, held in custody, and not recorded as held at another address (a blank `held_at` is allowed).
- One wallet per case per address; the same unit wallet may be recorded in several cases.
- Signing log: proposed -> approved (threshold distinct signers) -> broadcast (tx hash) -> confirmed, or cancelled with a reason from any step before confirmed. A release needs the court's order reference when proposed and must be approved before broadcast; a deposit goes to the wallet itself and may be broadcast without approvals (sending into a multisig needs no signatures).
- Every signing-log write needs a signed-in officer (not the demo identity); each approval records the signer (a listed name), the time and which officer entered it. One officer may enter several signers' approvals (the signing happens on the signers' own devices); see open questions.
- One transaction hash is recorded once per wallet. Audit detail is ids, step, status and approval count; never names, references or reasons.

## Next

1. Part 3: the panel on the Letters tab under the asset register, `frontend/src/api/custody.js`.
2. Part 4: `docs/custody-procedure.md` and suite-features row 9.

## Open questions

- Migration `g7_custody_1` revises `g7_domain_lookups_1` (main's head on 14 Nov). If #122 (`g7_tasks_1`) or #126 merge first with their own migrations, re-point its `down_revision` before merging.
- Signer rotation (replacing an owner of the same Safe) is not modelled: today it means a new record. Sidhyarth to decide whether that is enough.
- Should the officer entering an approval have to be a different officer from the one who proposed it (a server-side two-person rule on the record itself)? Today any signed-in officer of the unit can enter any step.

## Files mid-change (do not touch)

- none
