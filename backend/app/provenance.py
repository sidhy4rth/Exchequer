"""What a trace ran with, stored with its case.

A stored case never changes (ADR-0002), but its report and letters are
rendered on request, by whatever code is deployed then and against the label
lists on disk then. Without a record of the trace's own, a report rendered
after a deploy named the new commit as its version and today's list dates as
the screening's, and two downloads of one case either side of a deploy were two
different signed documents. So a trace stores:

* `tool_version`: the code that ran it;
* `lists`: each screening and label list's file, `_meta` dates and SHA-256;
* `label_store`: the label store it screened against, if any;
* `settings`: the switches that change what a trace does.

Reports and letters read these; a case stored before they existed says so.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import config
from .evidence import utc_now_iso

# The fields of a list's _meta a report reads (risk_matcher.list_freshness).
_META_KEYS = ("last_reviewed", "ofac_publish_date", "counts")


@lru_cache(maxsize=64)
def _file_sha256(path: str, mtime_ns: int, size: int) -> str:
    """Of the list file as it is; once per version of the file, since some are megabytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _list_entry(path: Path | None) -> dict[str, Any] | None:
    from .risk_matcher import _list_meta

    if not path:
        return None
    meta = _list_meta(path)
    if meta is None:
        return None
    try:
        stat = path.stat()
        sha = _file_sha256(str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        sha = None
    counts = meta.get("counts") or {}
    kept = {key: meta[key] for key in _META_KEYS if key in meta and key != "counts"}
    if counts.get("by_authority"):
        kept["counts"] = {"by_authority": counts["by_authority"]}
    return {"file": path.name, "sha256": sha, "meta": kept}


def capture(chain_key: str, *, follow_swaps: bool, max_follow_ons: int, live_tags: bool) -> dict[str, Any]:
    """The provenance of a trace on `chain_key`, as it starts."""
    from .label_store import get_label_store
    from .report import tool_version
    from .risk_matcher import LISTS

    chain = config.get_chain(chain_key)
    store = get_label_store()
    return {
        "tool_version": tool_version(),
        "captured_at": utc_now_iso(),
        "lists": {attribute: _list_entry(getattr(chain, attribute, None)) for attribute, _name, _age in LISTS},
        "label_store": {"file": store.path.name, "addresses": len(store)} if store is not None else None,
        "settings": {
            "follow_swaps": follow_swaps,
            "max_follow_ons": max_follow_ons,
            "live_tags": live_tags,
            "tx_intake": config.TX_INTAKE,
            "taint_expansion": config.TAINT_EXPANSION,
            "tracing_methods": config.TRACING_METHODS,
        },
    }


def list_metas(result: dict[str, Any]) -> dict[str, dict[str, Any] | None] | None:
    """{list attribute: its _meta as the trace saw it}, or None for a case
    stored before provenance was kept (its lists can only be today's)."""
    lists = (result.get("provenance") or {}).get("lists")
    if not isinstance(lists, dict):
        return None
    return {attribute: (entry or {}).get("meta") if entry else None for attribute, entry in lists.items()}
