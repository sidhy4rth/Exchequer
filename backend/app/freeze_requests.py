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

from sqlalchemy import func, select
from sqlalchemy.orm.exc import StaleDataError

from . import models

STATUSES = ("drafted", "sent", "acknowledged", "frozen", "declined", "closed")
OPEN_STATUSES = ("drafted", "sent", "acknowledged")
# The first two are the urgent freeze letters (request_letters.LETTERS): each
# letter the tool drafts can be logged as sent under its own name.
KINDS = ("exchange", "tether", "other", "exchange-freeze", "tether-freeze")
FOLLOW_UP_DAYS = 7
# Bounds on what anyone can store here. Owner keys are free, so the per-owner
# cap alone would not bound the table: MAX_TOTAL does. A real request moves
# through six statuses at most; HISTORY_MAX keeps a toggled one from growing.
MAX_PER_OWNER = 200
MAX_TOTAL = 20_000
HISTORY_MAX = 50


# Tries per update or delete when another write lands between the read and
# the write (row_version moved): each try re-reads and re-applies the change.
WRITE_TRIES = 3


class RequestError(ValueError):
    pass


class RequestConflict(RuntimeError):
    """The request kept changing underneath this update; the caller should reload."""


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
    # The cheap checks first, and the case looked up by id alone: its stored
    # result can be megabytes, read from a metered database, and a rejected
    # request must not cost that.
    recipient = (recipient or "").strip()[:120]
    if not recipient:
        raise RequestError("Say who the request is to.")
    if kind not in KINDS:
        raise RequestError(f"kind must be one of {', '.join(KINDS)}.")
    if status not in STATUSES:
        raise RequestError(f"status must be one of {', '.join(STATUSES)}.")
    with models.session() as s:
        if s.scalar(select(models.Case.id).where(models.Case.id == case_id)) is None:
            raise RequestError("No case with that id.")
    now = _now()
    r = models.FreezeRequest(
        id=str(uuid.uuid4()), owner_hash=owner, case_id=case_id, recipient=recipient, kind=kind,
        status=status, address=(address or "")[:64], asset=(asset or "")[:16],
        sent_at=now if status == "sent" else None, created_at=now, updated_at=now,
        history_json=json.dumps([{"at": now, "status": status}]),
    )
    with models.session() as s:
        count = select(func.count()).select_from(models.FreezeRequest)
        if s.scalar(count.where(models.FreezeRequest.owner_hash == owner)) >= MAX_PER_OWNER:
            raise RequestError(f"This browser already has {MAX_PER_OWNER} requests; delete closed ones first.")
        if s.scalar(count) >= MAX_TOTAL:
            raise RequestError("The request log is full on this deployment; ask its operator.")
        s.add(r)
        s.commit()
        s.refresh(r)
        return summary(r)


def update(owner: str, request_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    """Apply `changes`; None if the request is not this owner's. Two updates
    at once both land: the second re-reads and re-applies on its next try."""
    for _ in range(WRITE_TRIES):
        try:
            return _update_once(owner, request_id, changes)
        except StaleDataError:
            continue
    raise RequestConflict(request_id)


def _update_once(owner: str, request_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
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
            # Stored in UTC: an offset with seconds (+05:30:15.123456) would
            # otherwise be written back longer than the 32-character column.
            try:
                r.sent_at = parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
            except (OverflowError, ValueError) as exc:
                # A valid date whose offset moves it past year 1 or 9999.
                raise RequestError("sent_at must be a date like 2026-10-13.") from exc
        if "amount_frozen" in changes:
            value = changes["amount_frozen"]
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                raise RequestError("amount_frozen must be a positive number.")
            r.amount_frozen = value
        r.history_json = json.dumps(history[-HISTORY_MAX:])
        r.updated_at = now
        s.commit()
        s.refresh(r)
        return summary(r)


def delete(owner: str, request_id: str) -> bool:
    for _ in range(WRITE_TRIES):
        try:
            with models.session() as s:
                r = s.get(models.FreezeRequest, request_id)
                if r is None or r.owner_hash != owner:
                    return False
                s.delete(r)
                s.commit()
                return True
        except StaleDataError:
            continue  # updated meanwhile: read it again and delete that
    raise RequestConflict(request_id)


def list_for(owner: str, case_id: str | None = None, open_only: bool = False) -> list[dict[str, Any]]:
    with models.session() as s:
        stmt = select(models.FreezeRequest).where(models.FreezeRequest.owner_hash == owner)
        if case_id:
            stmt = stmt.where(models.FreezeRequest.case_id == case_id)
        if open_only:
            stmt = stmt.where(models.FreezeRequest.status.in_(OPEN_STATUSES))
        stmt = stmt.order_by(models.FreezeRequest.updated_at.desc())
        return [summary(r) for r in s.scalars(stmt)]
