"""The case's crypto summary in the CFCFRMS SOP's 9.4 terms (app/sop_summary.py).

    GET  /sop-summary                     whether this server offers it (EXCHEQUER_SOP_SUMMARY)
    POST /trace/{case_id}/sop-summary     the plain text, for the officer to copy

Both answer 404 with the flag off, as if they did not exist. The officer's
answer to "Is this exchange on CFCFRMS?" is sent in the body and not stored;
the audit row records which of the three answers it was and nothing else.
The NCRP number is never sent here: the officer's browser fills it in.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict

from .. import audit, config, sop_summary
from ..auth import CurrentUser
from .evidence import KEEP, _case_or_404

router = APIRouter()


def _offered() -> None:
    if not config.SOP_SUMMARY:
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/sop-summary")
def offered(user: CurrentUser) -> dict[str, Any]:
    """Whether the case page offers the summary; reads no case."""
    _offered()
    return {"enabled": True}


class Ask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_cfcfrms: sop_summary.Answer = "unknown"


@router.post("/trace/{case_id}/sop-summary")
def summary(case_id: str, body: Ask, user: CurrentUser) -> PlainTextResponse:
    """The summary of the case as this caller may read it (case_privacy.py)."""
    _offered()
    case = _case_or_404(case_id, user)
    text = sop_summary.summary(case_id, case.result, body.on_cfcfrms)
    audit.record("case.sop_summary_copy", case_id=case_id, detail={"on_cfcfrms": body.on_cfcfrms})
    return PlainTextResponse(text, headers=KEEP)
