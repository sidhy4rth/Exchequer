"""The demo code: on a public deployment, starting work needs it.

Anyone can open the public site. Reading costs nothing -- the recorded demos,
a stored case by its link, the label coverage -- but some requests spend the
deployment's free provider quota or leave work running after the visitor has
gone. With EXCHEQUER_DEMO_CODE set, those need the code, sent as the header
X-Exchequer-Demo-Code:

    POST /trace, /trace/jobs     a live trace
    POST /batches                up to 25 of them
    POST /payments/search        a search of a wallet for the victim's payment
    POST /watches, /watches/{id}/check    re-reading an address on a schedule
    POST /requests               logging a freeze request (a stored row)
    POST /trace/{id}/recheck     rereading a case's cited transfers from a second provider
    POST /access/check           whether a code is right, for the console's code box

Unset (a laptop, the test suite), nothing is guarded. The code is a shared
secret for a demo, not an account: R23 brings accounts. A public host
without it stays open -- the live site must keep working before the code is
set -- but says so: an error at every start, and "access": "open" in /health.
EXCHEQUER_REQUIRE_DEMO_CODE, once the code is in place, makes a deploy that
loses it refuse live tracing (503) instead.

The right code at /access/check also returns a pass, which the console sends
as X-Exchequer-Demo-Pass instead of the code. Ten wrong codes from one
connection lock that connection out for 15 minutes. A pass is signed with a
key made from the code, so it cannot be guessed and says nothing about the
code: a browser holding one is never locked out by someone else's guesses on
the same venue Wi-Fi. Passes expire (config.DEMO_PASS_SECONDS) and changing
the code revokes them all.

Whether the right code itself gets through a lockout depends on its length:

  - MIN_CODE_LENGTH (22) characters or more, the length of
    secrets.token_urlsafe(16), about 128 bits: yes. Telling a right guess from
    a wrong one helps nobody when there are 2^128 codes to try, so a judge's
    own laptop, a second presenter device or a script (check_demos.py) is not
    stopped by a prankster on the same Wi-Fi. Wrong codes are still refused
    with 429 during the lockout, and still counted before it.
  - Shorter: no. The lockout answers every request the same way, the right
    code included, or it would become an unlimited guessing oracle.

So make the code long and random (secrets.token_urlsafe(16)); the lockout is
a backstop, not what keeps it secret.

The owner's switch, EXCHEQUER_CONSOLE (config.CONSOLE), sits above all of
this. "open", the default, is everything above: the site stays open for the
judges. "officers" closes OFFICER_ONLY, every live or spending route, to a
signed-in officer session (accounts.py); a demo code or a pass no longer
opens them, and an officer needs neither. Reading, the recorded demos and
/verify stay open either way, and /health and /access say which mode is on.

One table here rather than a check in each route: what the public may do is
a single decision, and it should be readable in one place. tests/test_access.py
checks every guarded route by path, so a route that moves cannot slip out.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from . import accounts, config, rate_limit

logger = logging.getLogger(__name__)

CODE_HEADER = "x-exchequer-demo-code"
PASS_HEADER = "x-exchequer-demo-pass"
# The length of secrets.token_urlsafe(16): about 128 bits. Shorter, a code
# could be guessed despite the lockout, so the right code is locked out too
# (see the module docstring), and every start warns about it.
MIN_CODE_LENGTH = 22

GUARDED: list[tuple[str, re.Pattern[str]]] = [
    ("POST", re.compile(r"^/trace/?$")),
    ("POST", re.compile(r"^/trace/jobs/?$")),
    # Stopping a trace is owner-checked in the route; guarded like starting one.
    ("DELETE", re.compile(r"^/trace/jobs/[^/]+/?$")),
    ("POST", re.compile(r"^/batches/?$")),
    # A provider read, charged like a trace (routes/payments.py).
    ("POST", re.compile(r"^/payments/search/?$")),
    ("POST", re.compile(r"^/watches/?$")),
    ("POST", re.compile(r"^/watches/[^/]+/check/?$")),
    # A stored row per call; owner keys cost nothing, so only the code stops a
    # script filling the store from the public site.
    ("POST", re.compile(r"^/requests/?$")),
    # Rereads up to 40 transfers from a second provider (routes/recheck.py).
    ("POST", re.compile(r"^/trace/[^/]+/recheck/?$")),
    # Guarded like the rest, so checking a code in the console gets the same
    # constant-time comparison and the same limit on guesses.
    ("POST", re.compile(r"^/access/check/?$")),
]

# With EXCHEQUER_CONSOLE=officers, only a signed-in officer may call these:
# every guarded route but the code box (the payment search among them), the
# second officer's sign-off, and what an officer does with a citizen's
# complaint (routes/complaints.py): its status, a reply, a link to a case,
# claiming it for a unit.
OFFICER_ONLY: list[tuple[str, re.Pattern[str]]] = [
    *[(m, p) for m, p in GUARDED if not p.match("/access/check")],
    ("POST", re.compile(r"^/requests/[^/]+/signoff/?$")),
    ("POST", re.compile(r"^/complaints/[^/]+/(?:status|messages|link-case|claim)/?$")),
]
OFFICER_REFUSAL = "Sign in as an officer to trace live."

# Wrong codes per client: enough for typos, too few to guess one, and a
# prank on shared Wi-Fi lasts minutes rather than the afternoon.
wrong_codes = rate_limit.SlidingWindowLimiter(10, 900)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def is_guarded(method: str, path: str) -> bool:
    return any(method == m and pattern.match(path) for m, pattern in GUARDED)


def officer_only(method: str, path: str) -> bool:
    return config.CONSOLE == "officers" and any(method == m and p.match(path) for m, p in OFFICER_ONLY)


def is_officer(token: str | None) -> bool:
    """Whether this session cookie is a live officer session that may act
    (a temporary password must be changed first)."""
    found = accounts.signed_in(token) if token else None
    return found is not None and not found[0].must_change_password


def state() -> str:
    """"code" (guarded), "open" (no code: anyone may trace) or "closed" (a
    code is required but missing: nobody may)."""
    if config.DEMO_CODE:
        return "code"
    return "closed" if config.REQUIRE_DEMO_CODE else "open"


def report_at_startup() -> None:
    """Say loudly, at every start, when a public site is open to anyone."""
    raw = os.environ.get("EXCHEQUER_CONSOLE", "").strip().lower()
    if raw and raw not in config.CONSOLE_MODES:
        logger.error("EXCHEQUER_CONSOLE=%r is not one of %s: the console stays open",
                     raw[:20], ", ".join(config.CONSOLE_MODES))
    if config.CONSOLE == "officers":
        logger.warning("EXCHEQUER_CONSOLE=officers: live tracing needs a signed-in officer")
    current = state()
    if current == "closed":
        logger.error("EXCHEQUER_REQUIRE_DEMO_CODE is on but EXCHEQUER_DEMO_CODE is not set: "
                     "live traces, batches and watches are refused (503) until it is")
    elif current == "open" and config.PUBLIC_HOST and config.CONSOLE != "officers":
        logger.error("THIS PUBLIC SITE IS OPEN: EXCHEQUER_DEMO_CODE is not set, so anyone can start "
                     "live traces, batches and watches that spend the provider quota. Set it in the "
                     "host's environment, and the secret DEMO_CODE of the GitHub environment live-checks to the same value")
    elif current == "code" and not code_is_long_enough():
        logger.warning("EXCHEQUER_DEMO_CODE is %d characters, short enough to guess, so ten wrong "
                       "codes lock out the right one too; use %d or more: "
                       "python -c 'import secrets;print(secrets.token_urlsafe(16))'",
                       len(config.DEMO_CODE), MIN_CODE_LENGTH)


def code_is_long_enough() -> bool:
    """Whether the configured code is too long to guess, so the right code may
    pass a lockout without the lockout answering guesses. /health/detail
    reports this as demo_code_long_enough."""
    return len(config.DEMO_CODE) >= MIN_CODE_LENGTH


def _pass_mac(body: str) -> str:
    key = hmac.new(config.DEMO_CODE.encode(), b"exchequer demo pass v1", hashlib.sha256).digest()
    digest = hmac.new(key, body.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def mint_pass(now: float | None = None) -> str:
    """v1.<expiry>.<nonce>.<mac>: stateless, so it survives a restart."""
    exp = int((time.time() if now is None else now) + config.DEMO_PASS_SECONDS)
    body = f"v1.{exp}.{secrets.token_urlsafe(9)}"
    return f"{body}.{_pass_mac(body)}"


def pass_is_valid(token: str, now: float | None = None) -> bool:
    if not config.DEMO_CODE or len(token) > 200:
        return False
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != "v1" or not parts[1].isdigit():
        return False
    body = ".".join(parts[:3])
    if not hmac.compare_digest(parts[3].encode(), _pass_mac(body).encode()):
        return False
    return int(parts[1]) > (time.time() if now is None else now)


class DemoCodeMiddleware:
    """Refuses a guarded request without the right code, before any route runs."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and officer_only(scope["method"], scope["path"]):
            # Checked off the event loop: it reads the session store.
            if await run_in_threadpool(is_officer, Request(scope).cookies.get(accounts.COOKIE)):
                await self.app(scope, receive, send)
            else:
                await _refuse(send, 403, OFFICER_REFUSAL)
            return
        if scope["type"] != "http" or not is_guarded(scope["method"], scope["path"]):
            await self.app(scope, receive, send)
            return
        if not config.DEMO_CODE:
            if config.REQUIRE_DEMO_CODE:
                await _refuse(send, 503, "This site requires an access code but none is configured: "
                                         "live tracing is off until the operator sets EXCHEQUER_DEMO_CODE.")
                return
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        token = headers.get(PASS_HEADER, "")
        if token and pass_is_valid(token):
            # Before the lockout: a pass cannot be guessed, so letting it
            # through while the connection is locked out answers nothing.
            await self.app(scope, receive, send)
            return
        peer = scope.get("client")
        client = rate_limit.client_ip(headers, peer[0] if peer else None)
        given = headers.get(CODE_HEADER, "")
        if wrong_codes.remaining(client) == 0:
            # Locked out. A long code is too long to guess, so the right one
            # may pass without the lockout answering guesses; a short code is
            # refused like everything else. Constant time either way.
            if given and code_is_long_enough() and hmac.compare_digest(given.encode(), config.DEMO_CODE.encode()):
                await self.app(scope, receive, send)
                return
            wait = wrong_codes.check(client) or 60.0
            await _refuse(send, 429, "Too many wrong access codes from this connection. Try again later.",
                          {"retry-after": str(int(wait))})
            return
        if not given and token:
            # Expired, or made with a code since changed: not a guess.
            await _refuse(send, 403, "This browser's access pass has expired. Enter the access code again.",
                          {"x-exchequer-demo-pass-invalid": "1"})
            return
        if not given:
            await _refuse(send, 403, "Live tracing on this site needs an access code. "
                                     "The verified examples and stored cases open without one.")
            return
        # Constant time: how long a comparison takes must not say how much of a guess was right.
        if not hmac.compare_digest(given.encode(), config.DEMO_CODE.encode()):
            wrong_codes.check(client)
            await _refuse(send, 403, "That access code is not right.")
            return
        await self.app(scope, receive, send)


async def _refuse(send: Send, status: int, detail: str, extra: dict[str, str] | None = None) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    headers += [(k.encode(), v.encode()) for k, v in (extra or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


router = APIRouter()


@router.get("/access")
def access(request: Request) -> dict[str, Any]:
    """Whether this deployment asks for a demo code, so the console knows
    to show the recorded demos and a code box instead of the trace form;
    which console mode is on; and whether the caller is a signed-in officer,
    who in "officers" mode gets the trace form."""
    return {"demo_code_required": state() != "open", "console": config.CONSOLE,
            "officer": is_officer(request.cookies.get(accounts.COOKIE))}


@router.post("/access/check")
def check_code() -> dict[str, Any]:
    """Reached only with the right code or a valid pass (or none configured):
    the middleware above answers every other case. Hands back a fresh pass
    for the browser to send instead of the code."""
    if not config.DEMO_CODE:
        return {"ok": True}
    return {"ok": True, "pass": mint_pass(), "expires_in": config.DEMO_PASS_SECONDS}
