"""Tracing, and the case store it writes to.

POST /trace runs the pipeline and stores the result; GET /trace/{case_id}
reads a stored case back as it was when traced, never re-run. Its exports
are in evidence.py; the history list and correlation in casebook.py."""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .. import audit, config, models, ownership, pipeline, rate_limit
from ..auth import CurrentUser
from ..pipeline import TraceRequest


logger = logging.getLogger(__name__)
router = APIRouter()

# Traces in progress, server-wide; see config.TRACE_MAX_RUNNING.
_running = threading.BoundedSemaphore(config.TRACE_MAX_RUNNING)


def admit(http: Request) -> None:
    """Refuse a trace this client may not start now: over its hourly limit,
    or the server already running its maximum. On success the caller holds
    a running slot and must release it with `_running.release()`."""
    client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
    wait = rate_limit.traces.check(client)
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail=(
                f"This connection has started {config.TRACES_PER_HOUR_PER_CLIENT} traces "
                f"in the last hour. Try again in {int(wait // 60) + 1} min, or open a "
                "stored case in the meantime."
            ),
            headers={"Retry-After": str(int(wait))},
        )
    if not _running.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail=(
                f"{config.TRACE_MAX_RUNNING} traces are already running. "
                "Try again in a minute, or open a stored case in the meantime."
            ),
            headers={"Retry-After": "30"},
        )


def release() -> None:
    _running.release()


def store_result(payload: dict[str, Any], request: TraceRequest, owner: str | None) -> dict[str, Any]:
    """Give a finished trace its case id and, unless asked not to, store it."""
    case_id = models.new_case_id()
    created_at = models.utc_now_iso()
    payload["case_id"] = case_id
    payload["created_at"] = created_at
    if not request.save:
        payload["case_id"] = None
        return payload

    if owner and config.MAX_CASES_PER_OWNER and models.case_count_for(owner) >= config.MAX_CASES_PER_OWNER:
        payload["case_id"] = None
        payload.setdefault("warnings", []).append(
            f"This browser already keeps {config.MAX_CASES_PER_OWNER:,} cases, so this result is "
            "shown here but was not saved: export what you need from it now."
        )
        return payload

    stored = models.case_count() if config.MAX_STORED_CASES else 0
    if config.MAX_STORED_CASES and stored + 1 == int(config.MAX_STORED_CASES * 0.8):
        logger.warning("Case store is 80%% full (%d of %d cases)", stored + 1, config.MAX_STORED_CASES)
    if config.MAX_STORED_CASES and stored >= config.MAX_STORED_CASES:
        logger.warning("Case store full (%d cases); trace of %s not stored",
                       config.MAX_STORED_CASES, payload["address"])
        payload["case_id"] = None
        payload.setdefault("warnings", []).append(
            f"The case store is full ({config.MAX_STORED_CASES:,} cases), so this result is "
            "shown here but was not saved: it will not appear in the case history and "
            "cannot be exported or reopened later. Ask the operator to raise "
            "EXCHEQUER_MAX_STORED_CASES."
        )
        return payload

    try:
        models.save_case(case_id, payload["address"], payload, created_at=created_at,
                         owner_hash=owner or ownership.orphan_hash())
    except Exception:  # storage must never lose a completed trace
        logger.exception("Failed to persist case %s", case_id)
        # No id for a case that does not exist: the page would open it, find
        # nothing, and lose the result the officer just waited for.
        payload["case_id"] = None
        payload.setdefault("warnings", []).append(
            "Result could not be saved to the case database; it is shown here "
            "but will not appear in the case history."
        )
    return payload


def record_trace(payload: dict[str, Any]) -> None:
    """Audit a finished trace (CLAUDE.md rule 5): what kind of trace, not whose.

    No address and no NCRP number goes into the detail: until R24 the audit
    trail is a log line, and logs are no place for a complaint's particulars.
    """
    intake = payload.get("intake") or {}
    audit.record("case.trace", case_id=payload.get("case_id"), detail={
        "chain": payload.get("chain"),
        "asset": payload.get("asset"),
        "direction": payload.get("direction"),
        "mode": intake.get("mode", "address"),
        "payments": len(intake.get("payments") or []),
        "saved": bool(payload.get("case_id")),
        "exchange_reached": bool(payload.get("exchange")),
    })


@router.post("/trace")
def trace(request: TraceRequest, http: Request, user: CurrentUser) -> dict[str, Any]:
    """Trace funds to or from a reported address.

    Outgoing answers "where did the victim's money go"; incoming answers "who
    sent money to this address", which on a scammer's wallet enumerates the
    other people who paid it. The whole trace runs inside this request; the
    app itself uses POST /trace/jobs, which runs it in the background.
    """
    pipeline.check_request(request)
    admit(http)
    try:
        payload = pipeline.run_trace(request)
    finally:
        release()
    stored = store_result(payload, request, user.owner_hash)
    record_trace(stored)
    return stored


_INDEX_HTML = config.BACKEND_DIR.parent / "frontend" / "dist" / "index.html"


def _is_page_load(http: Request) -> bool:
    """A browser opening the URL, as opposed to the app's own fetch()."""
    mode = http.headers.get("sec-fetch-mode")
    if mode:
        return mode == "navigate"
    return "text/html" in http.headers.get("accept", "")


@router.get("/trace/intake")
def trace_intake() -> dict[str, Any]:
    """What the trace form may offer: whether a trace can start from the victim's
    payment hashes (R1, EXCHEQUER_TX_INTAKE), and how many of the reported
    wallet's incoming transfers are searched for them. Registered before
    /trace/{case_id}, which would otherwise read "intake" as a case id."""
    return {"payments": config.TX_INTAKE, "lookup_limit": config.TX_INTAKE_LOOKUP_LIMIT}


@router.get("/trace/{case_id}", response_model=None)
def get_trace(case_id: str, http: Request) -> JSONResponse | FileResponse:
    """Retrieve a previously traced case.

    /trace/<address> is also the app's own URL for a trace in progress, and
    the API claims the path first. A shared link or a reload of that page
    would get this endpoint's JSON 404; a browser navigation gets the app.

    The case is returned as a ready JSONResponse, rendered here in the worker
    thread: a plain dict would be walked by jsonable_encoder on the event
    loop, and a large case then stalled every other request."""
    if _is_page_load(http) and _INDEX_HTML.is_file():
        return FileResponse(_INDEX_HTML, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    return JSONResponse(case.result)
