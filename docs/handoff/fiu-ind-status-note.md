# Handoff: fiu-ind-status-note

- **Feature**: Feature 7 / feature 1 data: a dated, sourced FIU-IND note (registration as of 9 Mar 2026, enforcement actions, penalties) about the exchange a trace reached, on the report's FINDING and the exchange letters, behind `EXCHEQUER_FIU_IND_NOTE`
- **Issue**: #290
- **Branch**: `feat/fiu-ind-status-note`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: claimed; building

## Done

- Claimed (issue #290, draft PR).

## Decisions

- Separate data file, `backend/data/fiu_ind_status.json`, not a third status in `exchange_status.json`: closure and FIU-IND standing are independent (BitMEX is closed and was noticed; Coinbase was listed for takedown and is registered).

## Next

1. Data file, `app/fiu_ind_status.py`, the note in `report.py` FINDING and `request_letters.py`, tests, docs.

## Open questions

- none yet

## Files mid-change (do not touch)

- none
