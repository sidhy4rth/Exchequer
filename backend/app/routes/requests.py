"""Freeze and information requests logged against cases (freeze_requests.py).

    GET    /requests                     this browser's requests (?open=true)
    GET    /trace/{case_id}/requests     this browser's requests for one case
    POST   /requests                     log one
    PATCH  /requests/{id}                change status, reference, notes, amount
    POST   /requests/{id}/signoff        a second officer approves an urgent freeze letter
    DELETE /requests/{id}
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import accounts, audit, freeze_requests, rate_limit
from ..auth import CurrentUser, User
from ..input_rules import NoNul, OneLine
from .cases import app_page

router = APIRouter()


class NewRequest(BaseModel):
    case_id: OneLine = Field(..., max_length=36)
    recipient: OneLine = Field(..., max_length=120)
    kind: OneLine = Field("exchange", max_length=16)
    address: OneLine = Field("", max_length=64)
    asset: OneLine = Field("", max_length=16)
    status: OneLine = Field("drafted", max_length=16)


class RequestChange(BaseModel):
    status: OneLine | None = Field(None, max_length=16)
    note: NoNul | None = Field(None, max_length=500)
    reference: OneLine | None = Field(None, max_length=120)
    notes: NoNul | None = Field(None, max_length=4000)
    sent_at: OneLine | None = Field(None, max_length=32)
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


def _conflict() -> HTTPException:
    return HTTPException(status_code=409, detail="Someone changed this request at the same moment. "
                                                 "Reload it and make the change again.")


@router.get("/requests", response_model=None)
def list_requests(user: CurrentUser, http: Request, open: bool = Query(False)) -> dict[str, Any] | FileResponse:  # noqa: A002
    """The caller's freeze requests; a browser opening /requests gets the app's page."""
    if (page := app_page(http)) is not None:
        return page
    items = freeze_requests.list_for(user.owner_hash, open_only=open) if user.owner_hash else []
    audit.record("request.list", detail={"open": open})
    return {"count": len(items), "requests": items}


@router.get("/trace/{case_id}/requests")
def case_requests(case_id: str, user: CurrentUser) -> dict[str, Any]:
    if not user.owner_hash:  # logs nothing, so has nothing to ask (and answers as before)
        audit.record("request.list", case_id=case_id)
        return {"count": 0, "requests": []}
    items = freeze_requests.list_for(user.owner_hash, case_id=case_id, viewer=user)
    audit.record("request.list", case_id=case_id)
    # Said before anyone presses Ask for sign-off, so a demo user meets no dead end.
    return {"count": len(items), "requests": items, "ask_reason": freeze_requests.ask_reason(user)}


@router.post("/requests", status_code=201)
def new_request(body: NewRequest, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    try:
        made = freeze_requests.create(_owner(user), body.case_id, body.recipient, body.kind,
                                      body.address, body.asset, body.status, viewer=user)
    except freeze_requests.RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record("request.create", case_id=body.case_id, detail={"kind": made["kind"], "status": made["status"]})
    if made["status"] == "awaiting_signoff":  # the ask, made while logging the letter
        audit.record("request.signoff_ask", case_id=body.case_id, detail={"request_id": made["request_id"]})
    return made


@router.patch("/requests/{request_id}")
def change_request(request_id: str, body: RequestChange, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    changes = body.model_dump(exclude_unset=True)
    try:
        updated = freeze_requests.update(_owner(user), request_id, changes, viewer=user)
    except freeze_requests.RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except freeze_requests.RequestConflict as exc:
        raise _conflict() from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="No such request.")
    asked = updated.pop("moved") and updated["status"] == "awaiting_signoff"
    # Which fields changed, never what they say: notes can name people.
    audit.record("request.signoff_ask" if asked else "request.update", case_id=updated["case_id"],
                 detail={"request_id": request_id, "fields": sorted(changes)})
    return updated


@router.delete("/requests/{request_id}")
def delete_request(request_id: str, user: CurrentUser) -> dict[str, Any]:
    try:
        deleted = freeze_requests.delete(_owner(user), request_id)
    except freeze_requests.RequestConflict as exc:
        raise _conflict() from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="No such request.")
    audit.record("request.delete", detail={"request_id": request_id})
    return {"deleted": request_id}


def _csrf(http: Request) -> None:
    """The sign-off is the caller's session speaking: a cross-site form must not."""
    if http.headers.get(accounts.CSRF_HEADER) != "1":
        raise HTTPException(status_code=403, detail=f"This request needs the {accounts.CSRF_HEADER} header.")


@router.post("/requests/{request_id}/signoff", dependencies=[Depends(_csrf)])
def sign_off(request_id: str, user: CurrentUser, http: Request) -> dict[str, Any]:
    """A second signed-in officer or supervisor of the drafter's unit makes an
    urgent freeze letter ready. Everyone else is told why they cannot."""
    _allow_write(http)
    try:
        signed = freeze_requests.sign_off(request_id, user)
    except freeze_requests.SignoffRefused as exc:
        audit.record("request.signoff_refused", detail={"request_id": request_id, "code": exc.code})
        raise HTTPException(status_code=exc.code, detail=str(exc)) from exc
    except freeze_requests.RequestConflict as exc:
        raise _conflict() from exc
    if signed is None:
        raise HTTPException(status_code=404, detail="No such request.")
    audit.record("request.signoff", case_id=signed["case_id"], detail={"request_id": request_id})
    return signed
