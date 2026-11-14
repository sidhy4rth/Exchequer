# Handoff: letters-of-request

- **Feature**: suite feature 7 (request and letter generator): draft a letter of request to a foreign country (BNSS s.112) from a case, in the MHA's prescribed format
- **Issue**: #125
- **Branch**: `feat/letters-of-request`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: claimed; server being built

## Done

- Claimed (this file, draft PR).
- Sources read:
  - **The format.** MHA, *Guidelines on Mutual Legal Assistance in Criminal Matters*, F. No. 25016/52/2019-LC, 4 December 2019. MHA's own copy refuses automated fetches (403), so I read the copy the J&K High Court circulated (https://jkhighcourt.nic.in/upload/notices/guidelines.pdf). That copy is a scan; I ran OCR on it and checked the pages used against the page images.
    - Figure 2.2: the steps.
    - Figures 3.1 to 3.4: the checklists.
    - Figure 3.5: the format and contents.
  - **BNSS s.112 = CrPC s.166A.** NCRB's BNSS–CrPC table (https://www.ncrb.mha.gov.in/uploads/SankalanPortal/SectionTableBNSS.html).

## Decisions

- Follows `request_letters.py` and `notice_letters.py`: a draft, not valid until signed; every legal provision a marked blank with a bracketed suggestion; the officer's details in the body, never the URL; audit says which letter, never its details.

## Next

1. Server: `backend/app/letters_of_request.py`, the MHA's fixed wording in `backend/data/mha_letter_of_request.txt`, a route, tests.
2. Screen: a form on the Letters tab.

## Open questions

- none yet

## Files mid-change (do not touch)

- none yet
