"""What Exchequer can see, and whether it is up.

/health, /chains, /exchanges, /risk-labels and /ledger: read-only answers about the
label files, the screening lists and the providers. None of them touches a
chain or the case store's contents."""

from __future__ import annotations

import hmac
import logging
import random
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from .. import access, api_budget, config, label_store, models, ownership, rate_limit, signing, warmup, watchlist
from ..chain_data import provider_status
from ..exchange_matcher import get_matcher
from ..risk_matcher import (FROZEN, GAMBLING, LAUNDERING, MIXER, POISONING, SANCTIONED, SCAM, STOLEN,
                            get_risk_matcher)


logger = logging.getLogger(__name__)
router = APIRouter()


# HEAD too: uptime monitors and keep-awake pingers often send HEAD, and 405
# read as "down".
@router.api_route("/health", methods=["GET", "HEAD"])
async def health() -> dict[str, str]:
    """Liveness, for the host's health check and the uptime monitors: up or
    not, and whether anyone may start live traces ("open"), only holders of
    the demo code ("code"), or nobody ("closed") -- what GET /access already
    tells the console, where a monitor sees it. What the site can trace is
    /chains; how it is configured is /health/detail, for the operator.

    async, so it runs on the event loop: a sync route needs one of the 40
    worker threads, and when a slow database had them all, the host's health
    check failed and restarted a site that was only busy."""
    return {"status": "ok", "access": access.state()}


# The label type of a customer's deposit address at an exchange, as opposed
# to the exchange's own hot, cold or contract wallets. Counted apart because
# one matched deposit address names one customer account, and because on
# Ethereum they are most of the labels: a single total read as "25,000
# exchange wallets" when the exchanges' own wallets number about a thousand.
DEPOSIT_TYPE = "deposit_wallet"


def _chains() -> dict[str, dict[str, Any]]:
    chains = provider_status()
    for key, status in chains.items():
        matcher = get_matcher(key)
        deposits = sum(1 for _, meta in matcher.entries() if meta.get("type") == DEPOSIT_TYPE)
        status["exchange_labels"] = len(matcher)
        status["exchange_wallets"] = len(matcher) - deposits
        status["deposit_addresses"] = deposits
        status["risk_labels"] = get_risk_matcher(key).counts_by_category()
    return chains


@router.get("/chains")
def chains() -> dict[str, Any]:
    """What a visitor can trace: each chain, its assets, whether it is ready,
    and how many labels it is screened and attributed against. Public facts --
    the README publishes them -- without the reason a chain is not ready,
    which names the server's missing keys."""
    listed = _chains()
    for status in listed.values():
        status.pop("detail", None)
    return {
        "default_chain": config.DEFAULT_CHAIN.key,
        "max_depth": config.TRACE_MAX_DEPTH,
        "chains": listed,
    }


@router.get("/health/detail", include_in_schema=False)
def health_detail(request: Request) -> dict[str, Any]:
    """The configuration facts that break demos, for the operator: answers 404
    unless EXCHEQUER_HEALTH_TOKEN is set, and 401 to anything but that bearer
    token, as /admin/backup does."""
    if not config.HEALTH_TOKEN:
        raise HTTPException(status_code=404, detail="Not Found")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), config.HEALTH_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Not authorised.")
    return {
        "status": "ok",
        "etherscan_key_configured": bool(config.ETHERSCAN_API_KEY),
        "default_chain": config.DEFAULT_CHAIN.key,
        "chain_id": config.DEFAULT_CHAIN.chain_id,
        "max_depth": config.TRACE_MAX_DEPTH,
        "exchange_labels_loaded": len(get_matcher()),
        "risk_labels_loaded": len(get_risk_matcher()),
        # The on-disk label store (most of the 10.9M labels): an image built to
        # carry it that runs without it screens far less than it claims.
        "label_store": label_store.status(),
        "chains": _chains(),
        # Why a trace was slow. On the free tiers the provider, not the
        # traversal, is what costs the seconds: a high `rate_limit_penalties`
        # means the key is being refused and every refusal costs a backoff,
        # while a high cache `hit_rate` means repeat work is already free.
        "api_budget": api_budget.budget_stats(),
        # Whether the demo addresses are being (or have been) traced in the
        # background so they answer from cache. A trace during `in_progress`
        # shares the key's rate with the warm-up.
        "warm_cache": warmup.status(),
        # When watches were last checked, and whether that was too long ago:
        # on a host that sleeps when idle, the watcher sleeps too (R30).
        "watcher": watchlist.watcher_status(),
        # Which unfinished features are switched on here (config.FLAGS).
        "flags": config.FLAGS,
        # What a restart wipes. On a host without a lasting disk a SQLite case
        # store loses every case, and the provider cache starts cold.
        "storage": _storage(),
        # Whether reports signed now will still verify after a restart: a
        # temporary key means EXCHEQUER_SIGNING_KEY is missing or unreadable.
        "signing_key": {"fingerprint": signing.get_signer().fingerprint,
                        "source": signing.get_signer().source,
                        "persistent": signing.get_signer().persistent},
        # Whether live tracing needs the demo code, and whether that code is
        # long enough not to be guessed. Never the code itself.
        "access": {"state": access.state(), "public_host": config.PUBLIC_HOST,
                   "demo_code_set": bool(config.DEMO_CODE),
                   "demo_code_long_enough": len(config.DEMO_CODE) >= access.MIN_CODE_LENGTH,
                   "require_demo_code": config.REQUIRE_DEMO_CODE,
                   "pass_hours": config.DEMO_PASS_SECONDS / 3600},
        # Which address this request was counted against, and which header
        # gave it -- as fingerprints, never addresses. Send your own address
        # as X-Exchequer-Probe-Me to measure the proxy chain (rate_limit.probe).
        "client_ip": rate_limit.probe(request.headers, request.client.host if request.client else None),
    }


def _storage() -> dict[str, dict[str, Any]]:
    engine = models.engine().dialect.name
    cache = config.API_CACHE_PATH is not None
    return {
        "case_store": {"engine": engine, "temporary": config.TEMPORARY_DISK and engine == "sqlite"},
        "provider_cache": {"enabled": cache, "temporary": config.TEMPORARY_DISK and cache},
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
    # entries plus the public demo cases: built once per chain (and store).
    # A saved trace never changes it: store_result always gives a case an
    # owner, and only owner-less demo rows are read here. `limit` only slices
    # the shuffled list.
    key = (selected.key, models.engine())
    rows = _LEDGER_CACHE.get(key)
    if rows is None:
        rows = _build_ledger(selected.key)
        if len(_LEDGER_CACHE) > 16:
            _LEDGER_CACHE.clear()
        _LEDGER_CACHE[key] = rows
    return {"chain": selected.key, "count": len(rows), "entries": rows[:limit]}


_LEDGER_CACHE: dict[tuple[str, Any], list[dict[str, Any]]] = {}


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
            prefix = {SANCTIONED: "Sanctioned", MIXER: "Mixer", FROZEN: "Frozen",
                      STOLEN: "Stolen funds", GAMBLING: "Gambling platform",
                      POISONING: "Address poisoning", SCAM: "Reported scam",
                      LAUNDERING: "Laundering"}.get(meta["category"], "Flagged")
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
