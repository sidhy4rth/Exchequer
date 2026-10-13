"""Who can see which stored case, without accounts.

A case is a complaint: the reported address, the victim's funds and where
they went. Before this the history list and the correlation view showed every
stored case to anyone who asked. Now:

* Each browser makes a random owner key once and sends it with every request
  (header `X-Exchequer-Owner`). A case stores the SHA-256 of the key that
  traced it, never the key.
* The history list shows the caller's own cases plus the demo cases.
* A case id is a random UUID, so a link to a case works as the permission to
  read it: /trace/{id}, the report and the letters open for whoever holds
  the link, as they always have. Nothing lists ids that are not yours.
* Correlation still runs over every stored case -- that is the point of it --
  but another person's case appears as "another complaint", without its id,
  reported address or amounts.

Demo cases are the ones stored before ownership existed whose address is one
of the demo traces (data/demo_traces.json). They stay public so the console
has something to show on a fresh browser. A new trace of a demo address is
owned like any other.

This is privacy between users of one deployment, not access control: anyone
can still run a trace. The README says so.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from functools import lru_cache
from typing import Any, Mapping

from . import config

OWNER_HEADER = "x-exchequer-owner"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{22,128}$")


def owner_hash(token: str | None) -> str | None:
    """SHA-256 of a well-formed owner key, or None for a missing/odd one."""
    if not token or not _TOKEN_RE.match(token):
        return None
    return hashlib.sha256(token.encode()).hexdigest()


def owner_hash_from_headers(headers: Mapping[str, str]) -> str | None:
    return owner_hash(headers.get(OWNER_HEADER))


def orphan_hash() -> str:
    """Owner for a trace sent without a key (curl, a script): a hash of a key
    nobody holds, so the case is private to its link from the start."""
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


@lru_cache(maxsize=1)
def demo_addresses() -> frozenset[str]:
    path = config.BACKEND_DIR / "data" / "demo_traces.json"
    try:
        entries = json.loads(path.read_text())
    except (OSError, ValueError):
        return frozenset()
    return frozenset(e["address"].lower() for e in entries if e.get("address"))


def is_public(owner: str | None, address: str | None) -> bool:
    return owner is None and (address or "").lower() in demo_addresses()


def visible_to(owner: str | None, address: str | None, caller: str | None) -> bool:
    """Whether a case with this stored owner may be listed for `caller`."""
    return is_public(owner, address) or (caller is not None and owner == caller)


# ---------------------------------------------------------------------------
# Correlation output, with other people's cases redacted
# ---------------------------------------------------------------------------
def redact_clusters(clusters: list[dict[str, Any]], may_see: set[str]) -> list[dict[str, Any]]:
    """Clusters with members outside `may_see` (case ids) anonymised."""
    out = []
    for cluster in clusters:
        members = []
        visible_reported: set[str] = set()
        hidden_reported = 0
        seen_hidden: set[str] = set()
        for m in cluster["cases"]:
            if m["case_id"] in may_see:
                members.append(m)
                visible_reported.add(m["reported_address"])
                continue
            members.append(_hide_member(m))
            key = (m["reported_address"] or "").lower()
            if key not in seen_hidden:
                seen_hidden.add(key)
                hidden_reported += 1
        out.append({
            **cluster,
            "cases": members,
            "reported_addresses": sorted(visible_reported),
            "other_complaints": hidden_reported,
        })
    return out


def _hide_member(m: dict[str, Any]) -> dict[str, Any]:
    return {
        **m,
        "case_id": None,
        "reported_address": None,
        "traced_at": None,
        "value_in_native": None,
        "hidden": True,
    }


def redact_related(related: list[dict[str, Any]], may_see: set[str]) -> list[dict[str, Any]]:
    """The trace view's related-case list, other people's cases anonymised.

    Hidden entries keep what the reader's own trace already shows -- the
    shared wallet, whether it is a probable deposit address, the asset and
    the exchange the other trace reached -- and lose the rest."""
    out = []
    hidden_index = 0
    for entry in related:
        if entry["case_id"] in may_see:
            out.append({**entry, "hidden": False})
            continue
        hidden_index += 1
        out.append({
            **entry,
            "case_id": None,
            "reported_address": None,
            "traced_at": None,
            "hidden": True,
            "ref": f"Another complaint #{hidden_index}",
            "shared": [{**s, "value_in_native": None} for s in entry["shared"]],
        })
    return out
