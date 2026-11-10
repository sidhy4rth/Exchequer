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
  awaiting_signoff  an urgent freeze letter waits for a second officer
  ready         a second officer of the drafter's unit approved it
  sent          sent; waiting for a reply (flagged after FOLLOW_UP_DAYS)
  acknowledged  the recipient replied and is looking at it
  frozen        funds frozen (amount_frozen says how much)
  declined      the recipient will not act
  closed        nothing more to do

An urgent freeze letter (any "-freeze" kind) asks for money to be held now,
before a formal request, so a forged one is the cheapest fake police request
there is. It goes drafted -> awaiting_signoff -> ready, and only a second
signed-in officer or supervisor of the unit that drafted it makes it ready
(sign_off): never the drafter, an admin or a demo caller. Until then it
cannot be logged as sent.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm.exc import StaleDataError

from . import models

STATUSES = ("drafted", "awaiting_signoff", "ready", "sent", "acknowledged", "frozen", "declined", "closed")
OPEN_STATUSES = ("drafted", "awaiting_signoff", "ready", "sent", "acknowledged")
SIGNOFF_STATES = ("awaiting_signoff", "ready")
SIGNER_ROLES = ("officer", "supervisor")
NEEDS_SIGNOFF = "An urgent freeze letter needs a second officer's sign-off before it is ready to send."
NOT_URGENT = "Only an urgent freeze letter needs a second officer's sign-off."
NO_UNIT = ("This letter was drafted without signing in, so no unit's officer can sign it off. "
           "Sign in and draft it again.")
SIGN_IN_TO_ASK = ("An urgent freeze letter needs a signed-in drafter and a second officer of the same unit: "
                  "sign in to ask for a sign-off.")
# The first two are the urgent freeze letters (request_letters.LETTERS): each
# letter the tool drafts can be logged as sent under its own name.
KINDS = ("exchange", "tether", "other", "exchange-freeze", "tether-freeze", "instant", "instant-freeze")
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


class SignoffRefused(RequestError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def needs_signoff(kind: str) -> bool:
    return kind.endswith("-freeze")


def _check_status(kind: str, status: str, signed: bool) -> None:
    """Whether a request of `kind` may move to `status` (STATUSES checked first)."""
    if not needs_signoff(kind):
        if status in SIGNOFF_STATES:
            raise RequestError(NOT_URGENT)
    elif status == "ready":
        raise RequestError("Only a second officer's sign-off makes an urgent freeze letter ready.")
    elif status in ("drafted", "awaiting_signoff") and signed:
        raise RequestError("This letter is already signed off by a second officer.")
    elif status not in ("drafted", "awaiting_signoff", "closed") and not signed:
        raise RequestError(NEEDS_SIGNOFF)


def refusal(r: models.FreezeRequest, user: Any) -> tuple[int, str] | None:
    """Why `user` may not sign `r` off now, with the HTTP status; None if they may."""
    if not needs_signoff(r.kind):
        return 400, NOT_URGENT
    if r.unit_id is None:  # first: no one could ever sign it, demo caller or not
        return 403, NO_UNIT
    if user.demo:
        return 403, "A demo user cannot sign off a freeze letter: a second officer must sign in to their own account."
    if r.unit_id != user.unit_id:
        return 403, "Only an officer of the unit that drafted this letter can sign it off."
    if r.officer_id == user.officer_id:
        return 403, "You drafted this letter: a second officer of your unit must sign it off."
    if user.role not in SIGNER_ROLES:
        return 403, "Only an officer or a supervisor can sign off a freeze letter."
    if r.status != "awaiting_signoff":
        return 409, "This letter is not waiting for a sign-off."
    return None


def ask_reason(viewer: Any) -> str | None:
    """Why `viewer` may not ask for a sign-off on a letter they draft now."""
    return SIGN_IN_TO_ASK if getattr(viewer, "unit_id", None) is None else None


def _now() -> str:
    return models.utc_now_iso()


def summary(r: models.FreezeRequest, viewer: Any = None) -> dict[str, Any]:
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
        "needs_signoff": needs_signoff(r.kind),
        "signoff": {"by": r.signed_off_name, "at": r.signed_off_at} if r.signed_off_at else None,
        **_viewed(r, viewer),
    }


def _viewed(r: models.FreezeRequest, viewer: Any) -> dict[str, Any]:
    """What `viewer` may do with `r`: change it (their browser's), sign it off."""
    if viewer is None:
        return {"mine": True}
    no = refusal(r, viewer)
    return {"mine": r.owner_hash == viewer.owner_hash, "can_sign_off": no is None,
            "signoff_reason": no[1] if no and needs_signoff(r.kind) else None,
            "ask_reason": NO_UNIT if needs_signoff(r.kind) and r.unit_id is None else None}


def create(owner: str, case_id: str, recipient: str, kind: str, address: str = "",
           asset: str = "", status: str = "drafted", viewer: Any = None) -> dict[str, Any]:
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
    _check_status(kind, status, signed=False)
    if status == "awaiting_signoff" and (no := ask_reason(viewer)):
        raise RequestError(no)
    with models.session() as s:
        if s.scalar(select(models.Case.id).where(models.Case.id == case_id)) is None:
            raise RequestError("No case with that id.")
    now = _now()
    r = models.FreezeRequest(
        id=str(uuid.uuid4()), owner_hash=owner, case_id=case_id, recipient=recipient, kind=kind,
        status=status, address=(address or "")[:64], asset=(asset or "")[:16],
        sent_at=now if status == "sent" else None, created_at=now, updated_at=now,
        history_json=json.dumps([{"at": now, "status": status}]),
        officer_id=getattr(viewer, "officer_id", None), unit_id=getattr(viewer, "unit_id", None),
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
        return summary(r, viewer)


def update(owner: str, request_id: str, changes: dict[str, Any], viewer: Any = None) -> dict[str, Any] | None:
    """Apply `changes`; None if the request is not this owner's. Two updates
    at once both land: the second re-reads and re-applies on its next try."""
    for _ in range(WRITE_TRIES):
        try:
            return _update_once(owner, request_id, changes, viewer)
        except StaleDataError:
            continue
    raise RequestConflict(request_id)


def _update_once(owner: str, request_id: str, changes: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    with models.session() as s:
        r = s.get(models.FreezeRequest, request_id)
        if r is None or r.owner_hash != owner:
            return None
        history = json.loads(r.history_json or "[]")
        now = _now()
        moved = False
        status = changes.get("status")
        if status is not None:
            if status not in STATUSES:
                raise RequestError(f"status must be one of {', '.join(STATUSES)}.")
            if status != r.status:
                _check_status(r.kind, status, signed=r.signed_off_at is not None)
                if status == "awaiting_signoff" and r.unit_id is None:
                    raise RequestError(NO_UNIT)  # no unit's officer could ever sign it
                moved = True
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
        return {**summary(r, viewer), "moved": moved}


def sign_off(request_id: str, user: Any) -> dict[str, Any] | None:
    """A second officer approves an urgent freeze letter: awaiting_signoff ->
    ready. None if there is no such request; SignoffRefused says why not."""
    for _ in range(WRITE_TRIES):
        try:
            with models.session() as s:
                r = s.get(models.FreezeRequest, request_id)
                if r is None:
                    return None
                if (no := refusal(r, user)) is not None:
                    raise SignoffRefused(*no)
                now = _now()
                r.status, r.updated_at, r.signed_off_at = "ready", now, now
                r.signed_off_by, r.signed_off_name = user.officer_id, s.get(models.Officer, user.officer_id).name
                r.history_json = json.dumps([*json.loads(r.history_json or "[]"), {"at": now, "status": "ready"}][-HISTORY_MAX:])
                s.commit()
                s.refresh(r)
                return summary(r, user)
        except StaleDataError:
            continue
    raise RequestConflict(request_id)


def approval(case_id: str, kind: str, user: Any) -> dict[str, Any] | None:
    """The sign-off on the caller's (or their unit's) open `kind` request for the case, if any."""
    with models.session() as s:
        stmt = select(models.FreezeRequest).where(
            models.FreezeRequest.case_id == case_id, models.FreezeRequest.kind == kind,
            models.FreezeRequest.signed_off_at.is_not(None), models.FreezeRequest.status != "closed",
            _readable(user)).order_by(models.FreezeRequest.signed_off_at.desc())
        r = s.scalars(stmt).first()
        return {"by": r.signed_off_name, "at": r.signed_off_at} if r else None


def _readable(user: Any) -> Any:
    """The rows `user` may read: their browser's, and their unit's."""
    own = models.FreezeRequest.owner_hash == user.owner_hash
    return own if user.unit_id is None else or_(own, models.FreezeRequest.unit_id == user.unit_id)


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


def list_for(owner: str, case_id: str | None = None, open_only: bool = False,
             viewer: Any = None) -> list[dict[str, Any]]:
    """The browser's requests; for a signed-in `viewer` and one case, also
    their unit's, so a second officer finds a letter to sign off."""
    with models.session() as s:
        stmt = select(models.FreezeRequest).where(
            _readable(viewer) if viewer is not None and case_id
            else models.FreezeRequest.owner_hash == owner)
        if case_id:
            stmt = stmt.where(models.FreezeRequest.case_id == case_id)
        if open_only:
            stmt = stmt.where(models.FreezeRequest.status.in_(OPEN_STATUSES))
        stmt = stmt.order_by(models.FreezeRequest.updated_at.desc())
        return [summary(r, viewer) for r in s.scalars(stmt)]
