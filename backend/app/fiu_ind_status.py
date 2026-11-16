"""What FIU-IND has published about an exchange, read from data/fiu_ind_status.json.

Whether the exchange was on FIU-IND's list of registered VDA service providers
as of 9 Mar 2026 (Lok Sabha USQ 5805, Annexure-I, the only official list), and
the notices, takedown directions and penalties FIU-IND announced, each with its
date and source. It is a fact about the exchange, never about any customer, and
it changes nothing else: not the attribution, the labels, the addressee or what
a letter asks. The report's FINDING and the exchange letters print it as one
note, only with EXCHEQUER_FIU_IND_NOTE on. It states the sources' facts and
their dates, in date order, each with its source, and the day Exchequer last
checked those sources (`_meta.checked_on`); it draws no conclusion from them.
The sources are re-checked at least every STALE_AFTER_DAYS days
(docs/flag-rollout.md, tests/test_fiu_ind_status.py); scripts/check_fiu_staleness.py
warns in CI, by the real date, once they are due.

Looked up by the exchange's name, like exchange_status.py, so a case stored
earlier is covered too. An exchange with no entry gets no note: nothing is
inferred about it.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from . import config, exchange_status

logger = logging.getLogger(__name__)

STATUS_FILE = "fiu_ind_status.json"  # in config.DATA_DIR
ABOUT = "about the exchange, not any customer"
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
STALE_AFTER_DAYS = 180  # re-check the sources at least this often


def _key(name: Any) -> str:
    return exchange_status.marked(name.strip(), None).casefold() if isinstance(name, str) else ""


def _is_day(value: Any) -> bool:
    """A real calendar day written YYYY-MM-DD: "2026-02-30" matches the pattern but is no day, and
    would make note() raise while a letter is drafted, so it is caught here, when the file is read."""
    if not (isinstance(value, str) and _ISO.fullmatch(value)):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _dated(fact: Any) -> bool:
    return (isinstance(fact, dict) and _is_day(fact.get("date"))
            and str(fact.get("url", "")).startswith("https://") and bool(fact.get("text"))
            and bool(fact.get("source")))


@lru_cache(maxsize=1)
def _document() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """(the register snapshot and checked_on, {casefolded name: entry with its name}); empty, logged, if unusable."""
    try:
        document = json.loads((config.DATA_DIR / STATUS_FILE).read_text(encoding="utf-8"))
        register = {**document["_meta"]["register"], "checked_on": document["_meta"]["checked_on"]}
        rows = document["exchanges"]
        if not (isinstance(rows, dict) and _is_day(register["as_of"])
                and register["url"].startswith("https://") and register["source"]
                and _is_day(register["checked_on"])):
            raise ValueError("no register snapshot, no real 'checked_on' day or no 'exchanges' object")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.error("%s unusable; no FIU-IND note is shown: %s", STATUS_FILE, exc)
        return {}, {}
    out = {}
    for name, entry in rows.items():
        # Each entry's shape is checked here, so one bad entry ("actions": null, a
        # string, a number) is skipped and never makes note() raise while a letter is drafted.
        lists = ([entry.get("actions", []), entry.get("penalties", [])]
                 if isinstance(entry, dict) and isinstance(entry.get("registered"), bool) else [None])
        facts = [*lists[0], *lists[1]] if all(isinstance(each, list) for each in lists) else [None]
        # A listed exchange is named as Annexure-I lists it; without that name
        # the note would read "listed as None", so the entry is skipped.
        named = facts == [None] or not entry["registered"] or (
            isinstance(entry.get("listed_as"), str) and bool(entry["listed_as"].strip()))
        if isinstance(name, str) and name.strip() and named and all(_dated(f) for f in facts):
            out[_key(name)] = {"name": name.strip(), **entry}
        else:
            logger.error("%s: entry %r is not dated and sourced; skipped, so it gets no note", STATUS_FILE, name)
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
    name, as_of = found["name"], _day(register["as_of"])
    facts = sorted([*found.get("actions", []), *found.get("penalties", [])], key=lambda f: f["date"])
    said = [f"on {_day(f['date'])} {f['text']} ({f['source']})" for f in facts]
    # Every clause in date order. The register snapshot leads when nothing is older than it.
    before = sum(f["date"] < register["as_of"] for f in facts)
    if before:
        listed = (f"as of {as_of} {name}, listed as {found.get('listed_as')}, was on FIU-IND's list of registered "
                  f"VDA service providers ({register['source']})" if found["registered"] else
                  f"as of {as_of} {name} was not on FIU-IND's list of registered VDA service providers "
                  f"({register['source']})")
        said[0] = f"{name}, in date order: {said[0]}"
    else:
        listed = (f"{name}, listed as {found.get('listed_as')}, was on FIU-IND's list of registered VDA "
                  f"service providers as of {as_of} ({register['source']})" if found["registered"] else
                  f"{name} was not on FIU-IND's list of registered VDA service providers as of "
                  f"{as_of} ({register['source']})")
    said.insert(before, listed)
    sources = list(dict.fromkeys([register["url"], *(f["url"] for f in facts)]))
    checked = f"Exchequer last checked the sources on {_day(register['checked_on'])}."
    return {"text": "; ".join(said) + ". " + checked, "sources": sources}


def staleness(today: date) -> str | None:
    """Why the file needs re-checking on `today`, or None while checked_on is within STALE_AFTER_DAYS.

    Takes the day from the caller, so a test's clock never moves by itself."""
    register = _document()[0]
    if not register:
        return f"{STATUS_FILE} is unusable, so no FIU-IND note is shown"
    checked = date.fromisoformat(register["checked_on"])
    if today - checked <= timedelta(days=STALE_AFTER_DAYS):
        return None
    return (f"{STATUS_FILE} was last checked on {checked.isoformat()}, more than {STALE_AFTER_DAYS} days before "
            f"{today.isoformat()}: re-check every entry against its source and the newest Parliament answer "
            f"and PIB releases (docs/flag-rollout.md, EXCHEQUER_FIU_IND_NOTE), then update _meta.checked_on")


def clear_cache() -> None:
    _document.cache_clear()
