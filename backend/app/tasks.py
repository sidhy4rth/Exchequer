"""A task list per case (suite feature 6).

A case is a list of things still to do as much as a trace: send the notice to
the bank, get the court's order on the seized money, collect the phone
extraction, chase the exchange that has not answered. This keeps that list with
the case: what the task is, who it is assigned to (a name, never an account
detail), by when, and what came of it.

A task is open, done or dropped. Dropping one, or opening it again, needs a
reason: a task that quietly disappears is how a deadline is missed. Nothing is
deleted, and every change is a history entry with who and when, so the list
shows what was done in the case and in what order.

Free-text fields refuse private keys and seed phrases (assets.looks_like_secret),
as the asset and exhibit registers do.

Suggestions (suggestions()) are tasks the case's own records already call for:
a request sent with no reply after a week, an urgent freeze letter waiting for
its sign-off or approved and not sent, a freeze not yet in the asset register,
and held funds with no court order on custody. They are worked out each time
from those records, never stored, and name only what the records say. Taking
one up adds a task carrying the suggestion's key (source); so does declining
it, as a task dropped with the reason, so a suggestion never quietly returns.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm.exc import StaleDataError

from . import assets, freeze_requests, models
from .assets import NOT_A_KEY, looks_like_secret
from .display_text import one_line

IST = timezone(timedelta(hours=5, minutes=30), "IST")
CLOSED = ("done", "dropped")
STATUSES = ("open", *CLOSED)
TEXT = {"title": (200, "what has to be done"), "assignee": (120, "who it is assigned to"),
        "notes": (2000, "the notes"), "note": (300, "why")}
CHANGEABLE = ("title", "assignee", "due_on", "status", "notes", "note")
DUE_YEARS_AHEAD = 10  # a due date further out is a typo
MAX_PER_OWNER, MAX_TOTAL, HISTORY_MAX = 2000, 200_000, 500
WRITE_TRIES = 3  # two writes to one task at once: the second re-reads and tries again


class TaskError(ValueError):
    """What was given is missing, malformed or not allowed; the message says which."""


class TaskConflict(RuntimeError):
    """Another write to the same task kept landing first; try again."""


def _now() -> str:
    return models.utc_now_iso()


def _today() -> date:
    return datetime.now(tz=IST).date()


def _who(user: Any) -> str:
    return getattr(user, "id", None) or "unknown"


def _text(fields: dict[str, Any], key: str, required: bool = False) -> str:
    limit, what = TEXT[key]
    value = one_line(fields.get(key) or "").strip()
    if required and not value:
        raise TaskError(f"Enter {what}.")
    if len(value) > limit:
        raise TaskError(f"{what[0].upper()}{what[1:]} is longer than {limit} characters.")
    if looks_like_secret(value):
        raise TaskError(NOT_A_KEY)
    return value


def _due_on(raw: Any) -> str:
    """A date (YYYY-MM-DD), or "" for none. A past date is allowed: a task can be entered late."""
    if raw in (None, ""):
        return ""
    try:
        day = date.fromisoformat(str(raw))
    except ValueError as exc:
        raise TaskError("Enter the due date as YYYY-MM-DD.") from exc
    if day.year < 2009:
        raise TaskError("The due date is before any cryptocurrency existed.")
    if day > _today() + timedelta(days=365 * DUE_YEARS_AHEAD):
        raise TaskError(f"The due date is more than {DUE_YEARS_AHEAD} years away.")
    return day.isoformat()


def _readable(user: Any) -> Any:
    """The tasks `user` may read and change: their browser's, and their unit's."""
    own = models.CaseTask.owner_hash == user.owner_hash
    return own if getattr(user, "unit_id", None) is None else or_(own, models.CaseTask.unit_id == user.unit_id)


def summary(r: models.CaseTask) -> dict[str, Any]:
    days_left = (date.fromisoformat(r.due_on) - _today()).days if r.due_on else None
    return {
        "task_id": r.id, "case_id": r.case_id, "title": r.title, "assignee": r.assignee, "due_on": r.due_on,
        "status": r.status, "notes": r.notes, "source": r.source or "",
        "created_at": r.created_at, "updated_at": r.updated_at,
        "days_left": days_left if r.status == "open" else None,
        "overdue": r.status == "open" and days_left is not None and days_left < 0,
        "history": json.loads(r.history_json or "[]"),
    }


def create(owner: str, case_id: str, fields: dict[str, Any], viewer: Any = None) -> dict[str, Any]:
    """Add a task. With `source`, it is the suggestion by that key (its title and
    due date come from the case's records, not the caller); with `note` as well,
    the suggestion is declined: the task is added already dropped, with that reason."""
    source = str(fields.get("source") or "").strip()
    suggestion = _suggestion(viewer, case_id, source) if source else None
    row = {
        "title": suggestion["title"] if suggestion else _text(fields, "title", required=True),
        "assignee": _text(fields, "assignee"),
        "due_on": _due_on(fields.get("due_on")) or (suggestion["due_on"] if suggestion else ""),
        "notes": _text(fields, "notes"),
    }
    note = _text(fields, "note") if fields.get("note") else ""
    if note and not suggestion:
        raise TaskError("Only a suggestion can be declined with a reason; add the task, then drop it.")
    with models.session() as s:
        if s.scalar(select(models.Case.id).where(models.Case.id == case_id)) is None:
            raise TaskError("No case with that id.")
        count = select(func.count()).select_from(models.CaseTask)
        if s.scalar(count.where(models.CaseTask.owner_hash == owner)) >= MAX_PER_OWNER:
            raise TaskError(f"This browser already has {MAX_PER_OWNER} tasks on record.")
        if s.scalar(count) >= MAX_TOTAL:
            raise TaskError("The task list is full on this deployment; ask its operator.")
        now = _now()
        history: list[dict[str, Any]] = [{"at": now, "by": _who(viewer), "action": "added",
                                          **({"from": "suggestion"} if suggestion else {})}]
        if note:
            history.append({"at": now, "by": _who(viewer), "action": "dropped", "changed": ["status"], "note": note})
        r = models.CaseTask(
            id=str(uuid.uuid4()), owner_hash=owner, case_id=case_id, status="dropped" if note else "open",
            source=source, officer_id=getattr(viewer, "officer_id", None), unit_id=getattr(viewer, "unit_id", None),
            created_at=now, updated_at=now, history_json=json.dumps(history), **row,
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        return summary(r)


def _append(r: models.CaseTask, entry: dict[str, Any]) -> None:
    """Add to the task's history. A full one refuses: dropping old entries would lose how it began."""
    history = json.loads(r.history_json or "[]")
    if len(history) >= HISTORY_MAX:
        raise TaskError(f"This task's history is full ({HISTORY_MAX} entries); add a new task instead.")
    history.append(entry)
    r.history_json = json.dumps(history)
    r.updated_at = entry["at"]


def update(task_id: str, changes: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    """Change, close, reopen or add a note to a task; None when the viewer has none by that id."""
    unknown = set(changes) - set(CHANGEABLE)
    if unknown:
        raise TaskError(f"These cannot be changed: {', '.join(sorted(unknown))}.")
    for _ in range(WRITE_TRIES):
        try:
            return _update_once(task_id, changes, viewer)
        except StaleDataError:
            continue
    raise TaskConflict(task_id)


def _action(old: str, new: str) -> str:
    if new == old:
        return "changed"
    return "reopened" if new == "open" else new


def _update_once(task_id: str, changes: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    with models.session() as s:
        r = s.scalars(select(models.CaseTask).where(models.CaseTask.id == task_id, _readable(viewer))).first()
        if r is None:
            return None
        clean: dict[str, str] = {key: _text(changes, key, required=key == "title")
                                 for key in ("title", "assignee", "notes") if key in changes}
        if "due_on" in changes:
            clean["due_on"] = _due_on(changes["due_on"])
        status = changes.get("status")
        if status is not None:
            if status not in STATUSES:
                raise TaskError(f"status must be one of {', '.join(STATUSES)}.")
            clean["status"] = status
        changed = sorted(k for k, v in clean.items() if getattr(r, k) != v)
        if r.status in CLOSED and set(changed) - {"status", "notes"}:
            raise TaskError(f"This task is {r.status}; open it again to change it, or add a note.")
        note = _text(changes, "note") if "note" in changes else ""
        new_status = clean.get("status", r.status)
        if "status" in changed and new_status != "done" and not note:
            # Dropping a task or opening it again is a decision someone must be able to explain.
            raise TaskError("Say why: dropping a task, or opening it again, needs a reason.")
        action = _action(r.status, new_status)
        for key in changed:
            setattr(r, key, clean[key])
        if changed or note:  # a note on its own is kept too: it is how a closed task is added to
            entry: dict[str, Any] = {"at": _now(), "by": _who(viewer), "action": action if changed else "noted"}
            if changed:
                entry["changed"] = changed
            if note:
                entry["note"] = note
            _append(r, entry)
            s.commit()
            s.refresh(r)
        out = summary(r)
        out["changed"] = changed
        out["noted"] = bool(note) and not changed
        return out


def list_for(viewer: Any, case_id: str) -> list[dict[str, Any]]:
    """Open tasks first, soonest due first (no date last); then closed ones, latest first."""
    if getattr(viewer, "owner_hash", None) is None and getattr(viewer, "unit_id", None) is None:
        return []
    with models.session() as s:
        rows = s.scalars(select(models.CaseTask).where(models.CaseTask.case_id == case_id, _readable(viewer))).all()
        tasks = [summary(r) for r in rows]
    open_ = sorted((t for t in tasks if t["status"] == "open"), key=lambda t: (t["due_on"] or "9999-12-31", t["created_at"]))
    closed = sorted((t for t in tasks if t["status"] != "open"), key=lambda t: t["updated_at"], reverse=True)
    return open_ + closed


def due_for(viewer: Any, within_days: int = 7) -> list[dict[str, Any]]:
    """Open tasks due within `within_days` days or already overdue, across the
    viewer's cases, most overdue first."""
    if getattr(viewer, "owner_hash", None) is None and getattr(viewer, "unit_id", None) is None:
        return []
    latest = (_today() + timedelta(days=within_days)).isoformat()
    with models.session() as s:
        rows = s.scalars(select(models.CaseTask).where(
            models.CaseTask.status == "open", models.CaseTask.due_on != "",
            models.CaseTask.due_on <= latest, _readable(viewer))
            .order_by(models.CaseTask.due_on, models.CaseTask.created_at).limit(100)).all()
        return [summary(r) for r in rows]


# -- suggestions ---------------------------------------------------------------------------
def _day(iso: str | None) -> str:
    """'2026-11-03T10:00:00+00:00' or '2026-11-03' as '3 Nov 2026'."""
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return ""
    return f"{d.day} {d:%b %Y}"


def _from_requests(viewer: Any, case_id: str, registered: set[str]) -> list[dict[str, Any]]:
    out = []
    for q in freeze_requests.list_for(viewer.owner_hash, case_id, viewer=viewer):
        rid, who = q["request_id"], one_line(q["recipient"] or "the recipient")
        if q["status"] == "sent" and q["follow_up"]:
            out.append({"source": f"request:{rid}:follow_up", "due_on": "",
                        "title": f"Follow up with {who}: no reply in {q['days_waiting']} days",
                        "why": f"Logged as sent on {_day(q['sent_at'])}; no reply has been recorded since."})
        elif q["status"] == "awaiting_signoff":
            out.append({"source": f"request:{rid}:signoff", "due_on": "",
                        "title": f"Get a second officer's sign-off on the urgent freeze letter to {who}",
                        "why": "An urgent freeze letter cannot be sent until a second officer of the unit approves it."})
        elif q["status"] == "ready":
            by = (q.get("signoff") or {}).get("by")
            out.append({"source": f"request:{rid}:send", "due_on": "",
                        "title": f"Send the approved freeze letter to {who}",
                        "why": f"Signed off{f' by {one_line(by)}' if by else ''}; not yet logged as sent."})
        elif q["status"] == "frozen" and rid not in registered:
            out.append({"source": f"request:{rid}:register", "due_on": "",
                        "title": f"Record the funds {who} froze in the asset register",
                        "why": "The request is marked Frozen, and no row in the asset register points to it."})
    return out


def _from_assets(viewer: Any, case_id: str) -> tuple[list[dict[str, Any]], set[str]]:
    """Held funds with no court order on custody yet, and the requests the register already covers."""
    out, registered = [], set()
    for a in assets.list_for(viewer, case_id):
        if a["request_id"]:
            registered.add(a["request_id"])
        if a["status"] == "held" and not a["order_ref"]:
            out.append({"source": f"asset:{a['asset_id']}:order", "due_on": a["deadline"],
                        "title": f"Get the court's order on custody of {a['amount']} {one_line(a['asset'])}",
                        "why": f"Seized on {_day(a['seized_on'])}; the asset register counts the order as due "
                               f"{assets.DEADLINE_DAYS} days later, on {_day(a['deadline'])}."})
    return out, registered


def suggestions(viewer: Any, case_id: str) -> list[dict[str, Any]]:
    """Tasks the case's records call for that no task (open or closed) has taken up yet."""
    if getattr(viewer, "owner_hash", None) is None:
        return []
    held, registered = _from_assets(viewer, case_id)
    found = _from_requests(viewer, case_id, registered) + held
    with models.session() as s:
        taken = set(s.scalars(select(models.CaseTask.source).where(
            models.CaseTask.case_id == case_id, models.CaseTask.source != "", _readable(viewer))).all())
    return [x for x in found if x["source"] not in taken]


def _suggestion(viewer: Any, case_id: str, source: str) -> dict[str, Any]:
    if viewer is None:
        raise TaskError("A suggestion can only be taken up by the browser or unit that can see it.")
    for x in suggestions(viewer, case_id):
        if x["source"] == source:
            return x
    raise TaskError("That suggestion no longer applies to this case (it may already be a task). Reload the list.")
