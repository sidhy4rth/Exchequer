"""Text that reaches the store, cleaned to what the store can hold.

Postgres refuses a NUL anywhere in a text value, written or only compared,
and enforces every VARCHAR length; SQLite does neither, so the test suite
never sees either failure. Label text from third-party lists, provider
fields and what a browser sends all reach the store, and a NUL or an
over-long value there is a 500 in production -- or, in the watcher, a watch
that fails every round.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Annotated
from urllib.parse import unquote_plus

from pydantic import AfterValidator
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Control, format (zero-width, bidi overrides), line and paragraph separators.
_HIDDEN = {"Cc", "Cf", "Zl", "Zp"}
_SPACES = re.compile(r"\s+")


def plain_text(value: object, max_len: int) -> str:
    """`value` as one line of visible text, at most `max_len` characters.

    NFKC-normalised; control and invisible formatting characters become
    spaces; runs of whitespace collapse to one; cut with an ellipsis."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join(" " if unicodedata.category(ch) in _HIDDEN else ch for ch in text)
    text = _SPACES.sub(" ", text).strip()
    if len(text) > max_len:
        text = text[: max(0, max_len - 1)].rstrip() + "…"
    return text


# ---------------------------------------------------------------------------
# At the edge: refused before any route runs or any allowance is charged
# ---------------------------------------------------------------------------
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _no_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("text with a NUL character is not accepted")
    return value


def _one_line(value: str) -> str:
    if _CONTROL.search(value):
        raise ValueError("text with control characters is not accepted")
    return value


# Free text (notes): tabs and line breaks allowed, NUL never.
NoNul = Annotated[str, AfterValidator(_no_nul)]
# Names, references, ids, addresses: no control characters at all.
OneLine = Annotated[str, AfterValidator(_one_line)]

CONTROL_DETAIL = "Text with control characters is not accepted."


class ControlCharMiddleware:
    """400 for a request whose decoded path or query holds a control character.

    A path or query value reaches the store as a lookup key (/trace/{id},
    ?case_id=), and a NUL there is a psycopg error on Postgres: a 500 for
    anyone who asks, as often as they like."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            query = unquote_plus(scope.get("query_string", b"").decode("latin-1"))
            if _CONTROL.search(scope.get("path", "")) or _CONTROL.search(query):
                response = JSONResponse({"detail": CONTROL_DETAIL}, status_code=400)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
