"""Officer sign-in: who ran a trace, recorded with the evidence.

A court asks not only what the evidence says but who produced it and when.
Every case therefore carries the officer who ran it -- name, service ID,
unit -- and the report prints it in the header beside the time and the
content hash. That is the reason this exists; access control is the side
effect.

The gate is deliberately small. One shared access code, set in the
environment as EXCHEQUER_ACCESS_CODE, admits an officer who also states who
they are; there is no user database and nothing to breach. With the variable
unset the gate is off and traces record no officer, which keeps a machine
without a .env working and makes the requirement visible: a report with no
"Traced by" line was produced on an ungated instance.

The session is a signed, expiring token in an HttpOnly cookie. It carries
only what the officer typed; the signature is HMAC-SHA256 under a secret
derived from the access code (or EXCHEQUER_SESSION_SECRET when set), so a
token cannot be forged or edited without the code.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import HTTPException, Request, Response

COOKIE = "exchequer_session"
SESSION_HOURS = 12


def access_code() -> str:
    return os.getenv("EXCHEQUER_ACCESS_CODE", "").strip()


def gate_enabled() -> bool:
    return bool(access_code())


def code_matches(given: str) -> bool:
    return hmac.compare_digest(given.strip().encode("utf-8"), access_code().encode("utf-8"))


def _secret() -> bytes:
    explicit = os.getenv("EXCHEQUER_SESSION_SECRET", "").strip()
    seed = explicit or f"exchequer-session:{access_code()}"
    return hashlib.sha256(seed.encode("utf-8")).digest()


@dataclass(frozen=True)
class Officer:
    name: str
    officer_id: str
    unit: str
    signed_in_at: str  # UTC ISO

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def line(self) -> str:
        """One line for a report header: 'Inspector R. Sharma (ID 4471) · Cyber Cell, Bengaluru'."""
        who = f"{self.name} (ID {self.officer_id})" if self.officer_id else self.name
        return f"{who} · {self.unit}" if self.unit else who


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(officer: Officer, now: float | None = None) -> str:
    body = {**officer.to_dict(), "exp": int((now or time.time()) + SESSION_HOURS * 3600)}
    payload = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64(hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str | None, now: float | None = None) -> Officer | None:
    """The officer a token names, or None if it is missing, forged or expired."""
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        body = json.loads(_unb64(payload))
    except (ValueError, UnicodeDecodeError):
        return None
    if body.get("exp", 0) < (now or time.time()):
        return None
    try:
        return Officer(name=body["name"], officer_id=body["officer_id"],
                       unit=body["unit"], signed_in_at=body["signed_in_at"])
    except KeyError:
        return None


def current_officer(request: Request) -> Officer | None:
    return read_token(request.cookies.get(COOKIE))


def require_officer(request: Request) -> Officer | None:
    """FastAPI dependency. With the gate on, a valid session is required;
    with it off, everyone is admitted and no officer is recorded."""
    if not gate_enabled():
        return None
    officer = current_officer(request)
    if officer is None:
        raise HTTPException(status_code=401, detail="Sign in to use Exchequer.")
    return officer


def set_session(response: Response, officer: Officer) -> None:
    response.set_cookie(
        COOKIE, issue_token(officer), max_age=SESSION_HOURS * 3600,
        httponly=True, samesite="lax", path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")
