# Handoff: trace-cancel-on-disconnect

- **Feature**: a synchronous POST /trace whose client hangs up stops at its next provider request instead of running to the end
- **Issue**: #225
- **Branch**: `feat/trace-cancel-on-disconnect`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15 (live-site findings added)
- **Status**: merged in #227 (with #228) on 2026-11-15, behind `EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT`; on since 22:46 IST on 15 Nov 2026 (Render deploy `dep-dbsugv61egvs73eto9a0`), recorded in `render.yaml` by #296. It reaches only direct `POST /trace` callers: the web app traces with `POST /trace/jobs` (`frontend/src/api/trace.js` `runTrace`), which the flag does not touch

## Done

- `routes/cases.py`: `HangupWatch` and the `hangup_watch` dependency on POST /trace. With the flag on, a task on the event loop polls `http.is_disconnected()` every `HANGUP_POLL_SECONDS` (1 s) while the trace runs; on a hang-up it cancels the trace's budget with reason `client_disconnected`. With the flag off the dependency yields None and starts nothing.
- A trace stopped this way is never stored (save true or false), even if it returned after the hang-up; the route answers 409 and audits `case.trace_abandoned` with `stopped_by: client_disconnected`, `saved: false`.
- `api_budget.TraceBudget.cancel(reason)`: `stopped_by` records the reason ("cancel" stays the default for DELETE /trace/jobs/{id}).
- `config.py` FLAGS: `EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT`.
- Tests: `backend/tests/test_trace_hangup.py` (fake provider, raw ASGI http.disconnect mid-trace).

## Decisions

- No contract change: a stopped trace produces no case, so `stopped_by` in the result keeps its two values ("time", "budget"). `client_disconnected` lives on the budget and in the audit detail.
- Only POST /trace is watched. POST /trace/jobs and batches run in the background by design and are untouched.
- A trace that returns after a hang-up is discarded too: some reads swallow a stop and their stage goes on without them, so the result cannot be taken as whole.

## Next

1. Done 15 Nov: the Render-logs checks in `docs/flag-rollout.md` (flag off, `--http1.1` and `--http2`; then flag on, `--http2`), and the owner switched it on. HTTP/1.1 was not re-run with the flag on.
2. A background job whose tab was closed still runs to the end and saves a case while its own flag is off (nothing sends DELETE on unload, and `job_events` only frees its stream). The design (stop a job once no progress stream or status poll has watched it for a grace period; nothing saved) is built, in #302/#303 (merged 15 Nov), behind its own flag `EXCHEQUER_JOB_STOP_UNWATCHED` (off in `render.yaml`) with a 120 s grace (`JOB_UNWATCHED_GRACE_SECONDS`), not behind this flag. See its section in `docs/flag-rollout.md`.

## Measured on the live site (15 Nov 2026, flag off)

Details and numbers in `docs/flag-rollout.md`. On the progress stream `GET /trace/jobs/{id}/events` (3 open streams per job, a 4th gets 429 until a place frees), an HTTP/2 client's hang-up freed the place within about 0.1 s with no writes in between; an HTTP/1.1 client's hang-up freed it only just after the next progress write (2.3–5.9 s, 3 rounds). Neither Render nor Cloudflare documents this. Inference: the flag likely works for browsers (HTTP/2 or 3) and likely does nothing for HTTP/1.1 scripts such as `check_demos.py`, because `POST /trace` writes nothing until the trace ends. Not measured: the `POST /trace` phase before any byte is written.

## Open questions

- none. Answered by `fix/stopped-job-no-save` (stacked on this branch): a job stopped with DELETE /trace/jobs/{id} whose trace still returns is never stored either. `routes/jobs.py` checks the budget after `run_trace` and ends the job as any stop ends (failed, 409, "stopped by the person who started it"), no case saved. Not behind a flag: jobs are live on main, and the change is only that guard. Tests in `tests/test_jobs.py`.

## Files mid-change (do not touch)

- none
