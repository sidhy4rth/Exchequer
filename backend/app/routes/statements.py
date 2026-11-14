"""Bank and exchange statement rows kept with a case (statement_imports.py, suite feature 5).

    GET  /trace/{case_id}/statements   the imports this browser or unit may read, and the
                                       canonical exchange names a narration is matched against
                                       (?withdrawn=1: the withdrawn ones too, with their reasons)
    POST /trace/{case_id}/statements   keep the rows the officer confirmed (never the whole statement)
    POST /trace/{case_id}/statements/{import_id}/withdraw   withdraw one entered by mistake, with a
                                       reason (signed-in officers only; audited by id, never the reason)

Behind the flag EXCHEQUER_STATEMENT_IMPORT: off, the list says so and saving is refused.
Audited by counts only -- rows kept and why -- never an account number, a reference
or a narration: they are the bank's customer's particulars and stay in the case record.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import audit, config, statement_imports
from ..auth import CurrentUser
from .requests import _allow_write, _owner

router = APIRouter()
OFF = "Statement import is switched off on this deployment."
SIGN_IN_TO_WITHDRAW = "Sign in as an officer to withdraw a saved import."


class StatementRows(BaseModel):
    source: str = Field(..., max_length=16)
    currency: str = Field(..., max_length=12)
    title: str = Field("", max_length=120)
    rows: list[dict[str, Any]] = Field(..., max_length=statement_imports.ROWS_MAX)


class Withdrawal(BaseModel):
    reason: str = Field("", max_length=statement_imports.TEXT["reason"])


def listed(user: CurrentUser, event: str, case_id: str, withdrawn: bool, sources: Any) -> dict[str, Any]:
    """What a listing adds for withdrawal, audited as `event` (whether withdrawn imports were shown)."""
    audit.record(event, case_id=case_id, **({"detail": {"withdrawn": True}} if withdrawn else {}))
    return {"withdrawn_count": statement_imports.withdrawn_count(user, case_id, sources), "can_withdraw": not user.demo}


def withdrawn(withdraw: Callable[[], dict[str, Any] | None], user: CurrentUser, http: Request, event: str,
              case_id: str, import_id: str) -> dict[str, Any]:
    """Run `withdraw` for a signed-in officer; audit `event` by the import's id, never its reason."""
    if user.demo:
        raise HTTPException(status_code=403, detail=SIGN_IN_TO_WITHDRAW)
    _allow_write(http)
    try:
        done = withdraw()
    except statement_imports.AlreadyWithdrawn as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except statement_imports.StatementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except statement_imports.ImportConflict as exc:
        raise HTTPException(status_code=409, detail="Someone changed this import at the same moment. Reload and try again.") from exc
    if done is None:
        raise HTTPException(status_code=404, detail="No import with that id on this case that you can withdraw.")
    audit.record(event, case_id=case_id, detail={"import_id": import_id})
    return done


@router.get("/trace/{case_id}/statements")
def list_statements(case_id: str, user: CurrentUser, withdrawn: bool = False) -> dict[str, Any]:
    if not config.STATEMENT_IMPORT:
        return {"case_id": case_id, "enabled": False, "imports": [], "exchange_names": []}
    found = statement_imports.list_for(user, case_id, withdrawn=withdrawn)
    return {"case_id": case_id, "enabled": True, "count": len(found), "imports": found,
            "exchange_names": statement_imports.exchange_names(), "reasons": list(statement_imports.REASONS),
            "rows_max": statement_imports.ROWS_MAX,
            **listed(user, "statement.list", case_id, withdrawn, statement_imports.SOURCES)}


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


@router.post("/trace/{case_id}/statements/{import_id}/withdraw")
def withdraw_statement(case_id: str, import_id: str, body: Withdrawal, user: CurrentUser, http: Request) -> dict[str, Any]:
    if not config.STATEMENT_IMPORT:
        raise HTTPException(status_code=403, detail=OFF)
    return withdrawn(lambda: statement_imports.withdraw(user, case_id, import_id, body.reason), user, http,
                     "statement.withdraw", case_id, import_id)
