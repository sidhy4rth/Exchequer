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

from .. import freeze_requests, ownership

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
    amount_frozen: float | None = None


def _owner(http: Request) -> str:
    owner = ownership.owner_hash_from_headers(http.headers)
    if owner is None:
        raise HTTPException(status_code=400, detail="This browser sent no owner key, so it has no requests.")
    return owner


@router.get("/requests")
def list_requests(http: Request, open: bool = Query(False)) -> dict[str, Any]:  # noqa: A002
    owner = ownership.owner_hash_from_headers(http.headers)
    items = freeze_requests.list_for(owner, open_only=open) if owner else []
    return {"count": len(items), "requests": items}


@router.get("/trace/{case_id}/requests")
def case_requests(case_id: str, http: Request) -> dict[str, Any]:
    owner = ownership.owner_hash_from_headers(http.headers)
    items = freeze_requests.list_for(owner, case_id=case_id) if owner else []
    return {"count": len(items), "requests": items}


@router.post("/requests", status_code=201)
def new_request(body: NewRequest, http: Request) -> dict[str, Any]:
    try:
        return freeze_requests.create(_owner(http), body.case_id, body.recipient, body.kind,
                                      body.address, body.asset, body.status)
    except freeze_requests.RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/requests/{request_id}")
def change_request(request_id: str, body: RequestChange, http: Request) -> dict[str, Any]:
    try:
        updated = freeze_requests.update(_owner(http), request_id, body.model_dump(exclude_unset=True))
    except freeze_requests.RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="No such request.")
    return updated


@router.delete("/requests/{request_id}")
def delete_request(request_id: str, http: Request) -> dict[str, Any]:
    if not freeze_requests.delete(_owner(http), request_id):
        raise HTTPException(status_code=404, detail="No such request.")
    return {"deleted": request_id}
