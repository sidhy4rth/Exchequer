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

Two refinements since. A wallet a list flags without naming who holds it -- a
Tether freeze, a stolen-funds tag, a TronScan warning -- is still somebody's
wallet, and two complaints reaching it is a stronger lead, not a weaker one; only
a sanctioned entity (already named) and a mixer (a service, not a person) are
left out. And a case's follow-on traces -- the money after a swap into a
stablecoin -- are searched too, since that is where swapped funds converge.

Chains are kept apart. The same 0x string on Ethereum and BSC is two different
ledgers, and matching across them would manufacture a link no transaction
supports.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Iterable

# Flagged, but not an intermediary: a sanctioned entity is already named, and a
# mixer is a service every user of it passes through.
NOT_INTERMEDIARY_RISKS = frozenset({"sanctioned", "mixer"})

# Decides whether (chain, address) is a labelled contract or wallet that must
# never count as an intermediary. main.py passes the exchange and router
# label files; the tests pass whatever they need.
Excluder = Callable[[str, str], bool]


def _intermediaries(result: dict[str, Any], chain: str, excluded: Excluder | None) -> list[dict[str, Any]]:
    seed = result.get("address")
    out = []
    for node in result.get("graph", {}).get("nodes", []):
        if node.get("is_seed") or node.get("id") == seed:
            continue
        if node.get("exchange") or node.get("is_router") or node.get("risk_category") in NOT_INTERMEDIARY_RISKS:
            continue
        # A contract that pays out to many addresses (WETH, a pool) is a
        # service every trace passes through; so is anything the label files
        # know, even in a case stored before the graph carried these flags.
        if node.get("is_service_contract"):
            continue
        if excluded is not None and excluded(chain, node["id"]):
            continue
        out.append(node)
    return out


def _traces(result: dict[str, Any]) -> list[tuple[dict[str, Any], str | None]]:
    """The case's own trace, then each follow-on (with the asset swapped into)."""
    out: list[tuple[dict[str, Any], str | None]] = [(result, None)]
    for follow in result.get("follow_ons") or []:
        if follow.get("result"):
            out.append((follow["result"], follow.get("asset")))
    return out


def correlate(
    cases: Iterable[Any],
    only_case: str | None = None,
    min_cases: int = 2,
    excluded: Excluder | None = None,
) -> list[dict[str, Any]]:
    """Clusters of stored cases that share an intermediary address.

    `cases` are model.Case rows (anything with `.id`, `.address`, `.created_at`
    and `.result`). `only_case` narrows the answer to clusters that include
    that case, which is what the trace view asks for. `excluded` says which
    addresses are known contracts or exchange wallets on a chain.
    """
    by_key: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    inferred: dict[tuple[str, str], str] = {}
    flagged: dict[tuple[str, str], str] = {}

    for case in cases:
        result = case.result
        if not result:
            continue
        chain = result.get("chain") or "ethereum"
        for trace, swapped_to in _traces(result):
            for node in _intermediaries(trace, chain, excluded):
                key = (chain, node["id"])
                if node.get("inferred_exchange"):
                    inferred[key] = node["inferred_exchange"]
                if node.get("risk_category"):
                    flagged[key] = node["risk_category"]
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
                    "after_swap_to": swapped_to,
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
            "risk_category": flagged.get((chain, address)),
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


def related_cases(clusters: list[dict[str, Any]], case_id: str) -> list[dict[str, Any]]:
    """The same answer regrouped by the *other* case, for the trace view.

    An investigator reading a trace wants "which other complaints does this
    one touch, and through what", not a list of wallets each naming cases.
    One entry per other *reported address*, carrying every shared
    intermediary, most shared first; within a case, probable deposit addresses
    first, then by value.

    Two exclusions keep the list honest. An earlier trace of the same reported
    address is not a related case -- a wallet cannot corroborate itself, and
    the store holds repeat traces of the same address at different depths.
    And another address traced several times is one complaint, so only its
    most recent trace is listed.
    """
    own_address: str | None = None
    for cluster in clusters:
        for m in cluster["cases"]:
            if m["case_id"] == case_id:
                own_address = (m["reported_address"] or "").lower()
                break
        if own_address is not None:
            break

    by_case: dict[str, dict[str, Any]] = {}
    latest_for_address: dict[str, str] = {}
    for cluster in clusters:
        if not any(m["case_id"] == case_id for m in cluster["cases"]):
            continue
        for member in cluster["cases"]:
            if member["case_id"] == case_id:
                continue
            reported = (member["reported_address"] or "").lower()
            if reported == own_address:
                continue
            chosen = latest_for_address.setdefault(reported, member["case_id"])
            if chosen != member["case_id"]:
                # cluster["cases"] is newest first, so the first case seen for
                # an address is its most recent trace; older ones are skipped.
                continue
            entry = by_case.setdefault(member["case_id"], {
                "case_id": member["case_id"],
                "reported_address": member["reported_address"],
                "chain": cluster["chain"],
                "asset": member["asset"],
                "traced_at": member["traced_at"],
                "exchange": member["exchange"],
                "shared": [],
            })
            entry["shared"].append({
                "address": cluster["address"],
                "inferred_exchange": cluster["inferred_exchange"],
                "risk_category": cluster["risk_category"],
                "after_swap_to": member["after_swap_to"],
                "depth": member["depth"],
                "value_in_native": member["value_in_native"],
            })
    for entry in by_case.values():
        entry["shared"].sort(key=lambda s: (0 if s["inferred_exchange"] else 1, -s["value_in_native"]))
        entry["shared_count"] = len(entry["shared"])
    return sorted(by_case.values(), key=lambda e: (-e["shared_count"], e["traced_at"]), reverse=False)
