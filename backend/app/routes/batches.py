"""Bulk intake: trace a list of complaints and look across them (batches.py).

    POST /batches          {name, rows: [{address, chain, asset, direction, depth, reference}]}
    GET  /batches          this browser's batches
    GET  /batches/{id}     rows, progress, the exchanges reached and shared wallets

The browser parses the CSV and sends JSON, so the server never parses an
upload.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import audit, batches, config, ownership, pipeline, rate_limit
from . import casebook, cases

logger = logging.getLogger(__name__)
router = APIRouter()


class BatchRequest(BaseModel):
    name: str = Field("", max_length=120)
    rows: list[dict[str, Any]] = Field(..., max_length=batches.MAX_ROWS * 4)


def _owner(http: Request) -> str:
    owner = ownership.owner_hash_from_headers(http.headers)
    if owner is None:
        raise HTTPException(status_code=400, detail="This browser sent no owner key, so it cannot run a batch.")
    return owner


# Batch rows run in the batch slots first, then in a server trace slot: the
# batch slots are what keep batches from taking every trace slot.
_batch_slots = threading.BoundedSemaphore(batches.BATCH_SLOTS)
# Active (running or waiting) batches: batch id -> owner.
_active: dict[str, str] = {}
_active_lock = threading.Lock()


def _acquire() -> bool:
    if not _batch_slots.acquire(blocking=False):
        return False
    if cases._running.acquire(blocking=False):
        return True
    _batch_slots.release()
    return False


def _release() -> None:
    cases.release()
    _batch_slots.release()


def _refund(client: str, rows: int) -> None:
    if rows > 0:
        rate_limit.traces.refund(client, rows)
        rate_limit.traces_total.refund(rate_limit.TOTAL, rows)


def _admit_batch(owner: str) -> None:
    with _active_lock:
        _admit_batch_locked(owner)


def _admit_batch_locked(owner: str) -> None:
    """Refuse a second active batch from this browser, or one over the site's
    ceiling. Called with _active_lock held."""
    if owner in _active.values():
        raise HTTPException(status_code=429, headers={"Retry-After": "60"},
                            detail="This browser already has a batch running. Wait for it to finish.")
    if len(_active) >= batches.MAX_ACTIVE_BATCHES:
        raise HTTPException(status_code=429, headers={"Retry-After": "60"},
                            detail=f"This site is already running {batches.MAX_ACTIVE_BATCHES} batches. "
                                   "Try again later.")


@router.post("/batches", status_code=202)
def start_batch(body: BatchRequest, http: Request) -> JSONResponse:
    owner = _owner(http)
    _admit_batch(owner)
    try:
        rows = batches.validate_rows(body.rows)
    except batches.BatchError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc), "row_errors": exc.row_errors})
    client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
    refused = rate_limit.charge(rate_limit.traces, rate_limit.traces_total, client, cost=len(rows))
    if refused is not None:
        wait, who = refused
        if who == "site":
            left = rate_limit.traces_total.remaining(rate_limit.TOTAL)
            detail = (f"This batch needs {len(rows)} traces and this site can start {left} more "
                      f"this hour (limit {config.TRACES_PER_HOUR_TOTAL}). Send fewer rows, or wait.")
        else:
            left = rate_limit.traces.remaining(client)
            detail = (f"This batch needs {len(rows)} traces and this connection can start {left} more "
                      f"this hour (limit {config.TRACES_PER_HOUR_PER_CLIENT}). Send fewer rows, or wait.")
        raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(int(wait))})
    charged = len(rows)
    with _active_lock:
        try:
            _admit_batch_locked(owner)  # again: another request may have started one meanwhile
            batch = batches.create(owner, body.name, rows)
        except Exception:
            _refund(client, charged)
            raise
        _active[batch.id] = owner
    audit.record("batch.create", detail={"rows": len(rows)})

    # Rows that never reach a trace (the store failed, the batch was stopped)
    # are given back to the hourly allowance when the batch ends.
    traced = [0]

    def trace(request):
        traced[0] += 1
        return pipeline.run_trace(request)

    def done(batch_id: str = batch.id) -> None:
        with _active_lock:
            _active.pop(batch_id, None)
        _refund(client, charged - traced[0])

    def record(payload: dict[str, Any]) -> None:
        cases.record_trace(payload, via="batch")
    try:
        batches.start(batch.id, owner, _acquire, _release, trace, cases.store_result, on_done=done,
                      record_fn=record)
    except Exception as exc:  # noqa: BLE001 -- e.g. "can't start new thread" under memory pressure
        logger.error("Batch %s could not be started: %s", batch.id, type(exc).__name__)
        batches.fail(batch.id, "The batch could not be started. Send it again in a minute.")
        done()
        raise HTTPException(status_code=503, headers={"Retry-After": "60"},
                            detail="The server could not start this batch right now. Try again in a minute.") from exc
    return JSONResponse(status_code=202, content=batches.summary(batch))


@router.get("/batches")
def list_batches(http: Request) -> dict[str, Any]:
    owner = ownership.owner_hash_from_headers(http.headers)
    items = batches.list_for(owner) if owner else []
    return {"count": len(items), "batches": items}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, http: Request) -> dict[str, Any]:
    batch = batches.get(_owner(http), batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="No such batch.")
    return batches.summary(batch, with_correlation=True, excluded=casebook._known_contract_or_exchange)
