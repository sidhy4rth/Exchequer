# Handoff: letters-bank-telecom

- **Feature**: suite feature 7 (request and letter generator): draft notices to a bank and to a telecom operator, next to the exchange and Tether letters
- **Issue**: #98
- **Branch**: `feat/letters-bank-telecom`
- **Current**: Barenyam
- **Last worked on**: Barenyam, 2026-11-12
- **Status**: claimed; plan being written, no code yet

## The nine features (see `docs/suite-features.md`)

1 Attribution data (Sidhyarth, #91) · 2 Mobile and computer forensics · 3 Memory and disk tools · 4 OSINT · 5 Telecom and bank analysis · 6 Case management and evidence locker · **7 Request and letter generator (Barenyam, this file)** · 8 Government platforms · 9 Custody wallet tooling. Unnamed ones are unclaimed.

## Done

- Read `backend/app/request_letters.py`: exchange, Tether and instant-exchanger letters; urgent freeze letters first; every legal provision a marked blank with a bracketed suggestion; every draft "not valid until an officer signs it"; freeze letters wait for a second officer's approval.

## Decisions

- Bank and telecom notices follow the same rules as the existing letters. Their facts come only from what the officer enters (account number, IFSC, phone number, the exchange's reply reference) or what the case already holds; nothing is guessed.
- Foreign letters of request (BNSS s.112) are out of scope here.

## Next

1. Read how letters reach the user (`backend/app/routes/`, the frontend letter view, `freeze_requests.py`) and write the plan: files, where officer-entered bank and phone details are stored, tests. Show it before any code.

## Open questions

- Where do the officer-entered bank and phone details live: on the freeze-request row, or a new table? (affects a migration)
- Does feature 5's importer later fill these details automatically? If so, agree the shape with whoever takes feature 5.

## Files mid-change (do not touch)

- none yet
