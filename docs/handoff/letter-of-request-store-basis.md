# Handoff: letter-of-request-store-basis

- **Feature**: the letter of request (feature 7) prints what a label-store exchange row's attribution stands on, in the report's words
- **Issue**: #348
- **Branch**: `feat/lor-deposit-basis`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: claimed; behind `EXCHEQUER_STORE_EXCHANGE_ROWS` (off), since only a store row carries the field

## Done

- Claimed (this file, draft PR).

## Decisions

- Same lines as the report and the exchange letter (`report.basis_lines`), no new wording.

## Next

1. `backend/app/letters_of_request.py`: print `report.basis_lines(report.store_basis(trace), exchange)` after the claim in the Statement of Facts; nothing when the field is absent.

## Open questions

- none

## Files mid-change (do not touch)

- `backend/app/letters_of_request.py`: the basis lines
