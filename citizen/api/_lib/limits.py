"""Rate limits and sign-in delays, counted in citizen_attempts.

One row per kind and key (a keyed hash of a connection or an NCRP number),
counted in a window and updated in place. Wrong tracking codes for an NCRP
number, or from one connection, are free a few times; then each try waits
twice as long as the last, up to MAX_WAIT. A window with no tries for a day
starts again at zero: nobody is ever locked out for good.
"""
from __future__ import annotations

from . import web
from .db import DB

HOUR, WINDOW = 3_600, 86_400
# kind: (tries allowed, in seconds)
RATES = {"complaint-client": (5, WINDOW), "complaint-ncrp": (3, WINDOW), "message-case": (10, WINDOW), "message-client": (30, WINDOW),
         "payment-client": (20, HOUR), "signin-client-all": (60, HOUR)}
FREE_TRIES = {"signin-ncrp": 5, "signin-client": 10}
FIRST_WAIT, MAX_WAIT = 30, HOUR
SESSION_SECONDS = 30 * 60
# Complaints one NCRP number may hold in all. Sign-in checks every one of
# them (so another complaint under the number never shuts the first out),
# and always this many scrypt checks, so the time it takes says nothing.
CODES_PER_NCRP = 8

_UPSERT = """
INSERT INTO citizen_attempts (kind, key_hash, count, first_at, last_at) VALUES (?, ?, 1, ?, ?)
ON CONFLICT (kind, key_hash) DO UPDATE SET
  count = CASE WHEN excluded.first_at - citizen_attempts.first_at > ? THEN 1 ELSE citizen_attempts.count + 1 END,
  first_at = CASE WHEN excluded.first_at - citizen_attempts.first_at > ? THEN excluded.first_at
             ELSE citizen_attempts.first_at END,
  last_at = excluded.last_at
"""


def _count(db: DB, kind: str, key: str, window: int) -> tuple[int, int]:
    """(tries in the window, when the last one was)."""
    row = db.one("SELECT count, first_at, last_at FROM citizen_attempts WHERE kind = ? AND key_hash = ?", kind, key)
    if not row or web.now() - row["first_at"] > window:
        return 0, 0
    return row["count"], row["last_at"]


def hit(db: DB, kind: str, key: str, window: int = WINDOW) -> None:
    t = web.now()
    db.run(_UPSERT, kind, key, t, t, window, window)


def allow(db: DB, kind: str, value: str) -> None:
    """Count one try of `kind` by `value`, refusing it past the kind's rate."""
    limit, window = RATES[kind]
    key = web.keyed(kind, value)
    hit(db, kind, key, window)
    count, _ = _count(db, kind, key, window)
    if count > limit:
        row = db.one("SELECT first_at FROM citizen_attempts WHERE kind = ? AND key_hash = ?", kind, key)
        raise web.Refused(429, "Too many tries for now. Please try again later.",
                          retry_after=row["first_at"] + window - web.now())


def signin_wait(db: DB, keys: dict[str, str]) -> int:
    """Seconds before another sign-in may be tried, for any of {kind: key}."""
    wait = 0
    for kind, key in keys.items():
        count, last = _count(db, kind, key, WINDOW)
        if count >= FREE_TRIES[kind]:
            delay = min(FIRST_WAIT * 2 ** min(count - FREE_TRIES[kind], 20), MAX_WAIT)
            wait = max(wait, last + delay - web.now())
    return wait


def signin_failed(db: DB, keys: dict[str, str]) -> None:
    for kind, key in keys.items():
        hit(db, kind, key)


def signin_cleared(db: DB, kind: str, key: str) -> None:
    db.run("UPDATE citizen_attempts SET count = 0 WHERE kind = ? AND key_hash = ?", kind, key)
