# Handoff: custody-wallets

- **Feature**: suite feature 9 (custody wallet tooling): records of the unit's multisig custody wallets, a signing log for every movement in and out, and the officer's written procedure. The server never holds a key.
- **Issue**: #128
- **Branch**: `feat/custody-wallets` (then stacked `feat/custody-signing-log`, `feat/custody-screen`, `feat/custody-procedure`)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: all four parts open for review (#129, #139, #140, and the procedure doc); behind `EXCHEQUER_CUSTODY_WALLETS`, off

## Done

- Claimed: issue #128, this file, draft PR #129.
- Part 1 (#129): `backend/app/custody.py`, `backend/app/routes/custody.py` (`GET/POST /trace/{case_id}/custody`, `PATCH /custody/{wallet_id}`), model `CustodyWallet`, migration `g7_custody_1` (one table, `custody_wallets`), flag `EXCHEQUER_CUSTODY_WALLETS`. 40 tests in `backend/tests/test_custody.py`, including the migration going down and up.
- Part 2 (branch `feat/custody-signing-log`): `backend/app/custody_log.py`, routes `POST /custody/{wallet_id}/movements` and `POST /custody/movements/{movement_id}/{approve|broadcast|confirm|cancel}`, movements listed under each wallet in `GET /trace/{case_id}/custody`, model `CustodyMovement`, migration `g7_custody_2`. 29 tests in `backend/tests/test_custody_log.py` (#139).
- Part 3 (branch `feat/custody-screen`): `frontend/src/components/case/CustodyPanel.jsx` (+ `.css`, `.test.jsx`, 6 tests) on the Letters tab under the asset register (one import, one line in `LettersTab.jsx`); `frontend/src/api/custody.js` (one re-export line in `api.js`). The panel renders nothing unless the server says `enabled: true` (#140).
- Part 4 (branch `feat/custody-procedure`): `docs/custody-procedure.md`, the officer's checklist (two-person rule, hardware wallets held by named officers, test with a small amount, never photograph or type a seed, record every step, the court order before any release); suite-features row 9.

## Decisions

- Builds on the asset register (`assets.py`, #101): reuses its `looks_like_secret` check on every text field, its exact-decimal amounts and its transaction-hash check.
- Behind `EXCHEQUER_CUSTODY_WALLETS` (config.py FLAGS), off by default. Switched off, `GET /trace/{case_id}/custody` answers `enabled: false` (the screen hides itself) and every write is 403.
- A custody wallet needs a threshold of at least 2 and no more than its signers: one person alone must never move seized money.
- The panel sits on the Letters tab under the asset register (where #101 put the register), not on the Evidence tab: the wallet holds the register's custody rows.
- Signers are names, roles and units only, compared ignoring case and spacing, so the same person cannot be two of n. A seed split across a signer's fields is caught too.
- The chain, address, scheme, threshold and signers never change after the record is made; only notes and the linked asset-register rows do. A change of signers is a new record (see open questions).
- Linked asset-register rows must be in the same case, readable by the viewer, held in custody, and not recorded as held at another address (a blank `held_at` is allowed).
- One wallet per case per address; the same unit wallet may be recorded in several cases.
- Signing log: proposed -> approved (threshold distinct signers) -> broadcast (tx hash) -> confirmed, or cancelled with a reason from any step before confirmed. A release needs the court's order reference when proposed and must be approved before broadcast; a deposit goes to the wallet itself and may be broadcast without approvals (sending into a multisig needs no signatures).
- Who proposed a movement is chosen from the wallet's signers and stored by the name the wallet lists, so the rule that a proposer may not approve compares the same name. Where the scheme lets a proposer sign, the proposer must be a signer; where it does not, someone who is not a signer may propose (typed as "someone else"), and a signer may only if the other signers can still reach the threshold. A cancelled movement's card shows its reason.
- Every signing-log write needs a signed-in officer (not the demo identity); each approval records the signer (a listed name), the time and which officer entered it. One officer account enters at most one approval per movement (pre-review fix, 14 Nov): each signer records their own, signed in to their own account.
- One transaction hash is recorded once per live movement of a wallet, enforced by a partial unique index on (wallet_id, tx_hash) in `g7_custody_2` (movements not cancelled), so two racing broadcasts cannot both land; a cancelled movement's hash may be recorded again.
- A release is confirmed only while the wallet's confirmed releases of that asset stay within its confirmed deposits of it (assets compared ignoring case and spacing; exact decimals). Where amounts or asset spellings cannot be compared, it warns and does not refuse. Proposing a release beyond the deposits records it with a warning, which the panel shows. Deposits recorded only in the asset register, not as signing-log deposits, do not count.
- Audit detail is ids, step, status and approval count; never names, references or reasons.

## Next

1. Review and merge in order: #129, #139, #140, then the procedure PR.
2. Done 14 Nov: clicked through in Chrome against a local server with the flag on and two signed-in officers of one unit (wallet linked to a register row, deposit, release refused without the court's order, two approvals, broadcast, confirm, cancel; both themes, keyboard, axe on the panel). Four panel fixes went into `feat/custody-screen` (#140): stale signer after an approval, register rows added after load not offered, focus lost after a step, the deposit's approval count.
3. Turn the flag on (and later delete it) once the owner is happy; the procedure doc should be read by the unit before it is.

## Open questions

- Migration `g7_custody_1` revises `g7_domain_lookups_1` (main's head on 14 Nov). If #122 (`g7_tasks_1`) or #124 (`g7_tasks_2`) merge first, re-point its `down_revision` before merging.
- Signer rotation (replacing an owner of the same Safe) is not modelled: today it means a new record. Sidhyarth to decide whether that is enough.
- Should the officer entering an approval also have to be a different officer from the one who entered the proposal? Today one account may propose and enter one approval.

## Files mid-change (do not touch)

- none
