"""Call detail records read against a case (cdr_imports.py, suite feature 5).

    GET  /trace/{case_id}/cdr         the CDR summaries this browser or unit may read
    POST /trace/{case_id}/cdr         keep the summary the officer confirmed (numbers and counts, never the CDR)
    POST /trace/{case_id}/cdr/check   the numbers the officer chose: on this case's phone identifiers,
                                      and on the other cases they may read (identifiers.also_in)
    POST /trace/{case_id}/cdr/{import_id}/withdraw   withdraw a summary entered by mistake, with a reason
                                      (signed-in officers only; GET ?withdrawn=1 lists them too)

Behind the flag EXCHEQUER_CDR_IMPORT: off, the list says so and the rest is refused.
Numbers go in a POST body, never a URL. Audited by counts only, never a number,
an IMEI or a title: they are a subscriber's particulars and stay in the case record.
A number is a lead; subscriber details come from the operator under a lawful request.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import audit, cdr_imports, config, statement_imports
from ..auth import CurrentUser
from .requests import _allow_write, _owner
from .statements import Withdrawal, listed, withdrawn

router = APIRouter()
OFF = "CDR import is switched off on this deployment."


class CdrSummary(BaseModel):
    title: str = Field("", max_length=120)
    rows: list[dict[str, Any]] = Field(..., max_length=cdr_imports.ROWS_MAX)


class CdrCheck(BaseModel):
    numbers: list[str] = Field(..., max_length=cdr_imports.CHECK_MAX)


@router.get("/trace/{case_id}/cdr")
def list_cdr(case_id: str, user: CurrentUser, withdrawn: bool = False) -> dict[str, Any]:
    if not config.CDR_IMPORT:
        return {"case_id": case_id, "enabled": False, "imports": []}
    found = cdr_imports.list_for(user, case_id, withdrawn=withdrawn)
    return {"case_id": case_id, "enabled": True, "count": len(found), "imports": found,
            "rows_max": cdr_imports.ROWS_MAX, "check_max": cdr_imports.CHECK_MAX,
            **listed(user, "cdr.list", case_id, withdrawn, (cdr_imports.SOURCE,))}


@router.post("/trace/{case_id}/cdr", status_code=201)
def save_cdr(case_id: str, body: CdrSummary, user: CurrentUser, http: Request) -> dict[str, Any]:
    if not config.CDR_IMPORT:
        raise HTTPException(status_code=403, detail=OFF)
    _allow_write(http)
    try:
        made = cdr_imports.create(_owner(user), case_id, body.model_dump(), user)
    except cdr_imports.CdrError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record("cdr.save", case_id=case_id, detail={
        "import_id": made["import_id"], "rows": made["row_count"], **cdr_imports.counts(made["rows"])})
    return made


@router.post("/trace/{case_id}/cdr/check")
def check_numbers(case_id: str, body: CdrCheck, user: CurrentUser) -> dict[str, Any]:
    if not config.CDR_IMPORT:
        raise HTTPException(status_code=403, detail=OFF)
    try:
        found = cdr_imports.check(user, case_id, body.numbers)
    except cdr_imports.CdrError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record("cdr.check", case_id=case_id, detail={
        "numbers": len(found), "on_this_case": sum(f["on_this_case"] for f in found),
        "on_other_cases": sum(bool(f["also_in"]) for f in found)})
    return {"case_id": case_id, "results": found}


@router.post("/trace/{case_id}/cdr/{import_id}/withdraw")
def withdraw_cdr(case_id: str, import_id: str, body: Withdrawal, user: CurrentUser, http: Request) -> dict[str, Any]:
    if not config.CDR_IMPORT:
        raise HTTPException(status_code=403, detail=OFF)
    return withdrawn(lambda: statement_imports.withdraw(user, case_id, import_id, body.reason, sources=(cdr_imports.SOURCE,),
                                                        summarise=cdr_imports.summary),
                     user, http, "cdr.withdraw", case_id, import_id)
