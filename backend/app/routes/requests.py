"""Freeze and information requests logged against cases (freeze_requests.py).

    GET    /requests                     this browser's requests (?open=true)
    GET    /trace/{case_id}/requests     this browser's requests for one case
    POST   /requests                     log one
    PATCH  /requests/{id}                change status, reference, notes, amount
    DELETE /requests/{id}
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import audit, freeze_requests, rate_limit
from ..auth import CurrentUser, User

router = APIRouter()


class NewRequest(BaseModel):
    case_id: str = Field(..., max_length=36)
    recipient: str = Field(..., max_length=120)
    kind: str = Field("exchange", max_length=16)
    address: str = Field("", max_length=64)
    asset: str = Field("", max_length=16)
    status: str = Field("drafted", max_length=16)


class RequestChange(BaseModel):
    status: str | None = Field(None, max_length=16)
    note: str | None = Field(None, max_length=500)
    reference: str | None = Field(None, max_length=120)
    notes: str | None = Field(None, max_length=4000)
    sent_at: str | None = Field(None, max_length=32)
    # Finite only: a NaN or Infinity cannot be written back out as JSON.
    amount_frozen: float | None = Field(None, allow_inf_nan=False)


def _owner(user: User) -> str:
    if user.owner_hash is None:
        raise HTTPException(status_code=400, detail="This browser sent no owner key, so it has no requests.")
    return user.owner_hash


def _allow_write(http: Request) -> None:
    """Every create or update is a stored write: limit them per connection,
    since a fresh owner key costs nothing."""
    client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
    wait = rate_limit.request_writes.check(client)
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many request updates from this connection in the last hour. Try again later.",
            headers={"Retry-After": str(int(wait))},
        )


@router.get("/requests")
def list_requests(user: CurrentUser, open: bool = Query(False)) -> dict[str, Any]:  # noqa: A002
    items = freeze_requests.list_for(user.owner_hash, open_only=open) if user.owner_hash else []
    audit.record("request.list", detail={"open": open})
    return {"count": len(items), "requests": items}


@router.get("/trace/{case_id}/requests")
def case_requests(case_id: str, user: CurrentUser) -> dict[str, Any]:
    items = freeze_requests.list_for(user.owner_hash, case_id=case_id) if user.owner_hash else []
    audit.record("request.list", case_id=case_id)
    return {"count": len(items), "requests": items}


@router.post("/requests", status_code=201)
def new_request(body: NewRequest, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    try:
        made = freeze_requests.create(_owner(user), body.case_id, body.recipient, body.kind,
                                      body.address, body.asset, body.status)
    except freeze_requests.RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record("request.create", case_id=body.case_id, detail={"kind": made["kind"], "status": made["status"]})
    return made


@router.patch("/requests/{request_id}")
def change_request(request_id: str, body: RequestChange, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    changes = body.model_dump(exclude_unset=True)
    try:
        updated = freeze_requests.update(_owner(user), request_id, changes)
    except freeze_requests.RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="No such request.")
    # Which fields changed, never what they say: notes can name people.
    audit.record("request.update", case_id=updated["case_id"],
                 detail={"request_id": request_id, "fields": sorted(changes)})
    return updated


@router.delete("/requests/{request_id}")
def delete_request(request_id: str, user: CurrentUser) -> dict[str, Any]:
    if not freeze_requests.delete(_owner(user), request_id):
        raise HTTPException(status_code=404, detail="No such request.")
    audit.record("request.delete", detail={"request_id": request_id})
    return {"deleted": request_id}
