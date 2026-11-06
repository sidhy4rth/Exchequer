"""Security headers on every response.

The app serves its own frontend (see main.py), so one policy covers both the
page and the API. The page loads nothing from other origins, its fonts
included (they are bundled: frontend/src/main.jsx); React's style={}
attributes need inline styles; the sign-in globe draws
to a canvas and the exports are made from blob: URLs. Nothing else is allowed,
and the page may not be framed by another site.

A plain ASGI middleware rather than @app.middleware("http"): the HTTP
decorator wraps the response body, which would buffer a streamed response.

Nothing outside the hashed /assets/ bundle may be cached unless the response
says so itself: case, request, alert and batch JSON hold a complaint's
particulars, and a shared cyber-cell PC's disk cache (or a proxy) would keep
them after the officer has gone. Some URLs answer the app's HTML to a
browser opening them and JSON to fetch() (main.spa, cases.get_trace), so
every answer varies on the headers that choose between them.

The app has no WebSocket routes and the server runs none (--ws none in
docker-entrypoint.sh). Should one ever arrive, it is refused here, before the
demo-code gate and the body limit it would otherwise pass untouched.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from . import config

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self'",
    "img-src 'self' data: blob:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

HEADERS: list[tuple[bytes, bytes]] = [
    (b"content-security-policy", CONTENT_SECURITY_POLICY.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    # Browsers ignore this over plain http, so it is harmless in development.
    (b"strict-transport-security", b"max-age=15552000; includeSubDomains"),
    (b"cross-origin-opener-policy", b"same-origin"),
]

NO_STORE = (b"cache-control", b"no-store")
# The request headers main._is_page_load and cases._is_page_load read.
VARY_ON = ("Sec-Fetch-Mode", "Accept")


def _with_vary(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """One Vary header, holding what was there plus VARY_ON."""
    names: list[str] = []
    rest = []
    for name, value in headers:
        if name.lower() == b"vary":
            names += [v.strip() for v in value.decode("latin-1").split(",") if v.strip()]
        else:
            rest.append((name, value))
    seen = {n.lower() for n in names}
    names += [n for n in VARY_ON if n.lower() not in seen]
    return rest + [(b"vary", ", ".join(names).encode("latin-1"))]


# Swagger UI loads its script and stylesheet from a CDN and runs an inline
# bootstrap script, so the API docs (local development only, see config)
# get the other headers but not the page policy.
_DOCS_PATHS = ("/docs", "/redoc")

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class SecurityHeadersMiddleware:
    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})  # policy violation
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Only the docs pages themselves, and only when they exist: with docs
        # off, /docs is the app like any other path and keeps the page policy.
        path = scope.get("path", "")
        is_docs = config.API_DOCS_ENABLED and (path in _DOCS_PATHS or path.startswith("/docs/"))
        is_asset = path.startswith("/assets/")

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                extra = [
                    (name, value) for name, value in HEADERS
                    if name not in present
                    and not (is_docs and name == b"content-security-policy")
                ]
                if not is_asset:
                    if b"cache-control" not in present:
                        extra.append(NO_STORE)
                    headers = _with_vary(headers)
                message["headers"] = headers + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)


# The most any request body may hold. Only /verify takes a whole text report;
# every other route takes a small JSON body (the largest real one, a 25-row
# batch, is a few kilobytes), and FastAPI parses and validates JSON on the
# event loop, so a 2 MB body on any route stalled every visitor.
DEFAULT_MAX_BODY = 256_000
LARGE_BODY_ROUTES = {"/verify": 2_100_000}


class BodySizeLimitMiddleware:
    """Refuse request bodies over the route's limit with 413, before they fill memory.

    Refused up front when Content-Length says so, or as soon as a streamed
    body crosses the limit.
    """

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]],
                 max_bytes: int = DEFAULT_MAX_BODY, large: dict[str, int] | None = None) -> None:
        self.app = app
        self.default_max = max_bytes
        self.large = LARGE_BODY_ROUTES if large is None else large

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.large.get(scope.get("path", "").rstrip("/") or "/", self.default_max)
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    too_big = int(value) > limit
                except ValueError:
                    too_big = True
                if too_big:
                    await _send_413(send)
                    return
        received = 0
        started = False
        over = False

        async def counting_receive() -> dict[str, Any]:
            nonlocal received, over
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    over = True
                    raise _TooLarge()
            return message

        async def tracking_send(message: dict[str, Any]) -> None:
            nonlocal started
            if over:
                # FastAPI catches the error raised mid-read and answers 400
                # ("error parsing the body"); say what happened instead.
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await _send_413(send)
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started:
                await _send_413(send)


class _TooLarge(Exception):
    pass


async def _send_413(send: Send) -> None:
    body = b'{"detail":"Request body too large."}'
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
