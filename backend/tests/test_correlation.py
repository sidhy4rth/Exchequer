"""Tests for cross-case correlation.

The query turns separate complaints into a campaign picture, so the tests
that matter are the ones where it must NOT link: two victims who both cashed
out at the same exchange hot wallet share a bank, not an offender.
"""
from __future__ import annotations

import json

from app.correlation import correlate
from app.models import Case

from conftest import addr


def a_case(case_id: str, seed: str, nodes: list[dict], chain: str = "ethereum", when: str = "2026-09-15T10:00:00+00:00"):
    graph_nodes = [{"id": seed, "is_seed": True, "depth": 0}] + [
        {"id": n["id"], "is_seed": False, "depth": n.get("depth", 1),
         "total_in_native": n.get("value", 1.0), "exchange": n.get("exchange"),
         "is_router": n.get("is_router", False), "risk_category": n.get("risk"),
         "inferred_exchange": n.get("inferred")}
        for n in nodes
    ]
    result = {"address": seed, "chain": chain, "asset": "ETH", "direction": "outgoing",
              "exchange": next((n.get("exchange") for n in nodes if n.get("exchange")), None),
              "graph": {"nodes": graph_nodes, "edges": []}}
    return Case(id=case_id, address=seed, created_at=when, result_json=json.dumps(result))


SHARED = addr("5a1")


def test_two_complaints_reaching_the_same_unlabelled_wallet_form_a_cluster():
    cases = [
        a_case("c1", addr("1"), [{"id": SHARED, "depth": 1, "value": 5.0}]),
        a_case("c2", addr("2"), [{"id": SHARED, "depth": 2, "value": 3.0}]),
    ]
    clusters = correlate(cases)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster["address"] == SHARED
    assert cluster["reported_addresses"] == sorted([addr("1"), addr("2")])
    assert {c["case_id"] for c in cluster["cases"]} == {"c1", "c2"}
    assert {c["value_in_native"] for c in cluster["cases"]} == {5.0, 3.0}


def test_a_shared_exchange_hot_wallet_is_a_bank_not_a_lead():
    hot = addr("b1a")
    cases = [
        a_case("c1", addr("1"), [{"id": hot, "exchange": "Binance"}]),
        a_case("c2", addr("2"), [{"id": hot, "exchange": "Binance"}]),
    ]
    assert correlate(cases) == []


def test_routers_and_sanctioned_addresses_are_not_intermediaries():
    router, listed = addr("d0"), addr("0fac")
    cases = [
        a_case("c1", addr("1"), [{"id": router, "is_router": True}, {"id": listed, "risk": "sanctioned"}]),
        a_case("c2", addr("2"), [{"id": router, "is_router": True}, {"id": listed, "risk": "sanctioned"}]),
    ]
    assert correlate(cases) == []


def test_an_inferred_deposit_address_is_a_lead_and_is_named():
    deposit = addr("de90")
    cases = [
        a_case("c1", addr("1"), [{"id": deposit, "inferred": "Binance"}]),
        a_case("c2", addr("2"), [{"id": deposit, "inferred": "Binance"}]),
    ]
    clusters = correlate(cases)
    assert clusters[0]["inferred_exchange"] == "Binance"


def test_the_same_wallet_traced_twice_is_one_complaint():
    """Re-running a trace must not make it correlate with itself."""
    cases = [
        a_case("c1", addr("1"), [{"id": SHARED}]),
        a_case("c2", addr("1"), [{"id": SHARED}], when="2026-09-15T11:00:00+00:00"),
    ]
    assert correlate(cases) == []


def test_chains_are_never_mixed():
    cases = [
        a_case("c1", addr("1"), [{"id": SHARED}], chain="ethereum"),
        a_case("c2", addr("2"), [{"id": SHARED}], chain="bsc"),
    ]
    assert correlate(cases) == []


def test_only_case_narrows_to_clusters_that_include_it():
    other = addr("5a2")
    cases = [
        a_case("c1", addr("1"), [{"id": SHARED}]),
        a_case("c2", addr("2"), [{"id": SHARED}]),
        a_case("c3", addr("3"), [{"id": other}]),
        a_case("c4", addr("4"), [{"id": other}]),
    ]
    assert [c["address"] for c in correlate(cases, only_case="c3")] == [other]
    assert correlate(cases, only_case="c9") == []


def test_clusters_are_ordered_by_how_many_complaints_converge():
    big, small = addr("b16"), addr("5a11")
    cases = [
        a_case(f"c{i}", addr(str(i)), [{"id": big}]) for i in range(1, 4)
    ] + [
        a_case("c8", addr("8"), [{"id": small}]),
        a_case("c9", addr("9"), [{"id": small}]),
    ]
    assert [c["address"] for c in correlate(cases)] == [big, small]


def test_a_corrupt_stored_case_is_skipped():
    cases = [
        Case(id="bad", address=addr("1"), created_at="2026-01-01T00:00:00+00:00", result_json="{not json"),
        a_case("c1", addr("1"), [{"id": SHARED}]),
        a_case("c2", addr("2"), [{"id": SHARED}]),
    ]
    assert len(correlate(cases)) == 1
