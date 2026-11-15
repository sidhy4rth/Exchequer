# Handoff: job-stop-when-unwatched

- **Feature**: a background trace job whose page has gone (tab closed) stops after a grace period instead of running to the end and saving a case nobody saw
- **Issue**: #302
- **Branch**: `feat/job-stop-when-unwatched`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: PR #303 ready for review, behind `EXCHEQUER_JOB_STOP_UNWATCHED` (off)

## Done

- `config.py`: flag `EXCHEQUER_JOB_STOP_UNWATCHED` (FLAGS) and `JOB_UNWATCHED_GRACE_SECONDS = 30.0` (trace engine section).
- `jobs.py`: `Job.unwatched_since` (monotonic, None until the first stream closes) and `Job.abandoned`.
- `routes/jobs.py`: when a job's last progress stream closes, `_unwatched` starts the clock and `_schedule` sets a timer on the event loop (`call_later`). `_stop_if_unwatched` does nothing if the job finished, was stopped, or has a stream open again; if a status poll moved the clock it sets a new timer for what is left; otherwise it sets `abandoned` and cancels the budget with `client_disconnected`. `GET /trace/jobs/{id}` moves the clock (only once it has started). `_run_job` ends an abandoned job, whatever the stop surfaced as, with `cases.record_abandoned` and 409 `cases.ABANDONED_DETAIL`; nothing stored. The other endings moved unchanged into `_job_error`.
- Tests: `backend/tests/test_job_unwatched.py` (fake clock and fake timer; one test uses the real loop timer with a 0.2 s grace). `tests/test_jobs.py` unchanged and green.
- Docs: `docs/flag-rollout.md` section and table row; a note under the table in `docs/suite-features.md`.

## Decisions

- Its own flag, not `EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT` (on in production): switching this on is a separate choice.
- The clock starts only after a first stream has connected and closed, so a client that never opens a stream (a script that only polls or waits) is never stopped. A status poll counts as watching, so the page's polling fallback keeps its job.
- No refund of the hourly trace allowance, as for a Stop and a hung-up POST /trace: the trace was started and its provider calls spent, and a refund would let a client start and close traces to get round the limit.
- Audited as `case.trace_abandoned` (the existing record, `stopped_by: client_disconnected`, `saved: false`), not `case.trace_stopped`, which stays the Stop button's.
- A cancel that lands after the job's post-trace check (it is already saving) does not undo the save: the result is whole.

## Next

1. Owner: review and merge #303; then decide whether to switch it on, using the checks in `docs/flag-rollout.md` (section `EXCHEQUER_JOB_STOP_UNWATCHED`).

## Open questions

- A phone that sleeps with the tab open drops its stream and loses its trace after 30 s (the page shows the 409 on waking, as after a Stop). Owner: acceptable, or a longer grace?

## Files mid-change (do not touch)

- none
