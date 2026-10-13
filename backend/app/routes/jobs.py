"""Background traces: start one, watch it, collect the case.

    POST /trace/jobs                 start; 202 with the job id at once
    GET  /trace/jobs/{id}            status, progress and, when done, the result
    GET  /trace/jobs/{id}/events     the same as server-sent events, live

A job id works like a case id: whoever holds it can watch it. The finished
case is stored with the starting browser's owner key, as POST /trace does.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import jobs, ownership, pipeline, progress
from ..pipeline import TraceRequest
from . import cases

logger = logging.getLogger(__name__)
router = APIRouter()

HEARTBEAT_SECONDS = 15.0
POLL_SECONDS = 0.3


def _run(job: jobs.Job, request: TraceRequest, owner: str | None) -> None:
    token = progress.listen(lambda fields: jobs.store.report(job, fields))
    try:
        payload = pipeline.run_trace(request)
        jobs.store.report(job, {"stage": "saving"})
        jobs.store.finish(job, result=cases.store_result(payload, request, owner))
    except HTTPException as exc:
        jobs.store.finish(job, error={"status_code": exc.status_code, "detail": exc.detail})
    except Exception:  # noqa: BLE001 -- a job must always end, and say how
        logger.exception("Trace job %s failed", job.id)
        jobs.store.finish(job, error={"status_code": 500,
                                      "detail": "The trace failed unexpectedly. Try again."})
    finally:
        progress.stop(token)
        cases.release()


@router.post("/trace/jobs", status_code=202)
def start_job(request: TraceRequest, http: Request) -> JSONResponse:
    cases.admit(http)  # holds a running slot from here until _run releases it
    try:
        job = jobs.store.create()
        owner = ownership.owner_hash_from_headers(http.headers)
        threading.Thread(target=_run, args=(job, request, owner),
                         name=f"trace-job-{job.id[:8]}", daemon=True).start()
    except Exception:
        cases.release()
        raise
    return JSONResponse(status_code=202, content={
        **job.snapshot(),
        "status_url": f"/trace/jobs/{job.id}",
        "events_url": f"/trace/jobs/{job.id}/events",
    })


def _job_or_404(job_id: str) -> jobs.Job:
    job = jobs.store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such trace job (finished jobs are kept for 30 minutes).")
    return job


@router.get("/trace/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    return _job_or_404(job_id).snapshot(with_result=True)


@router.get("/trace/jobs/{job_id}/events")
async def job_events(job_id: str, http: Request) -> StreamingResponse:
    job = _job_or_404(job_id)

    async def stream():
        last_version = -1
        quiet = 0.0
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
            if await http.is_disconnected():
                return
            await asyncio.sleep(POLL_SECONDS)
            quiet += POLL_SECONDS
            if quiet >= HEARTBEAT_SECONDS:
                quiet = 0.0
                yield ": still tracing\n\n"  # keeps proxies from closing an idle stream

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
