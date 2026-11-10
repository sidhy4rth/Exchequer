"""The officers' side of citizen complaints: the review queue.

    GET  /complaints                    the queue, newest first (?status=&limit=&offset=), with its total
    GET  /complaints/{ref}              one complaint: what the citizen sent, payments, messages
    POST /complaints/{ref}/status       received | with_cell | investigating | closed
    POST /complaints/{ref}/messages     an officer's reply, the ONLY thing that goes back to the citizen
    POST /complaints/{ref}/link-case    the stored case it was traced in (officers only)

The citizen tables (app/complaints.py) are read through this app's own
connection. A list masks the NCRP number and leaves the phone out; neither
ever reaches a log or the audit trail, which names the complaint by its
reference. Whether a paid wallet is in other complaints or a stored case is
shown here and never to the citizen.

Who may: the investigator rules (auth.current_user). Until officers sign in
the caller is a demo identity, so a public deployment refuses the queue to
everyone: a demo code is shared with visitors, and must never open real
victims' complaints. Locally (tests, a laptop) it is open like the console.
"""
from __future__ import annotations

import json
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from .. import audit, config, models
from ..auth import CurrentUser, User
from ..complaints import Complaint, ComplaintLink, ComplaintMessage, ComplaintPayment
from ..input_rules import NoNul, OneLine
from .cases import app_page

router = APIRouter()

Status = Literal["received", "with_cell", "investigating", "closed"]
Reference = Annotated[str, Path(max_length=16, pattern=r"^[A-Za-z0-9-]+$")]
MESSAGE_CAP = 2000  # the citizen's own cap (citizen/api/_lib/complaint.py)
DETAILS = ("name", "mobile", "started", "app", "link", "contacts", "upi", "story")


class StatusChange(BaseModel):
    status: Status


class Reply(BaseModel):
    body: NoNul = Field(..., max_length=MESSAGE_CAP)


class CaseLink(BaseModel):
    case_id: OneLine = Field(..., min_length=1, max_length=36)


def _officer(user: User) -> None:
    """Refuses the queue to a demo identity on a public site (see above)."""
    if user.demo and config.PUBLIC_HOST:
        raise HTTPException(status_code=403, detail="The complaints queue opens only to signed-in officers.")


def _scope(user: User):
    """Which complaints `user` may see: every one, until accounts land.
    TODO(accounts): when officers sign in (the accounts branch), keep this the
    one place the queue is scoped: return the complaints routed to `user.unit`
    (a unit column the integration adds) unless the user is a supervisor."""
    del user
    return true()


def _visible(user: User):
    return select(Complaint).where(_scope(user))


def _find(s: Session, reference: str, user: User) -> Complaint:
    row = s.scalars(_visible(user).where(Complaint.reference == reference)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No complaint with that reference.")
    return row


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ordered_id() -> str:
    """Sorts in the order written, as the citizen site's ids do."""
    return f"{time.time_ns():020d}{secrets.token_hex(8)}"


def masked(ncrp: str) -> str:
    return "••••" + ncrp[-4:]


def _flags(row: Complaint) -> dict[str, bool]:
    tags = set((row.wallet_match or "").split(","))
    return {"in_other_complaints": "complaint" in tags, "in_stored_case": "case" in tags}


def _totals(payments: list[ComplaintPayment]) -> list[dict[str, str]]:
    """The amounts summed per token, as the citizen wrote them."""
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for p in payments:
        try:
            sums[p.token] += Decimal(p.amount)
        except InvalidOperation:  # an amount left empty
            continue
    return [{"token": t, "amount": format(sums[t].normalize(), "f")} for t in sorted(sums)]


@router.get("/complaints", response_model=None)
def queue(http: Request, user: CurrentUser, status: Status | None = None,
          limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict[str, Any] | FileResponse:
    """One page of the queue and how many there are in all, so the page can
    say when older complaints are past it and fetch them."""
    if (page := app_page(http)) is not None:
        return page
    _officer(user)
    with models.session() as s:
        q = _visible(user).where(Complaint.status == status) if status else _visible(user)
        total = s.scalar(select(func.count()).select_from(q.subquery()))
        rows = s.scalars(q.order_by(Complaint.created_at.desc(), Complaint.id.desc()).limit(limit).offset(offset)).all()
        paid: dict[str, list[ComplaintPayment]] = defaultdict(list)
        for p in s.scalars(select(ComplaintPayment).where(ComplaintPayment.complaint_id.in_([r.id for r in rows]))):
            paid[p.complaint_id].append(p)
    audit.record("complaint.list", detail={"status": status} if status else None)
    return {"count": len(rows), "total": total, "complaints": [{
        "reference": r.reference, "received_at": r.created_at, "ncrp": masked(r.ncrp), "status": r.status,
        "payments": len(paid[r.id]), "totals": _totals(paid[r.id]), **_flags(r),
    } for r in rows]}


@router.get("/complaints/{reference}", response_model=None)
def complaint(reference: Reference, http: Request, user: CurrentUser) -> dict[str, Any] | FileResponse:
    if (page := app_page(http)) is not None:
        return page
    _officer(user)
    with models.session() as s:
        row = _find(s, reference, user)
        payments = s.scalars(select(ComplaintPayment).where(ComplaintPayment.complaint_id == row.id)
                             .order_by(ComplaintPayment.id)).all()
        messages = s.scalars(select(ComplaintMessage).where(ComplaintMessage.complaint_id == row.id,
                                                            ComplaintMessage.sender.in_(("citizen", "officer")))
                             .order_by(ComplaintMessage.created_at, ComplaintMessage.id)).all()
        link = s.get(ComplaintLink, row.id)
    sent = json.loads(row.details_json or "{}")
    audit.record("complaint.read", detail={"reference": row.reference})
    return {
        "reference": row.reference, "received_at": row.created_at, "updated_at": row.updated_at,
        "status": row.status, "ncrp": row.ncrp, **_flags(row),
        "details": {k: str(sent.get(k) or "") for k in DETAILS},
        "payments": [{"hash": p.tx_hash, "amount": p.amount, "token": p.token, "network": p.network,
                      "paid_at": p.paid_at, "wallet": p.wallet} for p in payments],
        "messages": [{"from": m.sender, "body": m.body, "at": m.created_at} for m in messages],
        "case_id": link.case_id if link else None,
    }


@router.post("/complaints/{reference}/status")
def change_status(reference: Reference, change: StatusChange, user: CurrentUser) -> dict[str, str]:
    _officer(user)
    with models.session() as s:
        row = _find(s, reference, user)
        row.status, row.updated_at = change.status, _stamp()
        s.commit()
    audit.record("complaint.status", detail={"reference": reference, "status": change.status})
    return {"reference": reference, "status": change.status}


@router.post("/complaints/{reference}/messages", status_code=201)
def reply(reference: Reference, message: Reply, user: CurrentUser) -> dict[str, str]:
    """The officer's words, stored where the citizen's site reads them."""
    _officer(user)
    text = "".join(c for c in message.body if c == "\n" or c >= " " and c != "\x7f").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Write a message first.")
    at = _stamp()
    with models.session() as s:
        row = _find(s, reference, user)
        s.add(ComplaintMessage(id=_ordered_id(), complaint_id=row.id, sender="officer", body=text, created_at=at))
        row.updated_at = at
        s.commit()
    audit.record("complaint.message", detail={"reference": reference, "characters": len(text)})
    return {"from": "officer", "body": text, "at": at}


@router.post("/complaints/{reference}/link-case")
def link_case(reference: Reference, link: CaseLink, user: CurrentUser) -> dict[str, str]:
    _officer(user)
    if models.get_case(link.case_id) is None:
        raise HTTPException(status_code=404, detail="No stored case with that id.")
    with models.session() as s:
        row = _find(s, reference, user)
        s.merge(ComplaintLink(complaint_id=row.id, case_id=link.case_id, linked_at=_stamp()))
        s.commit()
    audit.record("complaint.link_case", case_id=link.case_id, detail={"reference": reference})
    return {"reference": reference, "case_id": link.case_id}
