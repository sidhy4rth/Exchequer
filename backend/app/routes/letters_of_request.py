"""A draft letter of request to a foreign country (letters_of_request.py, suite feature 7).

    POST /trace/{case_id}/letter-of-request   the draft, from the case, the officer's details
                                               (in the body, never the URL) and the case's requests log

The audit row says a letter of request was drafted and on which basis, never the
details typed into it; the file is named by case alone.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .. import audit, freeze_requests, letters_of_request
from ..auth import CurrentUser
from .evidence import KEEP, _case_or_404

router = APIRouter()
F = letters_of_request.FIELDS


class LetterOfRequestDetails(BaseModel):
    """What the officer or the Court supplies; anything left out is a marked blank in the draft."""

    country: str = Field("", max_length=F["country"])
    authority: str = Field("", max_length=F["authority"])
    court: str = Field("", max_length=F["court"])
    presiding: str = Field("", max_length=F["presiding"])
    basis: str = Field("", max_length=F["basis"])
    treaty: str = Field("", max_length=F["treaty"])
    agency: str = Field("", max_length=F["agency"])
    reference: str = Field("", max_length=F["reference"])
    proceedings: str = Field("", max_length=F["proceedings"])
    offences: str = Field("", max_length=F["offences"])
    limitation: str = Field("", max_length=F["limitation"])
    facts: str = Field("", max_length=F["facts"])
    exchange_office: str = Field("", max_length=F["exchange_office"])
    period: str = Field("", max_length=F["period"])
    liaison: str = Field("", max_length=F["liaison"])


@router.post("/trace/{case_id}/letter-of-request")
def draft_letter_of_request(case_id: str, body: LetterOfRequestDetails, user: CurrentUser) -> PlainTextResponse:
    case = _case_or_404(case_id, user)
    requests = (freeze_requests.list_for(user.owner_hash, case_id, viewer=user)
                if getattr(user, "owner_hash", None) else [])
    try:
        text = letters_of_request.draft(case_id, case.result, body.model_dump(), requests)
    except letters_of_request.LetterOfRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record("case.letter_of_request_draft", case_id=case_id, detail={"basis": body.basis or "not chosen"})
    return PlainTextResponse(text, headers={
        **KEEP, "Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}-letter-of-request.txt"'})
