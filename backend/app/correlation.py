"""Finds intermediary addresses shared between stored cases.

One complaint gives one trace. The problem statement's actual ask is the
campaign: many complaints whose money converges on the same wallets. Every
trace is stored with its full graph, so this is a query over what has already
been traced -- no new API calls, no new tracing.

The rule, stated plainly. For every stored case, take the addresses in its
graph other than the reported address itself and other than anything with a
label of its own (an exchange hot wallet, a DEX router, a sanctioned entity):
those are the *intermediaries* -- unlabelled wallets, and inferred deposit
addresses, that the money passed through. An intermediary that appears in two
or more cases with different reported addresses is a point of convergence.
Each is returned with the cases that reach it, how far from each reported
address it sits, and how much of each case's traced value arrived there.

Exchange hot wallets are excluded on purpose. Two unrelated victims whose money
both ended at Binance 14 share nothing but a bank; two whose money reached the
same unlabelled wallet, or the same deposit address, plausibly paid the same
person. That is the difference between a coincidence and a lead.

Chains are kept apart. The same 0x string on Ethereum and BSC is two different
ledgers, and matching across them would manufacture a link no transaction
supports.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def _intermediaries(result: dict[str, Any]) -> list[dict[str, Any]]:
    seed = result.get("address")
    out = []
    for node in result.get("graph", {}).get("nodes", []):
        if node.get("is_seed") or node.get("id") == seed:
            continue
        if node.get("exchange") or node.get("is_router") or node.get("risk_category"):
            continue
        out.append(node)
    return out


def correlate(cases: Iterable[Any], only_case: str | None = None, min_cases: int = 2) -> list[dict[str, Any]]:
    """Clusters of stored cases that share an intermediary address.

    `cases` are model.Case rows (anything with `.id`, `.address`, `.created_at`
    and `.result`). `only_case` narrows the answer to clusters that include
    that case, which is what the trace view asks for.
    """
    by_key: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    inferred: dict[tuple[str, str], str] = {}

    for case in cases:
        result = case.result
        if not result:
            continue
        chain = result.get("chain") or "ethereum"
        for node in _intermediaries(result):
            key = (chain, node["id"])
            if node.get("inferred_exchange"):
                inferred[key] = node["inferred_exchange"]
            # One entry per case per address; a case that touches the same
            # wallet twice is still one case.
            by_key[key].setdefault(case.id, {
                "case_id": case.id,
                "reported_address": result.get("address") or case.address,
                "direction": result.get("direction", "outgoing"),
                "asset": result.get("asset"),
                "traced_at": case.created_at,
                "depth": node.get("depth"),
                "value_in_native": node.get("total_in_native", 0.0),
                "exchange": result.get("exchange"),
            })

    clusters = []
    for (chain, address), members in by_key.items():
        # Distinct *reported* addresses, not distinct cases: the same wallet
        # traced twice is one complaint, not two converging on itself.
        reported = {m["reported_address"] for m in members.values()}
        if len(reported) < min_cases:
            continue
        if only_case is not None and only_case not in members:
            continue
        clusters.append({
            "chain": chain,
            "address": address,
            "inferred_exchange": inferred.get((chain, address)),
            "reported_addresses": sorted(reported),
            "case_count": len(members),
            "max_value_in_native": max(m["value_in_native"] for m in members.values()),
            "cases": sorted(members.values(), key=lambda m: m["traced_at"], reverse=True),
        })

    # Most complaints first; among equals, a probable deposit address (the
    # one a request can name) before an anonymous wallet, then by the largest
    # value that reached it -- so a sidebar that shows only the top few shows
    # the ones worth acting on.
    clusters.sort(key=lambda c: (
        -len(c["reported_addresses"]),
        0 if c["inferred_exchange"] else 1,
        -c["max_value_in_native"],
        c["address"],
    ))
    return clusters
