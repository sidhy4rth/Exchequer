# Handoff: asset-register

- **Feature**: suite feature 9 (custody wallet tooling): a register of every amount frozen or seized in a case, where it is held, and its court deadline
- **Issue**: #100
- **Branch**: `feat/asset-register`
- **Current**: nobody
- **Last worked on**: Barenyam, 2026-11-12
- **Status**: merged in #101 (12 Nov 2026) and live; part 2 below is open

## The nine features (see `docs/suite-features.md`)

1 Attribution data (Sidhyarth, #91) · 2 Mobile and computer forensics · 3 Memory and disk tools · 4 OSINT · 5 Telecom and bank analysis · 6 Case management and evidence locker · 7 Request and letter generator (bank and telecom notices merged in #99) · 8 Government platforms · **9 Custody wallet tooling (Barenyam, this file)**. Unnamed ones are unclaimed.

## Done

- Read `freeze_requests.py`: a request already records status "frozen" with `amount_frozen` and `asset`. An asset row can point at the request that froze it (`request_id`) instead of copying it.

- Server: `backend/app/assets.py`, `backend/app/routes/assets.py` (`GET/POST /trace/{case_id}/assets`, `PATCH /assets/{asset_id}`, `GET /assets/due?days=7`), model `SeizedAsset`, migration `g7_assets_1` (one table, `seized_assets`), `backend/data/bip39_english.txt`. 34 tests in `backend/tests/test_assets.py`, including the migration going down and up.
- Screens: `frontend/src/components/case/AssetsPanel.jsx` (+ `.css`, `.test.jsx`) under the requests log on the Letters tab; `frontend/src/components/AssetDeadlines.jsx` on the home page (one import, one line in `Home.jsx`; one import, one line in `LettersTab.jsx`). 8 tests; all 1,516 frontend tests and the build pass.
- End to end in a browser against the real server: a request marked Frozen added in one click; a seed phrase refused; a custody row refused without its transaction, then added; the home page listed the due row and dropped it once the court's order was recorded.

## Decisions

- Never store a private key, seed phrase or extended key. Free-text fields refuse text shaped like one; key holders are names only.
- Amounts are kept as exact decimal text, not floats: a register of seized funds must not drift by rounding.
- The register is a panel on the Letters tab, under the requests log, not a sixth case tab: `CaseTabs.test.jsx` and `caseTab.test.jsx` pin the five tabs, and the panel sits where a freeze turns into held money.
- Seed phrases are caught as twelve BIP39 words in a row (the official 2,048-word list), not as any twelve short words: ordinary sentences have runs of short words.
- The court deadline is 45 days from the seizure date (BNSS s.497 as read by the Karnataka High Court in Mukesh Jain); shown as a count of days, the source named in the UI.

## Next

1. Record one asset on the live site and check the home card.
2. Later: a "custody wallet" check that reads the custody address's balance on chain and flags a mismatch with the register (feature 9, part 2).

## Open questions

- The home-page card is one import and one line in `Home.jsx` (platform's page): Sidhyarth to confirm its place.

## Files mid-change (do not touch)

- none yet
