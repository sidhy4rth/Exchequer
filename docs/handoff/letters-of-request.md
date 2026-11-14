# Handoff: letters-of-request

- **Feature**: suite feature 7 (request and letter generator): draft a letter of request to a foreign country (BNSS s.112) from a case, in the MHA's prescribed format
- **Issue**: #125
- **Branch**: `feat/letters-of-request` (server, #126); `feat/letters-of-request-screen` (screen, #127, on top of it); `feat/letters-of-request-countries` (Figure 3.6's treaty countries in the officer's notes, on top of #127)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: built and tested end to end; server in #126, screen in its own PR on top of it (`feat/letters-of-request-screen`); both wait for review

## Done

- Claimed (this file, draft PR #126).
- **Server.**
  - `backend/app/letters_of_request.py`: drafts the letter in Figure 3.5's sections and order. It reuses `request_letters.py`'s facts helpers: the payments, each hop, the claim about the address, the amount, and for a wallet the exchange runs only the transfers that can carry the traced funds.
  - Notes for the officer come first, marked to be removed: the MHA's route and the Figure 3.2 checklist.
  - `backend/data/mha_letter_of_request.txt`: the MHA's fixed wording (opening, both bases, assurances (a) to (e), limitation of use, confidentiality, closing), with its source.
  - `POST /trace/{case_id}/letter-of-request` in `backend/app/routes/letters_of_request.py` (one import, one `include_router` line in `main.py`). The details go in the body. Audit `case.letter_of_request_draft` with `{"basis": ...}` only.
  - 21 tests in `backend/tests/test_letters_of_request.py`. The full suite passes (3,266).
- **Screen.**
  - `frontend/src/components/case/LetterOfRequestPanel.jsx` (+ `.css`, `.test.jsx`) on the Letters tab, under the asset register. One import, one line in `LettersTab.jsx`; the line passes `offered`, so the panel shows only when the server offers this case an exchange or instant-exchanger letter.
  - `frontend/src/api/lettersOfRequest.js` (one re-export line in `api.js`).
  - 5 tests. All 1,611 frontend tests and the build pass.
- **End to end** in a browser against the real server, with recorded demo 11 saved as a case:
  - drafted with the country, court and reciprocity;
  - only the 2 transfers into Binance-Hot 7 that can carry the funds are named;
  - the audit row holds only the basis, and the server log hides the case id.
- Sources read:
  - **The format.** MHA, *Guidelines on Mutual Legal Assistance in Criminal Matters*, F. No. 25016/52/2019-LC, 4 December 2019. MHA's own copy refuses automated fetches (403), so I read the copy the J&K High Court circulated (https://jkhighcourt.nic.in/upload/notices/guidelines.pdf). That copy is a scan; I ran OCR on it and checked the pages used against the page images.
    - Figure 2.2: the steps.
    - Figures 3.1 to 3.4: the checklists.
    - Figure 3.5: the format and contents.
  - **BNSS s.112 = CrPC s.166A.** NCRB's BNSS–CrPC table (https://www.ncrb.mha.gov.in/uploads/SankalanPortal/SectionTableBNSS.html).

## Decisions

- The letter's wording is the MHA's wherever the MHA gives it: transcribed from the scanned guidelines, checked against the page images, kept as printed (including "I, ..., has been authorized" and "the Government (name of the Requested Country)"), and pinned by SHA-256 in the tests so any change is deliberate.
- Where the MHA's format says "to be filled by Investigating Agency/Court", the draft fills only what the case holds (the facts, the assistance asked for) and leaves the rest to the officer: the basis is never chosen for them, no offence or treaty is suggested, and limitation is a blank.
- Assurances (f) and (g) are left out, with a note saying when to add them: (f) is for a person whose attendance is requested, which this letter does not ask; (g) for an offence punishable with death.
- The panel is its own card on the Letters tab, not a third switch beside the letters and notices: it keeps `LettersTab.jsx`'s draft flow untouched (one import, one line).
- Follows `request_letters.py` and `notice_letters.py`: a draft, not valid until signed; every legal provision a marked blank with a bracketed suggestion; the officer's details in the body, never the URL; audit says which letter, never its details.

## Next

1. Barenyam (or anyone but Sidhyarth) checks `backend/data/mha_letter_of_request.txt` by eye against pages [20] to [24] of the guidelines PDF, and says so in the PR.
2. Later: Figure 3.6's list of MLAT countries (Central Authority, language), hand-checked, so the draft can say whether the country has a treaty with India; it is a 2019 list, so it needs the MHA's current one beside it.
3. Later: log a letter of request in the requests log (sent to the MHA for concurrence, issued, transmitted).

## Open questions

- Has the MHA revised these guidelines since the BNSS came into force? The draft follows the 2019 guidelines and says that they name CrPC s.166A. (Whoever finds a later MHA circular.)

## Files mid-change (do not touch)

- `backend/app/letters_of_request.py`, `backend/data/mha_mlat_countries.txt` (`feat/letters-of-request-countries`)
