"""The case book: the caller's stored cases (/cases) and the wallets they
share (/cases/correlate). Queries over what is already stored -- no tracing."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Query, Request

from .. import config, models, ownership
from ..correlation import CaseIndex, related_cases
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


# Correlation reads and parses every case the caller may see. Stored cases
# never change, so the answer depends only on which cases go in: it is kept
# per set of case ids the caller may see, and nothing else. Callers who see
# the same cases -- every visitor with none of their own sees just the demos
# -- share one answer, a fresh owner key costs one id-only read, and a save
# changes only the answers of those who can see the new case. The key is what
# the answer was really computed from, never what was asked for, so one set's
# answer is never served to another.
#
# What the caller chooses -- min_cases, and which case the clusters must
# include -- is applied to the kept answer after the lookup, never part of
# the key: otherwise cycling through them would miss every time and reload
# every visible case on each request (r1-dos-cost-12). The kept answer is
# computed at the smallest min_cases (2), so every filter is a subset of it.
#
# A case the caller cannot list but holds the link to is not part of the key
# either (the 8 Nov check: cycling other people's case ids reloaded every
# visible case each time). The kept index of the caller's own set answers
# for it: only that one case is read (models.get_case, itself cached), and
# its addresses are looked up in the index. A case id that matches no case
# reads nothing more. The cache is bounded by entries as well as sets.
_CLUSTER_CACHE: "OrderedDict[tuple, tuple[list[tuple[str, str | None, str]], CaseIndex, list[dict[str, Any]]]]" = OrderedDict()
_CLUSTER_CACHE_SIZE = 128
_CLUSTER_CACHE_ENTRIES = 100_000  # (address, case) entries over every kept index
_cluster_entries = [0]
_cluster_lock = threading.Lock()
_FEWEST = 2  # the least min_cases the route accepts


def _key(ids) -> tuple:
    digest = hashlib.sha256("\n".join(sorted(ids)).encode()).digest()
    return (digest, models.engine())  # ids are unique within one store


def _keep(key: tuple, value) -> None:
    cost = value[1].entries()
    if cost > _CLUSTER_CACHE_ENTRIES:
        return  # one set too large to keep: computed each time, as before
    with _cluster_lock:
        if key in _CLUSTER_CACHE:
            return
        _CLUSTER_CACHE[key] = value
        _cluster_entries[0] += cost
        while _CLUSTER_CACHE and (len(_CLUSTER_CACHE) > _CLUSTER_CACHE_SIZE
                                  or _cluster_entries[0] > _CLUSTER_CACHE_ENTRIES):
            _, old = _CLUSTER_CACHE.popitem(last=False)
            _cluster_entries[0] -= old[1].entries()


def clear_cluster_cache() -> None:
    with _cluster_lock:
        _CLUSTER_CACHE.clear()
        _cluster_entries[0] = 0


def _visible(caller: str | None, refs):
    """(store, index, clusters) for the cases `caller` may list (`refs`, read just before)."""
    key = _key([r[0] for r in refs])
    with _cluster_lock:
        if key in _CLUSTER_CACHE:
            _CLUSTER_CACHE.move_to_end(key)
            return _CLUSTER_CACHE[key]
    records = ownership.correlatable_cases(caller)
    index = index_cases(records, _known_contract_or_exchange)
    value = ([(c.id, c.owner_hash, c.address) for c in records], index, index.clusters(min_cases=_FEWEST))
    # Under the ids really read: a case saved since the id read above is in them.
    _keep(_key([c.id for c in records]), value)
    return value


def index_cases(records, excluded) -> CaseIndex:
    return CaseIndex.of(records, excluded)


def _all_clusters(caller: str | None, case_id: str | None):
    """(store, clusters): who owns each case examined, and every cluster of
    at least _FEWEST reported addresses among them (with an unlisted
    case_id, only those that include it)."""
    refs = ownership.correlatable_refs(caller)
    linked = None
    if case_id and all(ref[0] != case_id for ref in refs):
        linked = models.get_case(case_id)
        if linked is None:
            return refs, []  # nothing more is read for an id that matches no case
    store, index, clusters = _visible(caller, refs)
    if linked is None:
        return store, clusters
    own = index_cases([linked], _known_contract_or_exchange)
    return ([*store, (linked.id, linked.owner_hash, linked.address)],
            index.merged(own).clusters(only_case=linked.id, min_cases=_FEWEST))


def _clusters(caller: str | None, case_id: str | None, min_cases: int):
    """(store, clusters) as correlate(only_case=case_id, min_cases=min_cases)
    would give them: the kept answer, filtered. Filtering keeps its order."""
    store, clusters = _all_clusters(caller, case_id)
    return store, [c for c in clusters
                   if len(c["reported_addresses"]) >= min_cases
                   and (case_id is None or any(m["case_id"] == case_id for m in c["cases"]))]


@router.get("/cases/correlate")
def cases_correlate(
    http: Request,
    case_id: str | None = Query(None, description="only clusters that include this case"),
    min_cases: int = Query(_FEWEST, ge=_FEWEST, le=50),
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
