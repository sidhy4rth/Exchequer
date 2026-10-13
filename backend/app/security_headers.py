"""Security headers on every response.

The app serves its own frontend (see main.py), so one policy covers both the
page and the API. The page loads nothing from other origins except Google
Fonts; React's style={} attributes need inline styles; the sign-in globe draws
to a canvas and the exports are made from blob: URLs. Nothing else is allowed,
and the page may not be framed by another site.

A plain ASGI middleware rather than @app.middleware("http"): the HTTP
decorator wraps the response body, which would buffer a streamed response.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
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
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_docs = scope.get("path", "").startswith(_DOCS_PATHS)

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                extra = [
                    (name, value) for name, value in HEADERS
                    if name not in present
                    and not (is_docs and name == b"content-security-policy")
                ]
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Refuse request bodies over `max_bytes` with 413, before they fill memory.

    FastAPI reads a JSON body whole. Nothing this API accepts comes near the
    limit -- the largest is a text report sent to /verify -- so anything over
    it is refused: up front when Content-Length says so, or as soon as a
    streamed body crosses it.
    """

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]], max_bytes: int = 2_100_000) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    too_big = int(value) > self.max_bytes
                except ValueError:
                    too_big = True
                if too_big:
                    await _send_413(send)
                    return
        received = 0
        started = False

        async def counting_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge()
            return message

        async def tracking_send(message: dict[str, Any]) -> None:
            nonlocal started
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
