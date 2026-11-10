"""The audit trail: what was done to which case, and by whom (R24).

Every action that reads, exports or changes a case records it:

    from .. import audit

    audit.record("case.export", case_id=case_id, detail={"format": "pdf"})

That writes one log line, which names the event and the case but never
what the detail says, and appends a row to the
audit_events table (a read that changes nothing, in LOG_ONLY, is the log
line alone). Who did it is not a parameter: it is taken from the
request (ActorMiddleware), so a route never passes it and can never pass the
wrong one: a signed-in officer as "officer:<id>" with their unit's id, by
number, never a name or an e-mail; anyone else as their browser. Work in a
thread of its own (a background trace, a batch) says whose it is with
`acting_as`; anything else is "system".

The table is append-only and hash-chained. Each row stores the hash of the
row before it (64 zeros for the first) and its own:

    row_hash = sha256(prev_hash + canonical JSON of the row without row_hash)

so editing, deleting or reordering any row breaks the chain from there on,
and verify() names the first seq where it breaks. Rows are added one at a
time: a lock in this process, and in the store a write lock taken before the
last row is read (SQLite: BEGIN IMMEDIATE; Postgres: an advisory lock), so
two writers can never both build on the same row. The seq primary key is
the backstop: a second row with the same seq is refused, and retried.

`detail` is cleaned before it is stored, as log_safety.py cleans the
logs: a key that names a secret, a token, a password, a session, a webhook,
a URL, an NCRP number or a case reference has its value removed (unless it
is a plain yes or no); a case_id that is not an id is dropped; strings (keys
too) have configured secrets and secret-shaped text removed, URLs and
NCRP-shaped numbers replaced, and addresses and hashes masked; an NCRP-sized
whole number is replaced.

The detail is kept in the table and nowhere else. The log line carries no
detail value, cleaned or not: only "sha256:" and the first 12 hex digits of
the hash of the stored detail text, which ties the line to its row.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import Headers
from starlette.requests import HTTPConnection

from . import accounts, log_safety, models, ownership

logger = logging.getLogger("exchequer.audit")

_EVENT_RE = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")
GENESIS = "0" * 64
# Any fixed number other than models.MIGRATION_LOCK_KEY.
LOCK_KEY = 727202624
DEMO_UNIT = "demo"  # auth.DEMO_UNIT: a demo caller has no unit

Actor = tuple[str, str | None]
SYSTEM: Actor = ("system", None)
_lock = threading.Lock()

# -- who ---------------------------------------------------------------------


def actor_for(owner_hash: str | None, officer: tuple[int | None, int | None] | None = None) -> Actor:
    """An officer (officer_id, unit_id) by id, else the demo identity of a
    browser: its owner hash, never its key."""
    if officer and officer[0] is not None:
        return f"officer:{officer[0]}", None if officer[1] is None else str(officer[1])
    return f"demo:{owner_hash or 'anonymous'}", DEMO_UNIT


class _FromRequest:
    """A request's actor, worked out when its first row is written: the
    officer its session cookie signs in (as auth.current_user reads it),
    else its browser. Requests that record nothing never look the session up."""

    def __init__(self, owner_hash: str | None, session: str | None) -> None:
        self.owner_hash, self.session, self.found = owner_hash, session, None

    def resolve(self) -> Actor:
        if self.found is None:
            signed = accounts.signed_in(self.session) if self.session else None
            officer = signed[0] if signed is not None and not signed[0].must_change_password else None
            self.found = actor_for(self.owner_hash, (officer.id, officer.unit_id) if officer else None)
        return self.found


_actor: ContextVar[Actor | _FromRequest] = ContextVar("audit_actor", default=SYSTEM)


def _current() -> Actor:
    found = _actor.get()
    return found.resolve() if isinstance(found, _FromRequest) else found


@contextmanager
def acting_as(owner_hash: str | None, officer: tuple[int | None, int | None] | None = None) -> Iterator[None]:
    """Record what runs inside as this officer (officer_id, unit_id), or,
    for a demo caller, as the browser with this owner hash."""
    token = _actor.set(actor_for(owner_hash, officer))
    try:
        yield
    finally:
        _actor.reset(token)


class ActorMiddleware:
    """Every request is recorded as its signed-in officer, else as the browser that sent it."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        session = HTTPConnection(scope).cookies.get(accounts.COOKIE)
        token = _actor.set(_FromRequest(ownership.owner_hash_from_headers(Headers(scope=scope)), session))
        try:
            await self.app(scope, receive, send)
        finally:
            _actor.reset(token)


# -- what a row may hold --------------------------------------------------------

_SECRET_KEY = re.compile(r"(?i)token|secret|passw|api[_-]?key|webhook|url|ncrp|reference|cookie|session|"
                         r"credential|authori[sz]ation|bearer|demo[_-]?(code|pass)|signing")
_URL = re.compile(r"(?i)\b(?:https?|wss?|ftp)://\S+")
_NCRP_SHAPE = re.compile(r"\b\d{10,20}\b")
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9._~+/=-]{20,}")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
REDACTED = "<redacted>"


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        # A yes/no cannot carry a secret: {"webhook": False} keeps its answer.
        return {_clean(str(k)): REDACTED if _SECRET_KEY.search(str(k)) and not isinstance(v, bool) else _clean(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        if _UUID.fullmatch(value):  # an id, even one whose last group is all digits
            return value
        cleaned = _NCRP_SHAPE.sub("<number>", log_safety.redact(_URL.sub("<url>", value)))
        if _TOKEN_SHAPE.fullmatch(cleaned):
            return REDACTED
        return cleaned[:500]
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) >= 10**9:
        return "<number>"  # an NCRP number sent as a number
    return value


# A case id is a uuid4, or a short slug ("demo-11"). Anything else (a path
# segment someone typed, an NCRP number) is not kept: the column is String(36).
_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,35}")
_LONG_NUMBER = re.compile(r"\d{10}")


def _case_id(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    if _UUID.fullmatch(value) or (_CASE_ID.fullmatch(value) and not _LONG_NUMBER.search(value)):
        return value
    return None


# Reads that change nothing, which anyone may send without a code or a limit:
# a log line each, never a row, or a loop could grow the permanent table
# without end (its oldest rows can never be pruned without breaking verify).
LOG_ONLY = frozenset({"request.list", "case.letters_list", "case.recheck_read"})

# -- the chain -------------------------------------------------------------------

_FIELDS = ("seq", "at", "actor", "unit_id", "action", "case_id", "prev_hash")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def row_hash(row: dict[str, Any]) -> str:
    """The hash `row` should carry; its `detail` is the stored JSON text."""
    body = {k: row[k] for k in _FIELDS}
    body["detail"] = json.loads(row["detail"])
    return hashlib.sha256((row["prev_hash"] + _canonical(body)).encode()).hexdigest()


def _write_lock(conn: Any) -> None:
    if conn.dialect.name == "sqlite":
        conn.exec_driver_sql("BEGIN IMMEDIATE")
    elif conn.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})


def _append(action: str, case_id: str | None, detail: str) -> int:
    table = models.AuditEvent.__table__
    actor, unit = _current()
    with _lock:
        for attempt in range(5):
            try:
                with models.engine().connect() as conn:
                    _write_lock(conn)
                    last = conn.execute(select(table.c.seq, table.c.row_hash)
                                        .order_by(table.c.seq.desc()).limit(1)).first()
                    row = {"seq": last[0] + 1 if last else 1, "prev_hash": last[1] if last else GENESIS,
                           "at": datetime.now(tz=timezone.utc).isoformat(timespec="microseconds"),
                           "actor": actor, "unit_id": unit, "action": action, "case_id": case_id,
                           "detail": detail}
                    conn.execute(insert(table).values(**row, row_hash=row_hash(row)))
                    conn.commit()
                    return row["seq"]
            except IntegrityError:  # another process took this seq first
                if attempt == 4:
                    raise
    raise AssertionError("unreachable")


def record(event: str, *, case_id: str | None = None, detail: dict[str, Any] | None = None) -> None:
    """Record that `event` happened, to `case_id` if it concerns one."""
    if not isinstance(event, str) or not _EVENT_RE.match(event) or len(event) > 64:
        raise ValueError(f"Audit event {event!r} must be dotted lower case, like 'case.export'")
    if detail is not None and not isinstance(detail, dict):
        raise TypeError(f"Audit detail must be a dict, not {type(detail).__name__}")
    # Raises on anything JSON cannot hold (a datetime, NaN): the row hashes this.
    stored = _canonical(_clean(detail or {}))
    case_id = _case_id(case_id)
    # The detail stays in the table: the line ties itself to the row by a hash.
    logger.info("audit %s case=%s detail=sha256:%s", event, case_id or "-",
                hashlib.sha256(stored.encode()).hexdigest()[:12])
    if event in LOG_ONLY:
        return
    try:
        _append(event, case_id, stored)
    except Exception as exc:  # noqa: BLE001 -- the log line above stands; the action itself is not undone
        # Its kind, not its message: a store error can quote the statement's parameters.
        logger.error("Audit event %s could not be stored: %s", event, type(exc).__name__)


def verify() -> dict[str, Any]:
    """Recompute the whole chain: {ok, rows, first_bad_seq}. A missing row
    is reported by the seq it should have had."""
    table = models.AuditEvent.__table__
    count, expected, prev, bad, after = 0, 1, GENESIS, None, 0
    with models.engine().connect() as conn:
        while True:
            page = conn.execute(select(table).where(table.c.seq > after)
                                .order_by(table.c.seq).limit(1000)).mappings().all()
            if not page:
                break
            for row in page:
                count += 1
                if bad is None:
                    if row["seq"] != expected:
                        bad = expected
                    elif row["prev_hash"] != prev or _hash_or_none(dict(row)) != row["row_hash"]:
                        bad = row["seq"]
                prev, expected = row["row_hash"], row["seq"] + 1
            after = page[-1]["seq"]
    return {"ok": bad is None, "rows": count, "first_bad_seq": bad}


def _hash_or_none(row: dict[str, Any]) -> str | None:
    try:
        return row_hash(row)
    except (ValueError, TypeError):  # detail no longer JSON
        return None


OTHER_BROWSER = "another browser"


def events_for(case_id: str, viewer: str | None = None, limit: int = 1000,
               officer_id: int | None = None, unit_id: int | None = None) -> list[dict[str, Any]]:
    """A case's events, oldest first, as the browser with owner hash `viewer`
    (signed in as `officer_id`, if it is) may see them: its own actor,
    "system" and, for an officer of the unit `unit_id` that traced the case,
    that unit's officers as stored; anyone else as "another browser", so an
    owner cannot follow one stranger across cases."""
    own = {actor_for(viewer)[0] if viewer else None, actor_for(None, (officer_id, None))[0] if officer_id else None}
    own.discard(None)
    table = models.AuditEvent.__table__
    with models.engine().connect() as conn:
        found = conn.execute(select(table).where(table.c.case_id == case_id)
                             .order_by(table.c.seq).limit(limit)).mappings().all()
    return [{**row, "detail": json.loads(row["detail"]),
             "actor": row["actor"] if row["actor"] in own | {SYSTEM[0]} or _same_unit(row, unit_id)
             else OTHER_BROWSER} for row in found]


def _same_unit(row: Any, unit_id: int | None) -> bool:
    return unit_id is not None and row["actor"].startswith("officer:") and row["unit_id"] == str(unit_id)
