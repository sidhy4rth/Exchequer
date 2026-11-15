"""What FIU-IND has published about an exchange, read from data/fiu_ind_status.json.

Whether the exchange was on FIU-IND's list of registered VDA service providers
as of 9 Mar 2026 (Lok Sabha USQ 5805, Annexure-I, the only official list), and
the notices, takedown directions and penalties FIU-IND announced, each with its
date and source. It is a fact about the exchange, never about any customer, and
it changes nothing else: not the attribution, the labels, the addressee or what
a letter asks. The report's FINDING and the exchange letters print it as one
note, only with EXCHEQUER_FIU_IND_NOTE on. It states the sources' facts and
their dates, and draws no conclusion from them.

Looked up by the exchange's name, like exchange_status.py, so a case stored
earlier is covered too. An exchange with no entry gets no note: nothing is
inferred about it.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from functools import lru_cache
from typing import Any

from . import config, exchange_status

logger = logging.getLogger(__name__)

STATUS_FILE = "fiu_ind_status.json"  # in config.DATA_DIR
ABOUT = "about the exchange, not any customer"
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def _key(name: Any) -> str:
    return exchange_status.marked(name.strip(), None).casefold() if isinstance(name, str) else ""


def _dated(fact: Any) -> bool:
    return (isinstance(fact, dict) and isinstance(fact.get("date"), str) and bool(_ISO.fullmatch(fact["date"]))
            and str(fact.get("url", "")).startswith("https://") and bool(fact.get("text"))
            and bool(fact.get("source")))


@lru_cache(maxsize=1)
def _document() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """(the register snapshot, {casefolded name: entry with its name}); empty, logged, if unusable."""
    try:
        document = json.loads((config.DATA_DIR / STATUS_FILE).read_text(encoding="utf-8"))
        register = document["_meta"]["register"]
        rows = document["exchanges"]
        if not (isinstance(rows, dict) and _ISO.fullmatch(register["as_of"])
                and register["url"].startswith("https://") and register["source"]):
            raise ValueError("no register snapshot or no 'exchanges' object")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.error("%s unusable; no FIU-IND note is shown: %s", STATUS_FILE, exc)
        return {}, {}
    out = {}
    for name, entry in rows.items():
        facts = ([*entry.get("actions", []), *entry.get("penalties", [])]
                 if isinstance(entry, dict) and isinstance(entry.get("registered"), bool) else [None])
        if isinstance(name, str) and name.strip() and all(_dated(f) for f in facts):
            out[_key(name)] = {"name": name.strip(), **entry}
        else:
            logger.warning("%s: entry %r is not dated and sourced; skipped", STATUS_FILE, name)
    return register, out


def entry(exchange: Any) -> dict[str, Any] | None:
    """The entry for `exchange`, or None if the file does not name it."""
    return _document()[1].get(_key(exchange)) if _key(exchange) else None


def _day(iso: str) -> str:
    when = date.fromisoformat(iso)
    return f"{when.day} {when:%b %Y}"


def note(exchange: Any) -> dict[str, Any] | None:
    """{"text", "sources"} for `exchange`; None with the flag off or for an exchange not listed."""
    if not config.FIU_IND_NOTE:
        return None
    found = entry(exchange)
    if not found:
        return None
    register = _document()[0]
    listed = (f"{found['name']}, listed as {found.get('listed_as')}, was on FIU-IND's list of registered VDA "
              f"service providers as of {_day(register['as_of'])} ({register['source']})"
              if found["registered"] else
              f"{found['name']} was not on FIU-IND's list of registered VDA service providers as of "
              f"{_day(register['as_of'])} ({register['source']})")
    facts = sorted([*found.get("actions", []), *found.get("penalties", [])], key=lambda f: f["date"])
    said = [listed] + [f"on {_day(f['date'])} {f['text']} ({f['source']})" for f in facts]
    sources = list(dict.fromkeys([register["url"], *(f["url"] for f in facts)]))
    return {"text": "; ".join(said) + ".", "sources": sources}


def clear_cache() -> None:
    _document.cache_clear()
