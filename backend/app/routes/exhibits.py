"""The exhibit register (exhibits.py): files outside forensic tools produced for a case.

    GET   /trace/{case_id}/exhibits   the case's exhibits this browser or unit may read
    POST  /trace/{case_id}/exhibits   record one (409 when the same file is already one)
    PATCH /exhibits/{exhibit_id}      hand over, move, end, or add notes
    POST  /exhibits/{exhibit_id}/check  compare a file's SHA-256 with the record

The file is never sent: only its hash. Writes are limited per connection, like
the requests log, and audited by what happened, never by the text or the hash.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import audit, exhibits
from ..auth import CurrentUser
from .requests import _allow_write, _owner

router = APIRouter()


class NewExhibit(BaseModel):
    kind: str = Field(..., max_length=24)
    label: str = Field(..., max_length=200)
    tool: str = Field(..., max_length=120)
    file_name: str = Field("", max_length=200)
    size_bytes: int | str | None = Field(None, union_mode="left_to_right")
    sha256: str = Field("", max_length=64)
    sha1: str = Field("", max_length=40)
    md5: str = Field("", max_length=32)
    made_by: str = Field("", max_length=120)
    made_on: str = Field(..., max_length=10)
    stored_at: str = Field("", max_length=200)
    holder: str = Field("", max_length=120)
    notes: str = Field("", max_length=2000)


class ExhibitChange(BaseModel):
    holder: str | None = Field(None, max_length=120)
    stored_at: str | None = Field(None, max_length=200)
    status: str | None = Field(None, max_length=16)
    notes: str | None = Field(None, max_length=2000)
    note: str | None = Field(None, max_length=300)


class FileHash(BaseModel):
    sha256: str = Field(..., max_length=66)


def _bad(exc: exhibits.ExhibitError) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(exc, exhibits.DuplicateExhibit) else 400, detail=str(exc))


@router.get("/trace/{case_id}/exhibits")
def list_exhibits(case_id: str, user: CurrentUser) -> dict[str, Any]:
    rows = exhibits.list_for(user, case_id)
    audit.record("exhibit.list", case_id=case_id)
    return {"case_id": case_id, "count": len(rows), "exhibits": rows, "kinds": exhibits.KINDS}


@router.post("/trace/{case_id}/exhibits", status_code=201)
def add_exhibit(case_id: str, body: NewExhibit, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    try:
        made = exhibits.create(_owner(user), case_id, body.model_dump(), user)
    except exhibits.ExhibitError as exc:
        raise _bad(exc) from exc
    audit.record("exhibit.add", case_id=case_id, detail={"exhibit_id": made["exhibit_id"], "kind": made["kind"]})
    return made


@router.patch("/exhibits/{exhibit_id}")
def change_exhibit(exhibit_id: str, body: ExhibitChange, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    try:
        updated = exhibits.update(exhibit_id, body.model_dump(exclude_none=True), user)
    except exhibits.ExhibitError as exc:
        raise _bad(exc) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="No exhibit with that id that you can change.")
    changed = updated.pop("changed")
    if changed:
        audit.record("exhibit.update", case_id=updated["case_id"], detail={"exhibit_id": exhibit_id, "changed": changed})
    return updated


@router.post("/exhibits/{exhibit_id}/check")
def check_exhibit(exhibit_id: str, body: FileHash, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    try:
        checked = exhibits.check(exhibit_id, body.sha256, user)
    except exhibits.ExhibitError as exc:
        raise _bad(exc) from exc
    if checked is None:
        raise HTTPException(status_code=404, detail="No exhibit with that id that you can check.")
    audit.record("exhibit.check", case_id=checked["exhibit"]["case_id"],
                 detail={"exhibit_id": exhibit_id, "result": checked["result"]})
    return checked
