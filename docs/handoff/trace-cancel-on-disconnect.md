# Handoff: trace-cancel-on-disconnect

- **Feature**: a synchronous POST /trace whose client hangs up stops at its next provider request instead of running to the end
- **Issue**: #225
- **Branch**: `feat/trace-cancel-on-disconnect`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: done behind `EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT` (off); in review

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

1. Owner: decide whether to set `EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT=1` on Render. Before relying on it, confirm on the live site that Render's proxy closes the upstream connection when the client goes away (start a trace with curl, kill curl, look for `case.trace_abandoned` in the audit log).

## Open questions

- Whether a stopped job (DELETE /trace/jobs/{id}) should get the same "returned after a stop is never stored" guard; today it can store a result whose late reads were skipped. Not changed here.

## Files mid-change (do not touch)

- none
