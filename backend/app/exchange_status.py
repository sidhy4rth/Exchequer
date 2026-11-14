"""Exchanges that have closed, or are closing, read from data/exchange_status.json.

An exchange's wallet stays its wallet after the exchange closes, so the label
files keep those labels: a trace that ends at an FTX address did end at FTX.
What changes is the next step. A request letter addressed to FTX as if FTX
could answer sends the officer's first, most urgent letter nowhere. So:

  * every label of a listed exchange reads "(defunct)" or "(winding down)"
    (scripts/mark_exchange_status.py writes that into the label files), and
  * request_letters.py addresses a defunct exchange's letters to whoever now
    holds its records -- an administrator, liquidator or successor, which the
    officer must identify -- and says why, with the source; a winding-down
    exchange's letters go to it as usual, with a note to send them before it
    closes.

The status is looked up by the exchange's name, not read from a case's label,
so a case stored before the label said "(defunct)", or an exchange named by a
live TronScan tag, is caught as well.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from . import config

logger = logging.getLogger(__name__)

STATUS_FILE = "exchange_status.json"  # in config.DATA_DIR
DEFUNCT = "defunct"
WINDING_DOWN = "winding_down"
SUFFIX = {DEFUNCT: " (defunct)", WINDING_DOWN: " (winding down)"}


def _key(name: Any) -> str:
    text = name.strip() if isinstance(name, str) else ""
    for suffix in SUFFIX.values():
        text = text.removesuffix(suffix)
    return text.casefold()


@lru_cache(maxsize=1)
def _entries() -> dict[str, dict[str, str]]:
    """{casefolded name: entry with its name}; empty, logged, if the file is missing or malformed."""
    try:
        document = json.loads((config.DATA_DIR / STATUS_FILE).read_text(encoding="utf-8"))
        rows = document.get("exchanges") if isinstance(document, dict) else None
        if not isinstance(rows, dict):
            raise ValueError("'exchanges' is not an object")
    except (OSError, ValueError) as exc:
        logger.error("%s unusable; no exchange is treated as closed: %s", STATUS_FILE, exc)
        return {}
    out = {}
    for name, entry in rows.items():
        if isinstance(entry, dict) and entry.get("status") in SUFFIX and isinstance(name, str) and name.strip():
            out[_key(name)] = {"name": name.strip(), **{k: str(v) for k, v in entry.items()}}
        else:
            logger.warning("%s: entry %r has no known status; skipped", STATUS_FILE, name)
    return out


def status(exchange: Any) -> dict[str, str] | None:
    """The entry for `exchange` ({name, status, since, what, source, ...}), or None if it is not listed."""
    return _entries().get(_key(exchange)) if _key(exchange) else None


def is_defunct(exchange: Any) -> bool:
    found = status(exchange)
    return bool(found) and found["status"] == DEFUNCT


def marked(label: str, exchange: Any) -> str:
    """`label` with its exchange's status suffix, once; unchanged for an exchange not listed."""
    found = status(exchange)
    plain = label
    for suffix in SUFFIX.values():
        plain = plain.removesuffix(suffix)
    return plain + SUFFIX[found["status"]] if found else plain


def clear_cache() -> None:
    _entries.cache_clear()
