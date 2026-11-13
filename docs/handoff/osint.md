# Handoff: osint

- **Feature**: Suite feature 4. Record what the victim reported besides the wallet (scam domain, Telegram handle, phone number, UPI ID), look up public facts about a domain, and link the same identifier across cases.
- **Issue**: #104
- **Branch**: `feat/osint`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-13
- **Status**: Claimed. The plan goes to Sidhyarth before any code is written.

## Done

- Claim: this file and a draft PR.

## Decisions

- The slices follow the issue: (1) a per-case identifier register, (2) domain lookup over fixed RDAP and DNS endpoints, (3) links across cases.
- Results go in their own tables, never inside a trace result, so `docs/contracts/case.md` is not touched.
- Live lookups stay behind a flag (rule 6) until the whole slice is ready.

## Next

1. Wait for #103 (exhibit register) to merge, then put the first migration after `g7_exhibits_1`.
2. Slice 1: `backend/app/identifiers.py` + `backend/app/routes/identifiers.py` + model + migration + panel, following `assets.py` and `exhibits.py`.

## Open questions

- How long are phone numbers and handles kept? (Team decides before any export.)
- Where the panel is mounted: the Evidence tab is busy with #103 until it merges.

## Files mid-change (do not touch)

- none
