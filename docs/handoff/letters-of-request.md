# Handoff: letters-of-request

- **Feature**: suite feature 7 (request and letter generator): draft a letter of request to a foreign country (BNSS s.112) from a case, in the MHA's prescribed format
- **Issue**: #125; #352 (Figure 3.6's Central Authorities and language rules, and the MHA's current treaty list)
- **Branch**: `feat/letters-of-request` (server, #126); `feat/letters-of-request-screen` (screen, #127, on top of it); `feat/letters-of-request-countries` (Figure 3.6's treaty countries in the officer's notes, #130, on top of #127); `feat/letters-of-request-log` (logged in the requests log, #136, on top of #130); `feat/letters-of-request-followup` (a longer follow-up wait for letters of request, on top of #136); `feat/letters-of-request-fig36` (#352, data only)
- **Current**: Sidhyarth (#352)
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: merged in #126 (with #127, #130, #136 and #158) on 2026-11-15; live, no flag

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

- **Treaty countries (#130).**
  - `backend/data/mha_mlat_countries.txt`: Figure 3.6 of the same guidelines, pages [25] to [28] (PDF pages 27 to 30), 42 rows, OCR'd and then read row by row from the page images; cross-checked against Figure 1.1 on page [4]. Three rows are marked signed but not yet in force (Cambodia, Maldives, Morocco). Pinned by SHA-256 in `backend/tests/test_mlat_countries.py`.
  - The officer's notes (never the letter) say whether the list names the country typed (exact name or formal name, case and spacing ignored, no fuzzy match), or that it is not on the list under that name and reciprocity may be the route; nothing when no country is given. The basis is never changed.
- **Requests log (#136).**
  - `freeze_requests.KINDS` gains `letter-rogatory` (15 characters: fits the 16-character kind column, so no migration); `letters_of_request.REQUEST_KIND` names it. No sign-off (not a `-freeze` kind).
  - The panel, after a draft, has "Log it in the requests log": recipient = the requested country, status drafted; the requests log above remounts and shows it with a "Letter of request" pill. The existing requests screen could only log the letters it suggests or "other", hence the button.
  - Its statuses are drafted, sent, acknowledged, declined, closed (`freeze_requests.KIND_STATUSES`, `statuses_for`): never "frozen" (it asks the requested country for help and freezes nothing itself), never the sign-off states. Each row carries `statuses`; the requests panel offers only those.
  - Logged once per case and country while open (drafted, sent, acknowledged), for the same browser: logging it again (after a reload) answers 200 with the open row and `already_logged: true`, audited as `request.create_existing`; the panel says it was not logged twice. Declined or closed, a new one may be logged. Not enforced by a database constraint, so two clicks landing at the same instant could still make two rows.
- **Follow-up wait (on top of #136).**
  - A sent request is flagged for follow-up after 7 days (`FOLLOW_UP_DAYS`), and #124 turns that flag into a "Follow up" task. A letter of request goes through the MHA and a foreign Central Authority and takes months, so 7 days was noise.
  - `freeze_requests.follow_up_days(kind)`: 30 days for `letter-rogatory` (`FOLLOW_UP_DAYS_BY_KIND`), 7 for every other kind. 30 days is an internal reminder interval the team chose, not a legal or MHA deadline.
  - Only the `follow_up` flag in `summary` changed, so the change stays clear of `feat/signoff-binding` (#133). The screens and #124 read the flag the server sends; neither has a 7-day number of its own.

## Decisions

- The letter's wording is the MHA's wherever the MHA gives it: transcribed from the scanned guidelines, checked against the page images, kept as printed (including "I, ..., has been authorized" and "the Government (name of the Requested Country)"), and pinned by SHA-256 in the tests so any change is deliberate.
- Where the MHA's format says "to be filled by Investigating Agency/Court", the draft fills only what the case holds (the facts, the assistance asked for) and leaves the rest to the officer: the basis is never chosen for them, no offence or treaty is suggested, and limitation is a blank.
- Assurances (f) and (g) are left out, with a note saying when to add them: (f) is for a person whose attendance is requested, which this letter does not ask; (g) for an offence punishable with death.
- The panel is its own card on the Letters tab, not a third switch beside the letters and notices: it keeps `LettersTab.jsx`'s draft flow untouched (one import, one line).
- Follows `request_letters.py` and `notice_letters.py`: a draft, not valid until signed; every legal provision a marked blank with a bracketed suggestion; the officer's details in the body, never the URL; audit says which letter, never its details.

## Next

1. Barenyam (or anyone but Sidhyarth) checks `backend/data/mha_letter_of_request.txt` by eye against pages [20] to [24] of the guidelines PDF, and says so in the PR.
2. Barenyam checks `backend/data/mha_mlat_countries.txt` by eye against pages [25] to [28] the same way (#130).
3. Later: the MHA's current treaty list beside the 2019 one; Figure 3.6's Central Authorities and language requirements are not transcribed.
4. If the team wants a different reminder for letters of request, change `FOLLOW_UP_DAYS_BY_KIND` in `freeze_requests.py` (see "Follow-up wait" above).

## Open questions

- Has the MHA revised these guidelines since the BNSS came into force? The draft follows the 2019 guidelines and says that they name CrPC s.166A. (Whoever finds a later MHA circular.)

## Files mid-change (do not touch)

- `backend/data/mha_mlat_central_authorities.txt`, `backend/data/mha_mlat_portal_countries.txt` (new), `backend/app/letters_of_request.py`, `backend/tests/test_mlat_countries.py` (#352)
