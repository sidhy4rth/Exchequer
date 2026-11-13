"""The exhibit register: files outside forensic tools produced for a case (suite feature 3).

A phone extraction, a disk image, a memory capture, the tool's own report: the
case relies on each, and a court asks two things of it -- is this the file that
was made, and who has had it since. The register answers both without holding
the file. The officer records the hash the tool printed (SHA-256, and SHA-1 or
MD5 when the tool gives those; the certificate in the BSA's Schedule (s.63(4))
offers all three); later, anyone
can check a file against the record by hashing it in their browser and sending
only the hash (check()). A phone image of many gigabytes never leaves the
officer's machine.

A row records what the file is (kind, label), the tool and its version, the file
name and size, the hashes, who made it and when, where it is kept and who holds
it now. Hand-overs, moves, checks and its end (released or destroyed) are
history entries with who, when and why: a chain of custody. Nothing is deleted,
and the hashes, file and tool never change once recorded.

Free-text fields refuse private keys and seed phrases (assets.looks_like_secret).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm.exc import StaleDataError

from . import models
from .assets import NOT_A_KEY, looks_like_secret
from .display_text import one_line

IST = timezone(timedelta(hours=5, minutes=30), "IST")
KINDS = {
    "phone_extraction": "Phone extraction",
    "disk_image": "Disk image",
    "memory_capture": "Memory capture",
    "tool_report": "Tool report",
    "video": "Video recording",
    "document": "Document",
    "other": "Other",
}
ENDS = ("released", "destroyed")
STATUSES = ("held", *ENDS)
HASHES = {"sha256": (64, "SHA-256"), "sha1": (40, "SHA-1"), "md5": (32, "MD5")}
TEXT = {"label": (200, "what the file is"), "tool": (120, "the tool and its version"),
        "file_name": (200, "the file name"), "made_by": (120, "who made it"),
        "stored_at": (200, "where it is kept"), "holder": (120, "who holds it"),
        "notes": (2000, "the notes"), "note": (300, "why")}
# What may change after an exhibit is recorded; a holder or place changes only with a reason.
CHANGEABLE = ("holder", "stored_at", "status", "notes", "note")
NEEDS_REASON = ("holder", "stored_at", "status")
SIZE_MAX = 10**15  # a petabyte: larger is a typo
MAX_PER_OWNER, MAX_TOTAL, HISTORY_MAX = 1000, 100_000, 1000
WRITE_TRIES = 3  # two writes to one exhibit at once: the second re-reads and tries again


class ExhibitError(ValueError):
    """What was given is missing, malformed or not allowed; the message says which."""


class DuplicateExhibit(ExhibitError):
    """The same file (by hash) is already an exhibit of this case."""


class ExhibitConflict(RuntimeError):
    """Another write to the same exhibit kept landing first; try again."""


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
        raise ExhibitError(f"Enter {what}.")
    if len(value) > limit:
        raise ExhibitError(f"{what[0].upper()}{what[1:]} is longer than {limit} characters.")
    if looks_like_secret(value):
        raise ExhibitError(NOT_A_KEY)
    return value


def _hash(fields: dict[str, Any], key: str) -> str:
    size, name = HASHES[key]
    value = str(fields.get(key) or "").strip().lower()
    if value and not re.fullmatch(rf"[0-9a-f]{{{size}}}", value):
        raise ExhibitError(f"Enter the {name} as {size} hexadecimal characters.")
    return value


def _size(raw: Any) -> int | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, bool):
        raise ExhibitError("Enter the size in bytes as a whole number.")
    try:
        value = int(str(raw).replace(",", "").strip())
    except ValueError as exc:
        raise ExhibitError("Enter the size in bytes as a whole number.") from exc
    if not 0 <= value <= SIZE_MAX:
        raise ExhibitError("The size must be zero or more bytes, and not more than a petabyte.")
    return value


def _made_on(raw: Any) -> str:
    try:
        day = date.fromisoformat(str(raw or ""))
    except ValueError as exc:
        raise ExhibitError("Enter the date the file was made as YYYY-MM-DD.") from exc
    if day > _today():
        raise ExhibitError("The date the file was made is in the future.")
    return day.isoformat()


def _readable(user: Any) -> Any:
    """The exhibits `user` may read and change: their browser's, and their unit's."""
    own = models.Exhibit.owner_hash == user.owner_hash
    return own if getattr(user, "unit_id", None) is None else or_(own, models.Exhibit.unit_id == user.unit_id)


def summary(r: models.Exhibit) -> dict[str, Any]:
    return {
        "exhibit_id": r.id, "case_id": r.case_id, "kind": r.kind, "kind_label": KINDS.get(r.kind, r.kind),
        "label": r.label, "tool": r.tool, "file_name": r.file_name, "size_bytes": r.size_bytes,
        "sha256": r.sha256, "sha1": r.sha1, "md5": r.md5, "made_by": r.made_by, "made_on": r.made_on,
        "stored_at": r.stored_at, "holder": r.holder, "status": r.status, "notes": r.notes,
        "created_at": r.created_at, "updated_at": r.updated_at, "history": json.loads(r.history_json or "[]"),
    }


def create(owner: str, case_id: str, fields: dict[str, Any], viewer: Any = None) -> dict[str, Any]:
    kind = str(fields.get("kind") or "")
    if kind not in KINDS:
        raise ExhibitError(f"Say what kind of file it is: one of {', '.join(KINDS)}.")
    row = {
        "kind": kind,
        "label": _text(fields, "label", required=True),
        "tool": _text(fields, "tool", required=True),
        "file_name": _text(fields, "file_name"),
        "size_bytes": _size(fields.get("size_bytes")),
        **{key: _hash(fields, key) for key in HASHES},
        "made_by": _text(fields, "made_by"),
        "made_on": _made_on(fields.get("made_on")),
        "stored_at": _text(fields, "stored_at"),
        "holder": _text(fields, "holder"),
        "notes": _text(fields, "notes"),
    }
    if not any(row[key] for key in HASHES):
        raise ExhibitError("Enter at least one hash the tool printed: SHA-256, SHA-1 or MD5.")
    with models.session() as s:
        if s.scalar(select(models.Case.id).where(models.Case.id == case_id)) is None:
            raise ExhibitError("No case with that id.")
        # Only among exhibits the viewer may read: the refusal names the twin, and
        # another unit's exhibit is not theirs to learn about.
        same = [getattr(models.Exhibit, key) == row[key] for key in HASHES if row[key]]
        twin = s.scalars(select(models.Exhibit).where(
            models.Exhibit.case_id == case_id, or_(*same), _readable(viewer or _Owner(owner)))).first()
        if twin is not None:
            raise DuplicateExhibit(f"This file is already exhibit {twin.id[:8]} of this case ({twin.label}).")
        count = select(func.count()).select_from(models.Exhibit)
        if s.scalar(count.where(models.Exhibit.owner_hash == owner)) >= MAX_PER_OWNER:
            raise ExhibitError(f"This browser already has {MAX_PER_OWNER} exhibits on record.")
        if s.scalar(count) >= MAX_TOTAL:
            raise ExhibitError("The exhibit register is full on this deployment; ask its operator.")
        now = _now()
        r = models.Exhibit(
            id=str(uuid.uuid4()), owner_hash=owner, case_id=case_id, status="held",
            officer_id=getattr(viewer, "officer_id", None), unit_id=getattr(viewer, "unit_id", None),
            created_at=now, updated_at=now,
            history_json=json.dumps([{"at": now, "by": _who(viewer), "action": "recorded"}]), **row,
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        return summary(r)


class _Owner:
    """A viewer that is only a browser's owner key, for callers that pass no viewer."""

    unit_id = None

    def __init__(self, owner_hash: str) -> None:
        self.owner_hash = owner_hash


def _row(s: Any, exhibit_id: str, viewer: Any) -> models.Exhibit | None:
    return s.scalars(select(models.Exhibit).where(models.Exhibit.id == exhibit_id, _readable(viewer))).first()


def _append(r: models.Exhibit, entry: dict[str, Any]) -> None:
    """Add to the chain of custody. A full one refuses: dropping old entries would lose its first links."""
    history = json.loads(r.history_json or "[]")
    if len(history) >= HISTORY_MAX:
        raise ExhibitError(f"This exhibit's history is full ({HISTORY_MAX} entries); ask the deployment's operator.")
    history.append(entry)
    r.history_json = json.dumps(history)
    r.updated_at = entry["at"]


def _retrying(write: Any, *args: Any) -> Any:
    for _ in range(WRITE_TRIES):
        try:
            return write(*args)
        except StaleDataError:
            continue
    raise ExhibitConflict(args[0])


def update(exhibit_id: str, changes: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    """Hand an exhibit over, move it, end it, or add notes or a note; None when the viewer has none by that id."""
    unknown = set(changes) - set(CHANGEABLE)
    if unknown:
        raise ExhibitError(f"These cannot be changed: {', '.join(sorted(unknown))}.")
    return _retrying(_update_once, exhibit_id, changes, viewer)


def _update_once(exhibit_id: str, changes: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    with models.session() as s:
        r = _row(s, exhibit_id, viewer)
        if r is None:
            return None
        if r.status != "held" and set(changes) - {"notes", "note"}:
            raise ExhibitError(f"This exhibit was already {r.status}; add a note instead.")
        clean = {key: _text(changes, key) for key in ("holder", "stored_at", "notes") if key in changes}
        status = changes.get("status")
        if status is not None and status != r.status:
            if status not in ENDS:
                raise ExhibitError(f"status must be one of {', '.join(ENDS)}.")
            clean["status"] = status
        changed = sorted(k for k, v in clean.items() if getattr(r, k) != v)
        note = _text(changes, "note") if "note" in changes else ""
        if any(k in NEEDS_REASON for k in changed) and not note:
            raise ExhibitError("Say why: a hand-over, a move or an end is part of the chain of custody.")
        for key in changed:
            setattr(r, key, clean[key])
        if changed or note:  # a note on its own is kept too: it is how an ended exhibit is added to
            entry = {"at": _now(), "by": _who(viewer), "action": "changed" if changed else "noted"}
            if changed:
                entry["changed"] = changed
            if note:
                entry["note"] = note
            _append(r, entry)
            s.commit()
            s.refresh(r)
        out = summary(r)
        out["changed"] = changed
        return out


def check(exhibit_id: str, sha256: str, viewer: Any) -> dict[str, Any] | None:
    """Compare a file's SHA-256 (hashed in the browser) with the record, and keep the result."""
    value = _hash({"sha256": sha256}, "sha256")
    if not value:
        raise ExhibitError("Enter the SHA-256 as 64 hexadecimal characters.")
    return _retrying(_check_once, exhibit_id, value, viewer)


def _check_once(exhibit_id: str, value: str, viewer: Any) -> dict[str, Any] | None:
    with models.session() as s:
        r = _row(s, exhibit_id, viewer)
        if r is None:
            return None
        if not r.sha256:
            raise ExhibitError("This exhibit has no SHA-256 on record, so a file cannot be checked against it.")
        result = "match" if value == r.sha256 else "mismatch"
        entry = {"at": _now(), "by": _who(viewer), "action": "checked", "result": result}
        if result == "mismatch":
            entry["sha256_seen"] = value
        _append(r, entry)
        s.commit()
        s.refresh(r)
        return {"result": result, "exhibit": summary(r)}


def list_for(viewer: Any, case_id: str) -> list[dict[str, Any]]:
    if getattr(viewer, "owner_hash", None) is None and getattr(viewer, "unit_id", None) is None:
        return []
    with models.session() as s:
        rows = s.scalars(select(models.Exhibit).where(models.Exhibit.case_id == case_id, _readable(viewer))
                         .order_by(models.Exhibit.made_on, models.Exhibit.created_at)).all()
        return [summary(r) for r in rows]
