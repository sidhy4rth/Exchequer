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
