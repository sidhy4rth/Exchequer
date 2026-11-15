"""Background traces: start one, watch it, collect the case.

    POST /trace/jobs                 start; 202 with the job id at once
    GET  /trace/jobs/{id}            status, progress and, when done, the result
    GET  /trace/jobs/{id}/events     the same as server-sent events, live

A job id works like a case id: whoever holds it can watch it. A job stopped
with DELETE stores nothing, even if its trace returns after the stop. With
EXCHEQUER_JOB_STOP_UNWATCHED on, neither does one no page has watched for
config.JOB_UNWATCHED_GRACE_SECONDS after its last progress stream closed. The finished
case is stored with the starting browser's owner key, as POST /trace does,
and its complaint particulars go only to that browser (case_privacy.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import api_budget, audit, case_privacy, case_refs, config, jobs, ownership, pipeline, progress
from ..auth import CurrentUser
from ..pipeline import TraceRequest
from . import cases

logger = logging.getLogger(__name__)
router = APIRouter()

HEARTBEAT_SECONDS = 15.0
POLL_SECONDS = 0.3


def _run(job: jobs.Job, request: TraceRequest, owner: str | None, slot: str | None = None,
         officer: tuple[int | None, int | None] = (None, None)) -> None:
    with audit.acting_as(owner, officer):  # this thread works for whoever started it
        _run_job(job, request, owner, slot, officer)


def _run_job(job: jobs.Job, request: TraceRequest, owner: str | None, slot: str | None,
             officer: tuple[int | None, int | None]) -> None:
    token = progress.listen(lambda fields: jobs.store.report(job, fields))
    try:
        with api_budget.using(job.budget):
            payload = pipeline.run_trace(request)
        if job.budget is not None and job.budget.cancelled:
            # It returned, but after a stop: a read refused by the stop may have
            # been skipped by a stage that went on without it (a block's date, a
            # tag), so the result cannot be taken as whole and is never stored.
            # It ends as a stop that raised does (POST /trace's hang-up rule).
            raise api_budget.Cancelled()
        jobs.store.report(job, {"stage": "saving"})
        # From here the trace is done and its provider calls are spent: a
        # failure to store or audit it is a warning on the result, never "failed".
        try:
            stored = cases.store_result(payload, request, owner, client=slot, officer=officer)
        except Exception:  # noqa: BLE001
            logger.exception("Trace job %s finished but could not be stored", job.id)
            stored = {**payload, "case_id": None}
            stored.setdefault("warnings", []).append(
                "Result could not be saved to the case database; it is shown here "
                "but will not appear in the case history.")
        cases.record_trace_safely(stored)
        jobs.store.finish(job, result=stored)
    except Exception as exc:  # noqa: BLE001 -- a job must always end, and say how
        if job.abandoned:
            # Stopped because no page watched it (EXCHEQUER_JOB_STOP_UNWATCHED):
            # whatever the stop surfaced as, it ends as POST /trace's hang-up
            # does, audited as abandoned, and nothing of it is kept.
            cases.record_abandoned(request)
            jobs.store.finish(job, error={"status_code": 409, "detail": cases.ABANDONED_DETAIL})
        else:
            jobs.store.finish(job, error=_job_error(job, exc))
    finally:
        progress.stop(token)
        cases.release(slot)


def _job_error(job: jobs.Job, exc: Exception) -> dict[str, Any]:
    """How a job that raised ends: the error its snapshot shows."""
    if isinstance(exc, HTTPException):
        return {"status_code": exc.status_code, "detail": exc.detail}
    if isinstance(exc, api_budget.Cancelled):
        return {"status_code": 409, "detail": "The trace was stopped by the person who started it."}
    if isinstance(exc, api_budget.TraceStopped):
        return {"status_code": 503, "detail": f"The trace stopped at its {exc.reason}."}
    logger.error("Trace job %s failed", job.id, exc_info=exc)
    return {"status_code": 500, "detail": "The trace failed unexpectedly. Try again."}


@router.post("/trace/jobs", status_code=202)
def start_job(request: TraceRequest, http: Request, user: CurrentUser) -> JSONResponse:
    request.case_ref = case_refs.required(user, request.case_ref)
    pipeline.check_request(request)  # a typo is refused before it costs the allowance
    slot = cases.admit(http, user)  # holds a running slot from here until _run releases it
    try:
        owner = user.owner_hash
        # The admit() token: this connection's share of the day's provider allowance.
        job = jobs.store.create(owner=owner, budget=api_budget.TraceBudget.for_request(
            request.time_budget_seconds, client=slot))
        cases.record_start(request)
        threading.Thread(target=_run, args=(job, request, owner, slot, (user.officer_id, user.unit_id)),
                         name=f"trace-job-{job.id[:8]}", daemon=True).start()
    except Exception:
        cases.release(slot)
        raise
    return JSONResponse(status_code=202, content={
        **job.snapshot(),
        "status_url": f"/trace/jobs/{job.id}",
        "events_url": f"/trace/jobs/{job.id}/events",
    })


@router.delete("/trace/jobs/{job_id}", status_code=202)
def stop_job(job_id: str, user: CurrentUser) -> dict[str, Any]:
    """Stop a running trace: only the browser that started it may. The trace
    ends at its next provider request or backoff, and its slot is freed."""
    job = _job_or_404(job_id)
    if user.owner_hash is None or user.owner_hash != job.owner:
        raise HTTPException(status_code=403, detail="Only the browser that started this trace can stop it.")
    running = job.status == jobs.RUNNING
    if running and job.budget is not None:
        job.budget.cancel()
    # Ids only, as case.trace_start: the job id and whether there was a trace to stop.
    audit.record("case.trace_stopped", detail={"job_id": job.id, "was_running": running})
    return {"job_id": job.id, "stopping": job.status == jobs.RUNNING}


def _job_or_404(job_id: str) -> jobs.Job:
    job = jobs.store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=("No such trace job (a finished job is kept for 30 minutes, "
                                                     "or 5 if its result was not saved)."))
    return job


@router.get("/trace/jobs/{job_id}")
def job_status(job_id: str, http: Request) -> dict[str, Any]:
    job = _job_or_404(job_id)
    if job.unwatched_since is not None:
        job.unwatched_since = _clock()  # a page polling is a page watching
    snapshot = job.snapshot(with_result=True)
    if snapshot.get("result"):
        caller = ownership.owner_hash_from_headers(http.headers)
        snapshot["result"] = case_privacy.for_reader(snapshot["result"], job.owner, caller)
    return snapshot


# Every open stream wakes every POLL_SECONDS on the one event loop, so a job
# takes only a few at once (a tab, a reload, a second screen). A stream ends
# after STREAM_MAX_SECONDS and the browser's EventSource reconnects by itself;
# that lifetime also clears entries left by connections that dropped without
# closing their stream. Job id -> {stream token: opened at (monotonic)}.
MAX_STREAMS_PER_JOB = 3
STREAM_MAX_SECONDS = 900.0
_streams: dict[str, dict[str, float]] = {}


def _open_stream(job_id: str) -> str:
    now = time.monotonic()
    open_ = {t: at for t, at in _streams.get(job_id, {}).items() if now - at < STREAM_MAX_SECONDS}
    if len(open_) >= MAX_STREAMS_PER_JOB:
        _streams[job_id] = open_
        raise HTTPException(status_code=429, headers={"Retry-After": "5"},
                            detail="This trace already has as many progress streams as it allows.")
    token = uuid.uuid4().hex
    open_[token] = now
    _streams[job_id] = open_
    return token


def _close_stream(job_id: str, token: str) -> None:
    open_ = _streams.get(job_id)
    if open_ is not None:
        open_.pop(token, None)
        if not open_:
            _streams.pop(job_id, None)


# EXCHEQUER_JOB_STOP_UNWATCHED: a job whose page has gone (tab closed) used to
# run to the end and save a case nobody saw; only a Stop (DELETE) ended it.
# Once a job's last progress stream closes, a clock starts; a stream opening
# or a status poll (the page's fallback asks every 1.5 s) resets it, and a job
# still unwatched after config.JOB_UNWATCHED_GRACE_SECONDS is stopped as a Stop
# stops it. A job whose client never opened a stream (a script that polls, or
# one that only waits) never starts the clock, so it runs as before.
_clock = time.monotonic


def _schedule(delay: float, callback) -> None:
    """Run `callback` on the event loop after `delay` seconds (tests replace this)."""
    try:
        asyncio.get_running_loop().call_later(delay, callback)
    except RuntimeError:  # no loop (a stream closed outside one): the job runs on, as before
        pass


def _watched(job_id: str) -> bool:
    now = time.monotonic()
    return any(now - at < STREAM_MAX_SECONDS for at in _streams.get(job_id, {}).values())


def _unwatched(job: jobs.Job) -> None:
    """The job's last stream has just closed: start its clock."""
    if not config.JOB_STOP_UNWATCHED or job.status != jobs.RUNNING or job.budget is None:
        return
    job.unwatched_since = _clock()
    _schedule(config.JOB_UNWATCHED_GRACE_SECONDS, lambda: _stop_if_unwatched(job))


def _stop_if_unwatched(job: jobs.Job) -> None:
    if job.status != jobs.RUNNING or job.budget.cancelled or job.unwatched_since is None or _watched(job.id):
        return  # finished, stopped, or watched again (its next close starts a new clock)
    left = config.JOB_UNWATCHED_GRACE_SECONDS - (_clock() - job.unwatched_since)
    if left > 0:  # a poll reset the clock
        _schedule(left, lambda: _stop_if_unwatched(job))
        return
    job.abandoned = True  # before the cancel, so the job's thread ends it as abandoned
    job.budget.cancel(cases.CLIENT_DISCONNECTED)


@router.get("/trace/jobs/{job_id}/events")
async def job_events(job_id: str, http: Request) -> StreamingResponse:
    job = _job_or_404(job_id)
    token = _open_stream(job_id)

    async def stream():
        last_version = -1
        quiet = 0.0
        opened = time.monotonic()
        try:
            # Tell the browser how soon to reconnect if the stream drops.
            yield "retry: 2000\n\n"
            while True:
                if job.version != last_version:
                    last_version = job.version
                    quiet = 0.0
                    yield f"event: progress\ndata: {json.dumps(job.snapshot())}\n\n"
                if job.status != jobs.RUNNING:
                    yield f"event: {job.status}\ndata: {json.dumps(job.snapshot())}\n\n"
                    return
                if await http.is_disconnected() or time.monotonic() - opened >= STREAM_MAX_SECONDS:
                    return
                await asyncio.sleep(POLL_SECONDS)
                quiet += POLL_SECONDS
                if quiet >= HEARTBEAT_SECONDS:
                    quiet = 0.0
                    # A named event, not a comment: it keeps proxies from
                    # closing an idle stream, and it reaches the page, whose
                    # watchdog then knows the stream is alive.
                    yield "event: heartbeat\ndata: {}\n\n"
        finally:
            _close_stream(job_id, token)
            if not _watched(job_id):
                _unwatched(job)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
