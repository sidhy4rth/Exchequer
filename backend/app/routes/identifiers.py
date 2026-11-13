"""The case identifier register (identifiers.py, suite feature 4): what the victim reported besides the wallet.

    GET   /trace/{case_id}/identifiers   the case's identifiers this browser or unit may read
    POST  /trace/{case_id}/identifiers   record one (409 when it is already recorded)
    PATCH /identifiers/{identifier_id}   change where it was seen or the notes, withdraw it, or add a note

Writes are limited per connection, like the requests log, and audited by what
happened -- the kind and the fields changed -- never by the value: a phone number
or a handle is personal data and stays out of the audit log.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import audit, identifiers
from ..auth import CurrentUser
from .requests import _allow_write, _owner

router = APIRouter()


class NewIdentifier(BaseModel):
    kind: str = Field(..., max_length=16)
    value: str = Field(..., max_length=300)
    context: str = Field("", max_length=200)
    notes: str = Field("", max_length=2000)


class IdentifierChange(BaseModel):
    context: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=2000)
    status: str | None = Field(None, max_length=16)
    note: str | None = Field(None, max_length=300)


def _bad(exc: identifiers.IdentifierError) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(exc, identifiers.DuplicateIdentifier) else 400, detail=str(exc))


@router.get("/trace/{case_id}/identifiers")
def list_identifiers(case_id: str, user: CurrentUser) -> dict[str, Any]:
    rows = identifiers.list_for(user, case_id)
    audit.record("identifier.list", case_id=case_id)
    return {"case_id": case_id, "count": len(rows), "identifiers": rows, "kinds": identifiers.KINDS}


@router.post("/trace/{case_id}/identifiers", status_code=201)
def add_identifier(case_id: str, body: NewIdentifier, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    try:
        made = identifiers.create(_owner(user), case_id, body.model_dump(), user)
    except identifiers.IdentifierError as exc:
        raise _bad(exc) from exc
    audit.record("identifier.add", case_id=case_id, detail={"identifier_id": made["identifier_id"], "kind": made["kind"]})
    return made


@router.patch("/identifiers/{identifier_id}")
def change_identifier(identifier_id: str, body: IdentifierChange, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    try:
        updated = identifiers.update(identifier_id, body.model_dump(exclude_none=True), user)
    except identifiers.IdentifierError as exc:
        raise _bad(exc) from exc
    except identifiers.IdentifierConflict as exc:
        raise HTTPException(status_code=409, detail="Someone changed this identifier at the same moment. Reload and try again.") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="No identifier with that id that you can change.")
    changed = updated.pop("changed")
    if changed:
        audit.record("identifier.update", case_id=updated["case_id"],
                     detail={"identifier_id": identifier_id, "changed": changed})
    return updated
