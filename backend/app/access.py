"""The demo code: on a public deployment, starting work needs it.

Anyone can open the public site. Reading costs nothing -- the recorded demos,
a stored case by its link, the label coverage -- but some requests spend the
deployment's free provider quota or leave work running after the visitor has
gone. With EXCHEQUER_DEMO_CODE set, those need the code, sent as the header
X-Exchequer-Demo-Code:

    POST /trace, /trace/jobs     a live trace
    POST /batches                up to 25 of them
    POST /watches, /watches/{id}/check    re-reading an address on a schedule
    POST /requests               logging a freeze request (a stored row)
    POST /access/check           whether a code is right, for the console's code box

Unset (a laptop, the test suite), nothing is guarded. The code is a shared
secret for a demo, not an account: R23 brings accounts.

One table here rather than a check in each route: what the public may do is
a single decision, and it should be readable in one place. tests/test_access.py
checks every guarded route by path, so a route that moves cannot slip out.
"""
from __future__ import annotations

import hmac
import json
import re
from typing import Any, Awaitable, Callable

from fastapi import APIRouter

from . import config, rate_limit

CODE_HEADER = "x-exchequer-demo-code"

GUARDED: list[tuple[str, re.Pattern[str]]] = [
    ("POST", re.compile(r"^/trace/?$")),
    ("POST", re.compile(r"^/trace/jobs/?$")),
    # Stopping a trace is owner-checked in the route; guarded like starting one.
    ("DELETE", re.compile(r"^/trace/jobs/[^/]+/?$")),
    ("POST", re.compile(r"^/batches/?$")),
    ("POST", re.compile(r"^/watches/?$")),
    ("POST", re.compile(r"^/watches/[^/]+/check/?$")),
    # A stored row per call; owner keys cost nothing, so only the code stops a
    # script filling the store from the public site.
    ("POST", re.compile(r"^/requests/?$")),
    # Guarded like the rest, so checking a code in the console gets the same
    # constant-time comparison and the same limit on guesses.
    ("POST", re.compile(r"^/access/check/?$")),
]

# Wrong codes per client: enough for typos, too few to guess one.
wrong_codes = rate_limit.SlidingWindowLimiter(10, 3600)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def is_guarded(method: str, path: str) -> bool:
    return any(method == m and pattern.match(path) for m, pattern in GUARDED)


class DemoCodeMiddleware:
    """Refuses a guarded request without the right code, before any route runs."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not config.DEMO_CODE or not is_guarded(scope["method"], scope["path"]):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        peer = scope.get("client")
        client = rate_limit.client_ip(headers, peer[0] if peer else None)
        if wrong_codes.remaining(client) == 0:
            wait = wrong_codes.check(client) or 60.0
            await _refuse(send, 429, "Too many wrong access codes from this connection. Try again later.",
                          {"retry-after": str(int(wait))})
            return
        given = headers.get(CODE_HEADER, "")
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
def access() -> dict[str, bool]:
    """Whether this deployment asks for a demo code, so the console knows
    to show the recorded demos and a code box instead of the trace form."""
    return {"demo_code_required": bool(config.DEMO_CODE)}


@router.post("/access/check")
def check_code() -> dict[str, bool]:
    """Reached only with the right code (or none configured): the middleware
    above answers every other case."""
    return {"ok": True}
