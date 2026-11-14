"""Bank and exchange statement rows kept with a case (statement_imports.py, suite feature 5).

    GET  /trace/{case_id}/statements   the imports this browser or unit may read, and the
                                       canonical exchange names a narration is matched against
    POST /trace/{case_id}/statements   keep the rows the officer confirmed (never the whole statement)

Behind the flag EXCHEQUER_STATEMENT_IMPORT: off, the list says so and saving is refused.
Audited by counts only -- rows kept and why -- never an account number, a reference
or a narration: they are the bank's customer's particulars and stay in the case record.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import audit, config, statement_imports
from ..auth import CurrentUser
from .requests import _allow_write, _owner

router = APIRouter()
OFF = "Statement import is switched off on this deployment."


class StatementRows(BaseModel):
    source: str = Field(..., max_length=16)
    currency: str = Field(..., max_length=12)
    title: str = Field("", max_length=120)
    rows: list[dict[str, Any]] = Field(..., max_length=statement_imports.ROWS_MAX)


@router.get("/trace/{case_id}/statements")
def list_statements(case_id: str, user: CurrentUser) -> dict[str, Any]:
    if not config.STATEMENT_IMPORT:
        return {"case_id": case_id, "enabled": False, "imports": [], "exchange_names": []}
    found = statement_imports.list_for(user, case_id)
    audit.record("statement.list", case_id=case_id)
    return {"case_id": case_id, "enabled": True, "count": len(found), "imports": found,
            "exchange_names": statement_imports.exchange_names(), "reasons": list(statement_imports.REASONS),
            "rows_max": statement_imports.ROWS_MAX}


@router.post("/trace/{case_id}/statements", status_code=201)
def save_statement_rows(case_id: str, body: StatementRows, user: CurrentUser, http: Request) -> dict[str, Any]:
    if not config.STATEMENT_IMPORT:
        raise HTTPException(status_code=403, detail=OFF)
    _allow_write(http)
    try:
        made = statement_imports.create(_owner(user), case_id, body.model_dump(), user)
    except statement_imports.StatementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record("statement.save", case_id=case_id, detail={
        "import_id": made["import_id"], "source": made["source"], "rows": made["row_count"],
        "reasons": statement_imports.reason_counts(made["rows"])})
    return made
