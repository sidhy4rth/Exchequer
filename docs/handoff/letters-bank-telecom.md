# Handoff: letters-bank-telecom

- **Feature**: suite feature 7 (request and letter generator): draft notices to a bank and to a telecom operator, next to the exchange and Tether letters
- **Issue**: #98
- **Branch**: `feat/letters-bank-telecom`
- **Current**: Barenyam
- **Last worked on**: Barenyam, 2026-11-12
- **Status**: PR A (server side) done and pushed; PR B (the form in the Letters tab) next

## The nine features (see `docs/suite-features.md`)

1 Attribution data (Sidhyarth, #91) · 2 Mobile and computer forensics · 3 Memory and disk tools · 4 OSINT · 5 Telecom and bank analysis · 6 Case management and evidence locker · **7 Request and letter generator (Barenyam, this file)** · 8 Government platforms · 9 Custody wallet tooling. Unnamed ones are unclaimed.

## Done

- Read `backend/app/request_letters.py`: exchange, Tether and instant-exchanger letters; urgent freeze letters first; every legal provision a marked blank with a bracketed suggestion; every draft "not valid until an officer signs it"; freeze letters wait for a second officer's approval.
- PR A, server side (#99):
  - `backend/app/notice_letters.py`: three notices, `bank-info`, `bank-freeze` (urgent) and `telecom`, built from the same header, freeze header and sign-off helpers as `request_letters.py`.
  - `POST /trace/{case_id}/notice` in `backend/app/routes/evidence.py`: the officer's details in the body; the file is named by case and notice; the audit row is `case.notice_draft` with `{"to": ...}` only.
  - `freeze_requests.KINDS` gains the three, so each can be logged as sent; `bank-freeze` needs a sign-off because it ends in `-freeze`.
  - `backend/tests/test_notice_letters.py`: 26 tests. Full backend suite and ruff pass, except `test_signing.py::test_unwritable_key_path_falls_back_to_a_marked_temporary_key`, which fails on unchanged `main` too when run as root (a root process can write the "unwritable" path); CI does not run as root.

## Decisions

- Bank and telecom notices follow the same rules as the existing letters. Their facts come only from what the officer enters (account number, IFSC, phone number, the exchange's reply reference) or what the case already holds; nothing is guessed.
- Foreign letters of request (BNSS s.112) are out of scope here.
- A bank hold is refused without the Magistrate's order (number, date, court): freezing an account is an attachment, and the High Courts have held s.106 does not allow it (see the suite report's legal section).
- The officer's details are not stored yet: the notice is drafted from the request body and returned. Storing them waits for feature 5 (the importer), which will produce the same details.
- New kinds are named `bank-info`, `bank-freeze`, `telecom`, not `bank`: `test_freeze_requests.py::test_bad_input` uses "bank" as its example of an unknown kind.

## Next

1. PR B, the form: in `frontend/src/components/case/LettersTab.jsx`, add a "Bank or telecom notice" section with the fields for each notice (bank, account, IFSC, period, source; order and amount for the hold; operator and phone for telecom), POST to `/trace/{id}/notice` (add the call to the right file in `frontend/src/api/`, per CLAUDE.md rule 4), and show the draft like the other letters. Tests next to `LettersTab.test.jsx`.
2. Add `bank-info`, `bank-freeze`, `telecom` to `KINDS` in `frontend/src/components/case/letterChecks.js` (it mirrors `freeze_requests.KINDS`) so the requests log names them.
3. When #97 is merged, mark feature 7's status in `docs/suite-features.md`.

## Open questions

- Does feature 5's importer later fill these details automatically? If so, agree the shape with whoever takes feature 5.

## Files mid-change (do not touch)

- none yet
