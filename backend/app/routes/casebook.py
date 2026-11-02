"""The case book: the caller's stored cases (/cases) and the wallets they
share (/cases/correlate). Queries over what is already stored -- no tracing."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Query, Request

from .. import config, models, ownership
from ..correlation import correlate, related_cases
from ..exchange_matcher import get_matcher, get_router_matcher

router = APIRouter()


@router.get("/cases")
def cases(http: Request, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    """History of past traces, most recent first: the caller's own cases (by
    the owner key their browser sends) and the demo cases. See ownership.py."""
    caller = ownership.owner_hash_from_headers(http.headers)
    records = models.list_cases(limit=limit, owner_hash=caller,
                                public_addresses=ownership.demo_addresses())
    # The deployed store holds the demos several times over (seeded more than
    # once); list each demo once, its newest trace. Records are newest first.
    seen_demo: set[tuple[str, str]] = set()
    kept = []
    for c in records:
        if ownership.is_public(c.owner_hash, c.address):
            key = (c.address.lower(), c.result.get("direction", "outgoing"))
            if key in seen_demo:
                continue
            seen_demo.add(key)
        kept.append(c)
    records = kept
    return {
        "count": len(records),
        "cases": [{**c.summary(), "demo": ownership.is_public(c.owner_hash, c.address)}
                  for c in records],
    }


def _known_contract_or_exchange(chain_key: str, address: str) -> bool:
    try:
        return bool(get_router_matcher(chain_key).lookup(address)
                    or get_matcher(chain_key).lookup(address))
    except config.UnknownChainError:
        return False


# Correlation reads and parses every case the caller may see, and the answer
# only changes when a case is added, so it is kept per (caller, case,
# min_cases) until the store's version moves. The caller is part of the key:
# without it, one person's answer would be served to the next. A handful of
# entries: the trace view asks once per case.
_CLUSTER_CACHE: "OrderedDict[tuple, tuple[list[tuple[str, str | None, str]], list[dict[str, Any]]]]" = OrderedDict()
_CLUSTER_CACHE_SIZE = 128
_cluster_lock = threading.Lock()


def _clusters(caller: str | None, case_id: str | None, min_cases: int):
    """(store, clusters): who owns each case examined, and the raw clusters."""
    key = (caller, case_id, min_cases, models.store_version())
    with _cluster_lock:
        if key in _CLUSTER_CACHE:
            _CLUSTER_CACHE.move_to_end(key)
            return _CLUSTER_CACHE[key]
    records = ownership.correlatable_cases(caller, case_id)
    clusters = correlate(records, only_case=case_id, min_cases=min_cases,
                         excluded=_known_contract_or_exchange)
    value = ([(c.id, c.owner_hash, c.address) for c in records], clusters)
    with _cluster_lock:
        _CLUSTER_CACHE[key] = value
        while len(_CLUSTER_CACHE) > _CLUSTER_CACHE_SIZE:
            _CLUSTER_CACHE.popitem(last=False)
    return value


@router.get("/cases/correlate")
def cases_correlate(
    http: Request,
    case_id: str | None = Query(None, description="only clusters that include this case"),
    min_cases: int = Query(2, ge=2, le=50),
) -> dict[str, Any]:
    """Intermediary addresses shared by two or more of the caller's cases.

    The campaign view: separate complaints whose traced funds converge on the
    same unlabelled wallet or the same inferred deposit address. A query over
    what is already stored -- no new tracing, no API calls. Labelled exchange
    wallets, routers and sanctioned entities are never counted as shared
    intermediaries: two victims who both cashed out at Binance share a bank,
    not an offender.

    Only the caller's own cases, the demo cases and the one they asked about
    (they hold its link) are examined; nobody else's case is read. See
    ownership.py.
    """
    caller = ownership.owner_hash_from_headers(http.headers)
    store, clusters = _clusters(caller, case_id, min_cases)
    may_see = {cid for cid, owner, address in store if ownership.visible_to(owner, address, caller)}
    if case_id:
        may_see.add(case_id)
    related = related_cases(clusters, case_id) if case_id else []
    return {
        "cases_examined": len(store),
        "cluster_count": len(clusters),
        "clusters": ownership.redact_clusters(clusters, may_see),
        # The same answer grouped by the other case, which is how the trace
        # view shows it. Empty unless case_id was given.
        "related_cases": ownership.redact_related(related, may_see),
        "rule": (
            "An intermediary is any address in a stored trace, or in its follow-on "
            "traces after a swap, other than the reported address and other than a "
            "labelled exchange wallet, DEX router, sanctioned entity or mixer; a wallet "
            "Tether froze or an explorer flagged still counts. A cluster is an intermediary reached by traces "
            f"of at least {min_cases} different reported addresses on the same chain. "
            "Contracts recognised as services (a pool, WETH) and anything in the "
            "exchange or router label files are never intermediaries."
        ),
    }
