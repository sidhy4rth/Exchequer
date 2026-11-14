# Handoff: government platforms (feature 8)

- **Feature**: work alongside NCRP, the 1930 helpline and CFCFRMS without any access to them: check an NCRP number's usual shape, and give the officer a crypto summary in the SOP's own terms to enter or attach on CFCFRMS
- **Issue**: #214
- **Branch**: `feat/ncrp-number-check` (PR 1), `feat/cfcfrms-crypto-summary` (PR 2, stacked)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: PR 1 (NCRP number shape note) in review

## Done

- PR 1: one rule for the usual shape of an NCRP acknowledgement number, 14 digits starting with 2 (portal) or 3 (1930), from the MHA SOP for NCRP-CFCFRMS 6.1(d) and 6.2(c). A soft note only; nothing that was accepted before is refused. `backend/app/ncrp.py` (the officers' complaint page gets `ncrp_note`), `frontend/src/ncrp.js` (New trace), `citizen/src/api.js` `ncrpNote` (complaint pack and My case).

## Decisions

- Warn, never refuse: older complaints or other channels may use other formats, and nothing published rules them out.
- The note is a fixed sentence and never repeats the number, so it can travel without the number reaching a log or the audit trail.

## Next

1. PR 2: the CFCFRMS crypto summary (SOP 9.4), behind `EXCHEQUER_SOP_SUMMARY`.

## Open questions

- None yet for PR 1.

## Files mid-change (do not touch)

- none
