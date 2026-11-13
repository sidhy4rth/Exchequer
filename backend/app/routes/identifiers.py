"""The case identifier register (identifiers.py, suite feature 4): what the victim reported besides the wallet.

    GET   /trace/{case_id}/identifiers   the case's identifiers this browser or unit may read, each with
                                         the other cases (of this browser or unit) that have it too
    POST  /trace/{case_id}/identifiers   record one (409 when it is already recorded)
    PATCH /identifiers/{identifier_id}   change where it was seen or the notes, withdraw it, or add a note
    POST  /identifiers/{identifier_id}/lookup   RDAP and DNS facts about a domain (config.OSINT_LOOKUPS),
                                               signed-in officers only, never the demo caller

Writes are limited per connection, like the requests log, and audited by what
happened -- the kind and the fields changed -- never by the value: a phone number
or a handle is personal data and stays out of the audit log.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import audit, config, domain_lookup, identifiers
from ..auth import CurrentUser
from .requests import _allow_write, _owner

router = APIRouter()
SIGN_IN_TO_LOOK_UP = "Sign in as an officer to look up a domain's public records."


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
    latest = domain_lookup.latest_for([r["identifier_id"] for r in rows if r["kind"] == "domain"])
    links = identifiers.also_in(user, case_id, rows)
    for r in rows:
        r["lookup"] = latest.get(r["identifier_id"])
        r["also_in"] = links.get(r["identifier_id"], [])
    audit.record("identifier.list", case_id=case_id)
    return {"case_id": case_id, "count": len(rows), "identifiers": rows, "kinds": identifiers.KINDS,
            "lookups_enabled": config.OSINT_LOOKUPS and not user.demo,
            "lookups_note": SIGN_IN_TO_LOOK_UP if config.OSINT_LOOKUPS and user.demo else ""}


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
    changed, noted = updated.pop("changed"), updated.pop("noted")
    if changed or noted:  # every new history entry is audited; a note's words never are
        detail = {"identifier_id": identifier_id, "changed": changed, **({"noted": True} if noted else {})}
        audit.record("identifier.update", case_id=updated["case_id"], detail=detail)
    return updated


@router.post("/identifiers/{identifier_id}/lookup")
def look_up_identifier(identifier_id: str, user: CurrentUser, http: Request) -> dict[str, Any]:
    if not config.OSINT_LOOKUPS:
        raise HTTPException(status_code=403, detail="Domain lookups are switched off on this deployment.")
    if user.demo:  # each lookup makes the server ask outside services: only for a signed-in officer
        raise HTTPException(status_code=403, detail=SIGN_IN_TO_LOOK_UP)
    _allow_write(http)
    try:
        found = domain_lookup.run_and_keep(identifier_id, user)
    except identifiers.IdentifierError as exc:
        raise _bad(exc) from exc
    except domain_lookup.LookupError_ as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if found is None:
        raise HTTPException(status_code=404, detail="No identifier with that id that you can look up.")
    audit.record("identifier.lookup", case_id=found["case_id"],
                 detail={"identifier_id": identifier_id, "lookup_id": found["lookup_id"],
                         "rdap": found["rdap"] is not None, "dns": bool(found["dns"])})
    return found
