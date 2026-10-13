"""Bulk intake: trace a list of complaints and look across them (batches.py).

    POST /batches          {name, rows: [{address, chain, asset, direction, depth, reference}]}
    GET  /batches          this browser's batches
    GET  /batches/{id}     rows, progress, the exchanges reached and shared wallets

The browser parses the CSV and sends JSON, so the server never parses an
upload.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import batches, config, ownership, pipeline, rate_limit
from . import cases

router = APIRouter()


class BatchRequest(BaseModel):
    name: str = Field("", max_length=120)
    rows: list[dict[str, Any]] = Field(..., max_length=batches.MAX_ROWS * 4)


def _owner(http: Request) -> str:
    owner = ownership.owner_hash_from_headers(http.headers)
    if owner is None:
        raise HTTPException(status_code=400, detail="This browser sent no owner key, so it cannot run a batch.")
    return owner


def _acquire() -> bool:
    return cases._running.acquire(blocking=False)


@router.post("/batches", status_code=202)
def start_batch(body: BatchRequest, http: Request) -> JSONResponse:
    owner = _owner(http)
    try:
        rows = batches.validate_rows(body.rows)
    except batches.BatchError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc), "row_errors": exc.row_errors})
    client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
    wait = rate_limit.traces.check(client, cost=len(rows))
    if wait is not None:
        left = rate_limit.traces.remaining(client)
        raise HTTPException(
            status_code=429,
            detail=(f"This batch needs {len(rows)} traces and this connection can start {left} more "
                    f"this hour (limit {config.TRACES_PER_HOUR_PER_CLIENT}). Send fewer rows, or wait."),
            headers={"Retry-After": str(int(wait))},
        )
    batch = batches.create(owner, body.name, rows)
    batches.start(batch.id, owner, _acquire, cases.release, pipeline.run_trace, cases.store_result)
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
    return batches.summary(batch, with_correlation=True, excluded=cases._known_contract_or_exchange)
