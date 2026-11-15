# Handoff: verify-fiu-and-page2-lede

- **Feature**: /verify checks PDFs with the FIU-IND note on, and PDFs whose privacy lede is on page 2
- **Issue**: #305
- **Branch**: `tests/verify-fiu-and-page2-lede`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: merged in #306 on 2026-11-15 (18:57 UTC, `c33327a0`); live

## Done

- `backend/tests/test_verify_fiu_and_privacy_pages.py`: flag-on Kraken and Binance PDFs verify genuine with
  pages matching; each FIU-IND source URL is whole on one printed line; an FIU-IND line put on page 1 reads
  `summary_differs`; one altered in Part 2 reads `printed_copy_differs`.
- The same file: a privacy section pushed onto page 2. A PDF issued with an earlier lede (report generated
  before its cut-off) read `summary_differs` ("Page 2 draws something Exchequer's page does not"), because
  `pdf_verify._issued` searched only page 1 for the lede. Fixed: `_issued` now searches the summary pages'
  text (`_compare` returns it). The cut-off rule and the three known ledes are unchanged, and tested on page 2.

## Decisions

- Page 1 does not print the FIU-IND note (it is only in the signed FINDING and Part 2), so the tests check
  that an FIU-IND line added to page 1 is caught, not that one is altered there.

## Next

1. Nothing.

## Open questions

- Whether the FIU-IND note should appear on page 1 is review question 2 on #193 (owner's call).

## Files mid-change (do not touch)

- none
