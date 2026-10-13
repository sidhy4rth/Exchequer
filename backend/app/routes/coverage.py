"""What Exchequer can see, and whether it is up.

/health, /exchanges, /risk-labels and /ledger: read-only answers about the
label files, the screening lists and the providers. None of them touches a
chain or the case store's contents."""

from __future__ import annotations

import logging
import random
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .. import api_budget, config, models, ownership, warmup
from ..chain_data import provider_status
from ..exchange_matcher import get_matcher
from ..risk_matcher import FROZEN, MIXER, SANCTIONED, get_risk_matcher


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
def health() -> dict[str, Any]:
    """Liveness probe, plus the configuration facts that break demos."""
    chains = provider_status()
    for key, status in chains.items():
        status["exchange_labels"] = len(get_matcher(key))
        status["risk_labels"] = get_risk_matcher(key).counts_by_category()
    return {
        "status": "ok",
        "etherscan_key_configured": bool(config.ETHERSCAN_API_KEY),
        "default_chain": config.DEFAULT_CHAIN.key,
        "chain_id": config.DEFAULT_CHAIN.chain_id,
        "max_depth": config.TRACE_MAX_DEPTH,
        # Kept for the existing frontend status line: labels on the default chain.
        "exchange_labels_loaded": len(get_matcher()),
        "risk_labels_loaded": len(get_risk_matcher()),
        "chains": chains,
        # Why a trace was slow. On the free tiers the provider, not the
        # traversal, is what costs the seconds: a high `rate_limit_penalties`
        # means the key is being refused and every refusal costs a backoff,
        # while a high cache `hit_rate` means repeat work is already free.
        "api_budget": api_budget.budget_stats(),
        # Whether the demo addresses are being (or have been) traced in the
        # background so they answer from cache. A trace during `in_progress`
        # shares the key's rate with the warm-up.
        "warm_cache": warmup.status(),
    }


@router.get("/exchanges")
def exchanges(chain: str | None = Query(None, description="ethereum or bsc")) -> dict[str, Any]:
    """What the attribution database covers.

    Exposed so a user can see immediately whether a null attribution means
    "the funds went nowhere known" or "we do not have labels for that exchange".
    """
    try:
        selected = config.get_chain(chain)
    except config.UnknownChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    matcher = get_matcher(selected.key)
    return {
        "chain": selected.key,
        "chain_name": selected.name,
        "count": len(matcher),
        "exchanges": matcher.exchanges,
    }


@router.get("/risk-labels")
def risk_labels(chain: str | None = Query(None, description="ethereum, bsc or tron")) -> dict[str, Any]:
    """What the sanctions and mixer screening covers.

    The counterpart to /exchanges, and exposed for the same reason: without it
    a trace reporting no sanctions hit is ambiguous between "nothing in this
    trace is listed" and "this chain has no risk labels loaded at all". Those
    two answers are very different and an investigator has to be able to tell
    them apart.
    """
    try:
        selected = config.get_chain(chain)
    except config.UnknownChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    matcher = get_risk_matcher(selected.key)
    return {
        "chain": selected.key,
        "chain_name": selected.name,
        "count": len(matcher),
        "counts_by_category": matcher.counts_by_category(),
        "entities": matcher.entities,
        "screened": len(matcher) > 0,
    }


@router.get("/ledger")
def ledger(chain: str | None = Query(None), limit: int = Query(1400, ge=50, le=4000)) -> dict[str, Any]:
    """The addresses the tool knows, for the sign-in page's backdrop.

    Every entry is real: the exchange wallets it attributes to, the
    sanctions list it screens against, the deposit addresses it has inferred
    and the unlabelled intermediaries of the demo cases. Each carries only
    what the case view would show -- the kind, the exchange, the label -- so
    the page can colour it the same way. Shuffled with a fixed seed so the
    sea looks the same on every load.
    """
    try:
        selected = config.get_chain(chain)
    except config.UnknownChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # The sign-in page asks on every load, and the answer is ~30,000 label
    # entries plus the demo cases: built once per chain and kept until a case
    # is stored. `limit` only slices the shuffled list.
    key = (selected.key, models.store_version())
    rows = _LEDGER_CACHE.get(key)
    if rows is None:
        rows = _build_ledger(selected.key)
        if len(_LEDGER_CACHE) > 16:
            _LEDGER_CACHE.clear()
        _LEDGER_CACHE[key] = rows
    return {"chain": selected.key, "count": len(rows), "entries": rows[:limit]}


_LEDGER_CACHE: dict[tuple[str, int], list[dict[str, Any]]] = {}


def _build_ledger(chain_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(address: str, kind: str, exchange: str = "", label: str = "") -> None:
        if address in seen:
            return
        seen.add(address)
        rows.append({"a": address, "k": kind, "e": exchange, "t": label})

    for address, meta in get_risk_matcher(chain_key).entries():
        if meta["category"] == SANCTIONED and meta.get("source", "").startswith("OFAC"):
            add(address, "sanctioned", "", f"OFAC SDN · {meta.get('entity', '')}"[:48])
        else:
            prefix = {SANCTIONED: "Sanctioned", MIXER: "Mixer",
                      FROZEN: "Frozen by Tether"}.get(meta["category"], "Stolen funds")
            add(address, "flagged", "", f"{prefix} · {meta.get('label', '')}"[:48])
    for address, meta in get_matcher(chain_key).entries():
        add(address, "exchange", meta.get("exchange", ""), (meta.get("label") or meta.get("exchange", ""))[:40])
    # Only the public demo cases: this endpoint backs a page anyone can open,
    # and another person's trace would put their reported address on it.
    for case in models.list_cases(limit=200, public_addresses=ownership.demo_addresses()):
        result = case.result
        if result.get("chain") != chain_key:
            continue
        for match in result.get("inferred_deposits", []):
            add(match["address"], "inferred", match["exchange"], f"probable {match['exchange']} deposit")
        for node in result.get("graph", {}).get("nodes", []):
            if node.get("exchange") or node.get("risk_category") or node.get("is_router") or node.get("is_service_contract"):
                continue
            add(node["id"], "wallet", "", "reported address" if node.get("is_seed") else "")
    random.Random(4).shuffle(rows)
    return rows
