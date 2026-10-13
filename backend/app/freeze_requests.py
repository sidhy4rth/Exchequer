"""Track the requests sent about a case, and what came of them.

The tool drafts the letter (request_letters.py); the officer sends it, by
whatever channel the exchange accepts. What happens next -- an
acknowledgement, a freeze, a refusal, silence -- used to live in someone's
inbox. Here each request is a row with a status, a reference, the amount
frozen and a dated history, owned by the browser that logged it (like its
cases), so a case shows where its requests stand and the home page shows
which are still waiting.

Statuses, in the order they usually happen:

  drafted       the letter is written, not yet sent
  sent          sent; waiting for a reply (flagged after FOLLOW_UP_DAYS)
  acknowledged  the recipient replied and is looking at it
  frozen        funds frozen (amount_frozen says how much)
  declined      the recipient will not act
  closed        nothing more to do
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from . import models

STATUSES = ("drafted", "sent", "acknowledged", "frozen", "declined", "closed")
OPEN_STATUSES = ("drafted", "sent", "acknowledged")
KINDS = ("exchange", "tether", "other")
FOLLOW_UP_DAYS = 7


class RequestError(ValueError):
    pass


def _now() -> str:
    return models.utc_now_iso()


def summary(r: models.FreezeRequest) -> dict[str, Any]:
    waiting = None
    if r.status == "sent" and r.sent_at:
        try:
            waiting = (datetime.now(tz=timezone.utc) - datetime.fromisoformat(r.sent_at)).days
        except ValueError:
            waiting = None
    return {
        "request_id": r.id, "case_id": r.case_id, "recipient": r.recipient, "kind": r.kind,
        "status": r.status, "address": r.address, "reference": r.reference, "sent_at": r.sent_at,
        "amount_frozen": r.amount_frozen, "asset": r.asset, "notes": r.notes,
        "created_at": r.created_at, "updated_at": r.updated_at,
        "days_waiting": waiting,
        "follow_up": waiting is not None and waiting >= FOLLOW_UP_DAYS,
        "history": json.loads(r.history_json or "[]"),
    }


def create(owner: str, case_id: str, recipient: str, kind: str, address: str = "",
           asset: str = "", status: str = "drafted") -> dict[str, Any]:
    if models.get_case(case_id) is None:
        raise RequestError("No case with that id.")
    recipient = (recipient or "").strip()[:120]
    if not recipient:
        raise RequestError("Say who the request is to.")
    if kind not in KINDS:
        raise RequestError(f"kind must be one of {', '.join(KINDS)}.")
    if status not in STATUSES:
        raise RequestError(f"status must be one of {', '.join(STATUSES)}.")
    now = _now()
    r = models.FreezeRequest(
        id=str(uuid.uuid4()), owner_hash=owner, case_id=case_id, recipient=recipient, kind=kind,
        status=status, address=(address or "")[:64], asset=(asset or "")[:16],
        sent_at=now if status == "sent" else None, created_at=now, updated_at=now,
        history_json=json.dumps([{"at": now, "status": status}]),
    )
    with models.session() as s:
        s.add(r)
        s.commit()
        s.refresh(r)
        return summary(r)


def update(owner: str, request_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    with models.session() as s:
        r = s.get(models.FreezeRequest, request_id)
        if r is None or r.owner_hash != owner:
            return None
        history = json.loads(r.history_json or "[]")
        now = _now()
        status = changes.get("status")
        if status is not None:
            if status not in STATUSES:
                raise RequestError(f"status must be one of {', '.join(STATUSES)}.")
            if status != r.status:
                entry: dict[str, Any] = {"at": now, "status": status}
                if changes.get("note"):
                    entry["note"] = str(changes["note"])[:500]
                history.append(entry)
                r.status = status
                if status == "sent" and not r.sent_at:
                    r.sent_at = now
        if "reference" in changes and changes["reference"] is not None:
            r.reference = str(changes["reference"])[:120]
        if "notes" in changes and changes["notes"] is not None:
            r.notes = str(changes["notes"])[:4000]
        if "sent_at" in changes and changes["sent_at"]:
            try:
                parsed = datetime.fromisoformat(str(changes["sent_at"]))
            except ValueError as exc:
                raise RequestError("sent_at must be a date like 2026-10-13.") from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            r.sent_at = parsed.isoformat(timespec="seconds")
        if "amount_frozen" in changes:
            value = changes["amount_frozen"]
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                raise RequestError("amount_frozen must be a positive number.")
            r.amount_frozen = value
        r.history_json = json.dumps(history)
        r.updated_at = now
        s.commit()
        s.refresh(r)
        return summary(r)


def delete(owner: str, request_id: str) -> bool:
    with models.session() as s:
        r = s.get(models.FreezeRequest, request_id)
        if r is None or r.owner_hash != owner:
            return False
        s.delete(r)
        s.commit()
        return True


def list_for(owner: str, case_id: str | None = None, open_only: bool = False) -> list[dict[str, Any]]:
    with models.session() as s:
        stmt = select(models.FreezeRequest).where(models.FreezeRequest.owner_hash == owner)
        if case_id:
            stmt = stmt.where(models.FreezeRequest.case_id == case_id)
        if open_only:
            stmt = stmt.where(models.FreezeRequest.status.in_(OPEN_STATUSES))
        stmt = stmt.order_by(models.FreezeRequest.updated_at.desc())
        return [summary(r) for r in s.scalars(stmt)]
