# Handoff: job-stop-when-unwatched

- **Feature**: a background trace job whose page has gone (tab closed) stops after a grace period instead of running to the end and saving a case nobody saw
- **Issue**: #302
- **Branch**: `feat/job-stop-when-unwatched`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: in progress, behind `EXCHEQUER_JOB_STOP_UNWATCHED` (off)

## Done

- claimed

## Decisions

- pending

## Next

1. `backend/app/routes/jobs.py`: start a grace clock when a job's last progress stream closes; cancel the job when it runs out.

## Open questions

- none yet

## Files mid-change (do not touch)

- `backend/app/routes/jobs.py`, `backend/app/jobs.py`
