# Handoff: letters-bank-telecom

- **Feature**: suite feature 7 (request and letter generator): draft notices to a bank and to a telecom operator, next to the exchange and Tether letters
- **Issue**: #98
- **Branch**: `feat/letters-bank-telecom`
- **Current**: nobody
- **Last worked on**: Barenyam, 2026-11-12
- **Status**: merged in #99 (12 Nov 2026) and deployed with it; the later parts below are open

## The nine features (see `docs/suite-features.md`)

1 Attribution data (Sidhyarth, #91) · 2 Mobile and computer forensics · 3 Memory and disk tools · 4 OSINT · 5 Telecom and bank analysis · 6 Case management and evidence locker · **7 Request and letter generator (Barenyam, this file)** · 8 Government platforms · 9 Custody wallet tooling. Unnamed ones are unclaimed.

## Done

- Read `backend/app/request_letters.py`: exchange, Tether and instant-exchanger letters; urgent freeze letters first; every legal provision a marked blank with a bracketed suggestion; every draft "not valid until an officer signs it"; freeze letters wait for a second officer's approval.
- PR A, server side (#99):
  - `backend/app/notice_letters.py`: three notices, `bank-info`, `bank-freeze` (urgent) and `telecom`, built from the same header, freeze header and sign-off helpers as `request_letters.py`.
  - `POST /trace/{case_id}/notice` in `backend/app/routes/evidence.py`: the officer's details in the body; the file is named by case and notice; the audit row is `case.notice_draft` with `{"to": ...}` only.
  - `freeze_requests.KINDS` gains the three, so each can be logged as sent; `bank-freeze` needs a sign-off because it ends in `-freeze`.
  - `backend/tests/test_notice_letters.py`: 31 tests, including the whole two-officer flow (Asha logs a bank hold and asks for sign-off; she cannot sign it; Bina does; the draft then names her) and logging the information notices as sent. Full backend suite and ruff pass, except `test_signing.py::test_unwritable_key_path_falls_back_to_a_marked_temporary_key`, which fails on unchanged `main` too when run as root (a root process can write the "unwritable" path); CI does not run as root.

## Decisions

- Bank and telecom notices follow the same rules as the existing letters. Their facts come only from what the officer enters (account number, IFSC, phone number, the exchange's reply reference) or what the case already holds; nothing is guessed.
- Foreign letters of request (BNSS s.112) are out of scope here.
- A bank hold is refused without the Magistrate's order (number, date, court): freezing an account is an attachment, and the High Courts have held s.106 does not allow it (see the suite report's legal section).
- The officer's details are not stored yet: the notice is drafted from the request body and returned. Storing them waits for feature 5 (the importer), which will produce the same details.
- New kinds are named `bank-info`, `bank-freeze`, `telecom`, not `bank`: `test_freeze_requests.py::test_bad_input` uses "bank" as its example of an unknown kind.

## Next

1. Open a stored case's Letters tab on the live site and draft one of each notice.
2. When #97 is merged, mark feature 7's status in `docs/suite-features.md`.
3. Later parts of feature 7: foreign letters of request (BNSS s.112); saving notice details once feature 5's importer exists.

- The form (`frontend/src/components/case/NoticeForm.jsx`, `.css`, `.test.jsx`), in the Letters tab:
  - A second switch, "Notice to: Bank · Phone company", beside the letter switch, on stored cases only (a recorded example has no case to draft from). It is its own group so the letter switch still shows exactly the backend's letters.
  - Bank: Information / Urgent hold; bank, account, IFSC, source, then the period (information) or the Magistrate's order and an optional amount (hold). Phone company: operator, number, source, period. Ticks when an IFSC, account or mobile number looks right.
  - Nothing is drafted until the officer presses Draft the letter; changing a detail or the kind asks for a fresh draft. The draft, blanks, checks, sign-off and Mark as sent are the tab's own.
  - `draftNotice` in `frontend/src/api/evidence.js` (POST, details in the body). `letterChecks.js`: the three kinds; a notice has no address or asset in the requests log; the recipient is the bank or operator the officer typed.
  - Tests: 10 in `NoticeForm.test.jsx`; all 1,494 frontend tests and the build pass.
- End-to-end in a real browser against the real server (demo 11 stored as a case): bank letter drafted and logged as sent; hold refused without an order, then drafted and held for sign-off; phone letter drafted; no number in any URL; no browser errors apart from the deliberate refusal.
- Rupees in the hold are written the Indian way: INR 2,50,000.00.
- Cross-check (2026-11-12): amounts accept "2,50,000"; True, nan, inf and words are refused; README lists the new route.

## Open questions

- Any signed-in officer holding a case's id can draft its notices, as they can its exchange letters today (`case_privacy.py`: "holding it opens the case", so a recipient can follow a letter's reference back to the evidence). Should drafting letters and notices be limited to the case's own unit? A cross-cutting question for Sidhyarth (an ADR if we change it), not part of this feature.

- Does feature 5's importer later fill these details automatically? If so, agree the shape with whoever takes feature 5.

## Files mid-change (do not touch)

- none yet
