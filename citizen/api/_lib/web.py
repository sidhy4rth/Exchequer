"""Requests and answers for the citizen functions, and the Vercel handler.

Every answer is JSON, never cached, and never carries a stack trace. A
request must come from this site: the custom X-Citizen header (a page on
another site cannot send it without a preflight, which is never allowed)
plus SameSite=Strict cookies; an Origin, when sent, must be this host.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable
from urllib.parse import parse_qsl, urlsplit

from . import db

logger = logging.getLogger("citizen")
SORRY = "Something went wrong. Please try again later."
NOT_READY = "This site cannot take requests right now. Please try again later."


def now() -> int:
    return int(time.time())


@dataclass
class Request:
    method: str
    path: str
    query: str
    headers: dict[str, str]  # lower-case names
    body: bytes
    client: str  # the socket's peer

    def args(self) -> dict[str, str]:
        return dict(parse_qsl(self.query, keep_blank_values=True))

    def cookie(self, name: str) -> str | None:
        for part in self.headers.get("cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return None


@dataclass
class Response:
    status: int
    body: Any
    cookies: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)


class Refused(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after


@dataclass
class Endpoint:
    route: Callable[[Request], Response]
    methods: tuple[str, ...]
    cap: int = 4_096  # the largest body read, in bytes


def secret() -> bytes:
    value = os.environ.get("CITIZEN_SECRET", "")
    if len(value) < 32:
        raise db.Unavailable("CITIZEN_SECRET is not set")
    return value.encode()


def keyed(kind: str, value: str) -> str:
    """A keyed hash: an NCRP number or a connection's address is never stored as itself."""
    return hmac.new(secret(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def client_ip(req: Request) -> str:
    # Vercel sets both headers itself and drops any the client sent.
    # An IPv6 client holds a whole /64 and can take a new address in it for
    # each request, so it is counted by the /64; IPv4 by the address.
    real = req.headers.get("x-real-ip", "").strip()
    forwarded = req.headers.get("x-forwarded-for", "").split(",")[0].strip()
    seen = real or forwarded or req.client
    try:
        ip = ipaddress.ip_address(seen)
    except ValueError:
        return seen
    if ip.version == 6 and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)


def json_body(req: Request, fields: set[str]) -> dict:
    """The body as an object with no field outside `fields`."""
    try:
        body = json.loads(req.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Refused(400, "The request could not be read.") from None
    if not isinstance(body, dict):
        raise Refused(400, "The request could not be read.")
    extra = sorted(set(body) - fields)
    if extra:
        raise Refused(400, f"Unexpected field: {', '.join(extra)[:80]}. Only text details are sent.")
    return body


def _check(endpoint: Endpoint, req: Request) -> None:
    if req.method not in endpoint.methods:
        raise Refused(405, "This address does not take that kind of request.")
    if req.headers.get("x-citizen") != "1":
        raise Refused(403, "This request must come from the citizen site.")
    origin = req.headers.get("origin")
    if origin and urlsplit(origin).netloc != req.headers.get("host", ""):
        raise Refused(403, "This request must come from the citizen site.")
    if len(req.body) > endpoint.cap:
        raise Refused(413, "That is too long to send.")
    if req.method == "POST" and req.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise Refused(415, "Send the details as JSON.")


def dispatch(endpoint: Endpoint, req: Request) -> Response:
    try:
        _check(endpoint, req)
        res = endpoint.route(req)
    except Refused as no:
        res = Response(no.status, {"error": no.message})
        if no.retry_after is not None:
            res.headers["Retry-After"] = str(max(1, no.retry_after))
        if no.status == 405:
            res.headers["Allow"] = ", ".join(endpoint.methods)
    except db.Unavailable as exc:
        logger.warning("citizen %s: not ready (%s)", req.path, exc)
        res = Response(503, {"error": NOT_READY})
    except Exception as exc:  # never a stack trace to the client; the log gets the kind only
        logger.error("citizen %s failed: %s", req.path, type(exc).__name__)
        res = Response(500, {"error": SORRY})
    res.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                        "Content-Type": "application/json; charset=utf-8"})
    return res


def handler_for(endpoint: Endpoint) -> type[BaseHTTPRequestHandler]:
    """The class Vercel's Python runtime calls for each request."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _serve(self) -> None:
            headers = {k.lower(): v for k, v in self.headers.items()}
            body, refused = b"", None
            if self.command == "POST":
                length = headers.get("content-length", "")
                if not length.isdigit():
                    refused = Response(411, {"error": "The request has no length."})
                elif int(length) > endpoint.cap:
                    refused = Response(413, {"error": "That is too long to send."})
                else:
                    body = self.rfile.read(int(length))
            parts = urlsplit(self.path)
            req = Request(self.command, parts.path, parts.query, headers, body, self.client_address[0])
            res = refused or dispatch(endpoint, req)
            data = json.dumps(res.body).encode()
            self.send_response(res.status)
            for name, value in {**res.headers, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                "Content-Type": "application/json; charset=utf-8"}.items():
                self.send_header(name, value)
            for cookie in res.cookies:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _serve

        def log_message(self, *_args) -> None:  # addresses and paths stay out of the logs
            pass

    return Handler
