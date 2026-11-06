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
