"""Officer accounts (R23): units, officers, passwords and sign-in sessions.

Admins create every account; there is no public sign-up. A new account, and
one an admin resets, gets a temporary password that is shown once and must
be changed before the account can do anything else.

* Passwords are hashed with scrypt from the standard library (n=2**15, r=8,
  p=1, a 16-byte random salt), the parameters stored with the hash so they
  can be raised later without breaking the hashes already stored.
* A session is a random 32-byte token in an HttpOnly, SameSite=Strict
  cookie. The store keeps only its SHA-256, so a copy of the database signs
  nobody in. A session ends after 12 idle hours, after 7 days whatever, on
  sign-out, and when an admin resets or deactivates the account.

Without a session cookie nothing here runs: auth.current_user returns the
demo user as before, and the recorded demos stay open to everyone.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .input_rules import plain_text
from .models import Officer, OfficerSession, Unit

OFFICER_ROLES = ("officer", "supervisor", "admin")
COOKIE = "exchequer_session"
# State-changing account routes also need this header: a cross-site form
# cannot send it, and a cross-site fetch() that sets it needs a CORS
# preflight this API never grants with credentials.
CSRF_HEADER = "x-exchequer-request"
SESSION_IDLE = timedelta(hours=12)
SESSION_MAX = timedelta(days=7)
_TOUCH_EVERY = timedelta(minutes=1)  # last_seen_at is written at most this often
LOGIN_FAILED = "That e-mail and password do not match an active account."

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
_MAXMEM = 2**27  # scrypt needs 128 * r * n bytes: 32 MB at the parameters above


class Conflict(Exception):
    """A change that would break an account rule (a taken e-mail, no admin left)."""


def _session() -> Session:
    # Rows read here are handed out after the session closes.
    return Session(models.engine(), expire_on_commit=False)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            maxmem=_MAXMEM, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        name, n, r, p, salt, digest = stored.split("$")
        n, r, p = int(n), int(r), int(p)
        if name != "scrypt" or not (2 <= n <= 2**16 and 1 <= r <= 8 and 1 <= p <= 4):
            return False  # never let a stored value pick an unbounded cost
        want = base64.b64decode(digest, validate=True)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt, validate=True), n=n, r=r, p=p,
                             maxmem=_MAXMEM, dklen=len(want))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


def temporary_password() -> str:
    return secrets.token_urlsafe(15)  # 20 characters, 120 bits


def normal_email(email: str) -> str:
    return email.strip().lower()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def public(officer: Officer, unit: Unit) -> dict[str, Any]:
    """What the API shows of an account: never its password hash."""
    return {"id": officer.id, "email": officer.email, "name": officer.name, "role": officer.role,
            "unit": {"id": unit.id, "name": unit.name}, "active": officer.active,
            "must_change_password": officer.must_change_password,
            "created_at": officer.created_at, "last_login_at": officer.last_login_at}


# -- records ---------------------------------------------------------------------
def create_unit(name: str) -> Unit:
    with _session() as s:
        unit = Unit(name=plain_text(name, 120))
        s.add(unit)
        s.commit()
        s.expunge(unit)
        return unit


def units() -> list[Unit]:
    with _session() as s:
        found = list(s.scalars(select(Unit).order_by(Unit.name)))
        s.expunge_all()
        return found


def unit_limits(unit_id: int) -> dict[str, Any]:
    """The unit's own per-officer limits, {kind: {"per_hour", "per_day"}};
    {} when it has none (or no such unit), so the defaults apply."""
    with _session() as s:
        unit = s.get(Unit, unit_id)
        return json.loads(unit.limits_json) if unit is not None and unit.limits_json else {}


def set_unit_limits(unit_id: int, limits: dict[str, Any]) -> Unit:
    """Replace the unit's own limits ({} goes back to the defaults)."""
    with _session() as s:
        unit = s.get(Unit, unit_id)
        if unit is None:
            raise LookupError("No such unit.")
        unit.limits_json = json.dumps(limits, sort_keys=True) if limits else None
        s.commit()
        s.expunge(unit)
        return unit


def create_officer(email: str, name: str, unit_id: int, role: str,
                   password: str | None = None) -> tuple[Officer, str | None]:
    """(the new account, its one-time temporary password, or None when
    `password` was given). Raises Conflict for a taken e-mail, LookupError
    for a unit that does not exist."""
    if role not in OFFICER_ROLES:
        raise ValueError(f"role must be one of {OFFICER_ROLES}")
    temp = None if password else temporary_password()
    with _session() as s:
        if s.get(Unit, unit_id) is None:
            raise LookupError("No such unit.")
        officer = Officer(email=normal_email(email), name=plain_text(name, 120), unit_id=unit_id, role=role,
                          password_hash=hash_password(password or temp), must_change_password=temp is not None,
                          active=True, created_at=_iso(now()))
        s.add(officer)
        try:
            s.commit()
        except IntegrityError:
            raise Conflict("An account with that e-mail already exists.") from None
        s.expunge(officer)
        return officer, temp


def officers() -> list[tuple[Officer, Unit]]:
    with _session() as s:
        rows = [tuple(r) for r in s.execute(select(Officer, Unit).join(Unit, Officer.unit_id == Unit.id)
                                            .order_by(Officer.email))]
        s.expunge_all()
        return rows


def get_officer(officer_id: int) -> tuple[Officer, Unit] | None:
    with _session() as s:
        officer = s.get(Officer, officer_id)
        if officer is None:
            return None
        unit = s.get(Unit, officer.unit_id)
        s.expunge_all()
        return officer, unit


def admin_exists() -> bool:
    with _session() as s:
        return bool(s.scalar(select(func.count()).select_from(Officer)
                             .where(Officer.role == "admin", Officer.active.is_(True))))


def change_officer(officer_id: int, role: str | None = None, unit_id: int | None = None,
                   active: bool | None = None, reset_password: bool = False) -> str | None:
    """Apply an admin's change; the new temporary password if one was made.
    Raises LookupError (no such officer or unit) or Conflict (no admin left)."""
    with _session() as s:
        officer = s.get(Officer, officer_id)
        if officer is None or (unit_id is not None and s.get(Unit, unit_id) is None):
            raise LookupError("No such officer or unit.")
        stays_admin = (role or officer.role) == "admin" and (officer.active if active is None else active)
        if officer.role == "admin" and officer.active and not stays_admin:
            others = s.scalar(select(func.count()).select_from(Officer).where(
                Officer.role == "admin", Officer.active.is_(True), Officer.id != officer_id))
            if not others:
                raise Conflict("This is the last active admin: make another admin first.")
        temp = temporary_password() if reset_password else None
        officer.role = role or officer.role
        officer.unit_id = officer.unit_id if unit_id is None else unit_id
        officer.active = officer.active if active is None else active
        if temp:
            officer.password_hash, officer.must_change_password = hash_password(temp), True
        if temp or not officer.active:
            s.execute(delete(OfficerSession).where(OfficerSession.officer_id == officer_id))
        s.commit()
        return temp


def set_password(officer_id: int, password: str, keep_token: str) -> None:
    """A new password chosen by its officer; every other session of theirs ends."""
    with _session() as s:
        officer = s.get(Officer, officer_id)
        officer.password_hash, officer.must_change_password = hash_password(password), False
        s.execute(delete(OfficerSession).where(OfficerSession.officer_id == officer_id,
                                               OfficerSession.token_sha256 != _digest(keep_token)))
        s.commit()


_dummy_hash: str | None = None


def authenticate(email: str, password: str) -> tuple[Officer, Unit] | None:
    """The active account with this e-mail and password, else None. An
    unknown e-mail costs the same hash as a known one."""
    global _dummy_hash
    with _session() as s:
        officer = s.scalar(select(Officer).where(Officer.email == normal_email(email)))
        if officer is None:
            _dummy_hash = _dummy_hash or hash_password(secrets.token_urlsafe(16))
            verify_password(password, _dummy_hash)
            return None
        if not verify_password(password, officer.password_hash) or not officer.active:
            return None
        unit = s.get(Unit, officer.unit_id)
        s.expunge_all()
        return officer, unit


# -- sessions --------------------------------------------------------------------
def start_session(officer_id: int) -> str:
    """A new session's cookie token. Only its SHA-256 is stored."""
    token, moment = secrets.token_urlsafe(32), now()
    with _session() as s:
        s.add(OfficerSession(token_sha256=_digest(token), officer_id=officer_id, created_at=_iso(moment),
                             last_seen_at=_iso(moment), expires_at=_iso(moment + SESSION_MAX)))
        s.get(Officer, officer_id).last_login_at = _iso(moment)
        s.commit()
    return token


def signed_in(token: str | None) -> tuple[Officer, Unit] | None:
    """The officer whose live session this token is, else None. A session
    past its idle or absolute limit, or of an inactive account, is deleted."""
    if not token or len(token) > 128:
        return None
    moment = now()
    with _session() as s:
        row = s.scalar(select(OfficerSession).where(OfficerSession.token_sha256 == _digest(token)))
        if row is None:
            return None
        officer = s.get(Officer, row.officer_id)
        seen = datetime.fromisoformat(row.last_seen_at)
        if (moment >= datetime.fromisoformat(row.expires_at) or moment - seen >= SESSION_IDLE
                or officer is None or not officer.active):
            s.delete(row)
            s.commit()
            return None
        if moment - seen >= _TOUCH_EVERY:
            row.last_seen_at = _iso(moment)
            s.commit()
        unit = s.get(Unit, officer.unit_id)
        s.expunge_all()
        return officer, unit


def end_session(token: str) -> int | None:
    """Delete this session; the officer it belonged to, if it was one."""
    with _session() as s:
        row = s.scalar(select(OfficerSession).where(OfficerSession.token_sha256 == _digest(token)))
        if row is None:
            return None
        s.delete(row)
        s.commit()
        return row.officer_id
