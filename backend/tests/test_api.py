"""Tests for the endpoints that answer without touching a chain.

/trace is deliberately absent: it makes live provider calls, and a test that
did so could not tell a broken route from a rate limit. What is worth pinning
here is the shape of the answers a client depends on, and the error codes it
branches on.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_reports_every_chain(client):
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert set(body["chains"]) == {"ethereum", "bsc", "tron"}
    for chain in body["chains"].values():
        assert "exchange_labels" in chain
        assert set(chain["risk_labels"]) == {"sanctioned", "mixer", "stolen"}


def test_exchanges_lists_what_attribution_covers(client):
    """So a null attribution can be told from an absent label file."""
    body = client.get("/exchanges?chain=ethereum").json()

    assert body["chain"] == "ethereum"
    # count is labelled *addresses*; exchanges is the distinct names among them,
    # so there are always at least as many addresses as exchanges.
    assert body["count"] >= len(body["exchanges"]) > 0
    assert "Binance" in body["exchanges"]


def test_risk_labels_says_whether_screening_ran_at_all(client):
    """The same ambiguity, for the screening lists."""
    body = client.get("/risk-labels?chain=ethereum").json()

    assert body["chain"] == "ethereum"
    assert body["screened"] is (body["count"] > 0)
    assert set(body["counts_by_category"]) == {"sanctioned", "mixer", "stolen"}


def test_an_unknown_chain_is_a_400_on_both_label_endpoints(client):
    assert client.get("/exchanges?chain=dogecoin").status_code == 400
    assert client.get("/risk-labels?chain=dogecoin").status_code == 400


def test_an_unknown_case_is_a_404(client):
    response = client.get("/trace/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_a_malformed_address_is_rejected_before_any_provider_call(client):
    """A 400 here proves validation runs first -- no API budget is spent."""
    response = client.post("/trace", json={"address": "not-an-address"})
    assert response.status_code == 400
    assert "not a valid" in response.json()["detail"].lower()


def test_an_address_from_the_wrong_family_is_rejected(client):
    """A 0x address is well formed but meaningless on Tron."""
    response = client.post(
        "/trace", json={"address": "0x" + "a" * 40, "chain": "tron"}
    )
    assert response.status_code == 400
    assert "Base58" in response.json()["detail"]


def test_an_unknown_direction_is_rejected_by_the_request_model(client):
    response = client.post(
        "/trace", json={"address": "0x" + "a" * 40, "direction": "sideways"}
    )
    assert response.status_code == 422


def test_cases_lists_stored_traces(client):
    body = client.get("/cases?limit=5").json()
    assert body["count"] == len(body["cases"])
    assert body["count"] <= 5


def test_hops_covered_counts_addresses_found_not_expanded():
    """depth_reached is 0 on a one-hop trace because the addresses one hop out
    are found and never expanded -- reporting that reads as "0 hops"."""
    from app.main import _hops_covered
    from conftest import addr, make_graph

    seed = addr("5eed")
    graph = make_graph([(seed, addr("a1"), 1.0), (addr("a1"), addr("b2"), 1.0)], seed=seed)

    assert _hops_covered(graph) == 2
    assert _hops_covered(make_graph([(seed, addr("a1"), 1.0)], seed=seed)) == 1


def test_ledger_lists_real_labelled_addresses(client):
    """The sign-in backdrop draws the tool's own knowledge, nothing invented."""
    body = client.get("/ledger?chain=ethereum&limit=100").json()
    assert body["chain"] == "ethereum"
    assert body["count"] >= 400  # 337 exchange wallets + 124 OFAC addresses, at least
    assert len(body["entries"]) == 100
    kinds = {e["k"] for e in body["entries"]}
    assert kinds <= {"sanctioned", "flagged", "exchange", "inferred", "wallet"}
    for e in body["entries"]:
        assert e["a"].startswith("0x") and len(e["a"]) == 42
        if e["k"] == "exchange":
            assert e["e"]
        if e["k"] == "sanctioned":
            assert e["t"].startswith("OFAC SDN")
