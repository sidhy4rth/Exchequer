# Handoff: sop-steps

- **Feature**: suite feature 8 (government platforms): on a case's Letters tab, the steps of the MHA SOP for NCRP-CFCFRMS, each quoted with its section and PDF page, beside what the case's own records show
- **Issue**: #326
- **Branch**: `feat/sop-steps`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16 (status after merge)
- **Status**: merged in #327 on 2026-11-16 (`272dc620`); behind `EXCHEQUER_SOP_STEPS` (off)

## Done

- `backend/app/sop_steps.py`: six steps (acknowledgement number 6.1(d)/6.2(c); submit to CFCFRMS 6.1(f); bank notices 6.1(g) and 6.1(k); FIR 6.1(i); exchange 9.4(ii)/(iv); grievance 10.1(e)/(f)). Beside each, what the case shows: whether a number of the usual NCRP shape is recorded (never which), how many bank holds the asset register still holds, which exchange the trace reached; else that the step is on the portal, which Exchequer cannot see.
- Routes in `backend/app/routes/sop_summary.py`: `GET /sop-steps` (offered or 404) and `GET /trace/{case_id}/sop-steps` (audited as `case.sop_steps_view`, no detail).
- `frontend/src/components/case/SopSteps.jsx` (+ `.css`, `.test.jsx`), mounted on the Letters tab; it reads the case only when opened.
- Tests: `backend/tests/test_sop_steps.py` (10), `SopSteps.test.jsx` (2).

## Decisions

- Quotes only, never applied; no notice is drafted, so the open question on a CFCFRMS notice draft (`government-platforms.md`) is untouched.
- The 6.1(k), 9.4 and 10.1 quotes are reused from `sop_reminders.py` and `sop_summary.py` (a test checks they stay identical). The new ones (6.1(d), (f), (g), (i), 6.2(c)) were checked on 16 Nov 2026 against the text of the bank-published copy (same SHA-256 as `sop_reminders.py` names); pages follow the 15 Nov render check (6.1(d) to (i) on page 12, 6.2 on page 13).
- No migration, no new stored field.

## Next

1. Owner: decide whether to turn the flag on (Render env `EXCHEQUER_SOP_STEPS=1`).

## Open questions

- none new

## Files mid-change (do not touch)

- none
