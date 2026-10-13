"""Who sees which case (app/ownership.py) and the trace rate limit (app/rate_limit.py).

Runs against a throwaway SQLite file, never the real case store.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import config, models, ownership, pipeline, rate_limit
from app.main import app

ALICE = "a" * 32
BOB = "b" * 32
DEMO = "0x60d02e0956e2f3795167c15ba61ab452c85c2533"  # in data/demo_traces.json
OTHER = "0x" + "1" * 40


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'cases.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    return engine


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(pipeline, "run_trace",
                        lambda request: {"address": request.address, "chain": "ethereum"})
    with TestClient(app) as c:
        yield c


def trace(client, address, owner=None):
    headers = {ownership.OWNER_HEADER: owner} if owner else {}
    response = client.post("/trace", json={"address": address}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["case_id"]


def listed(client, owner=None):
    headers = {ownership.OWNER_HEADER: owner} if owner else {}
    return {c["case_id"] for c in client.get("/cases?limit=100", headers=headers).json()["cases"]}


# -- the owner key -------------------------------------------------------------
def test_owner_hash_accepts_only_well_formed_keys():
    assert ownership.owner_hash(ALICE) and len(ownership.owner_hash(ALICE)) == 64
    assert ownership.owner_hash(ALICE) != ownership.owner_hash(BOB)
    for bad in (None, "", "short", "x" * 200, "a" * 30 + "!?"):
        assert ownership.owner_hash(bad) is None


# -- the history list ----------------------------------------------------------
def test_each_browser_lists_only_its_own_cases(client):
    a = trace(client, OTHER, ALICE)
    b = trace(client, OTHER, BOB)
    assert listed(client, ALICE) == {a}
    assert listed(client, BOB) == {b}
    assert listed(client) == set()


def test_a_trace_without_a_key_is_listed_for_nobody(client):
    case_id = trace(client, OTHER)
    assert case_id not in listed(client) | listed(client, ALICE)
    # ...but its link still opens it.
    assert client.get(f"/trace/{case_id}").status_code == 200


def test_old_demo_cases_stay_public_and_other_old_cases_do_not(client):
    models.save_case("demo-case", DEMO, {"address": DEMO})
    models.save_case("old-case", OTHER, {"address": OTHER})
    body = client.get("/cases", headers={ownership.OWNER_HEADER: ALICE}).json()
    ids = {c["case_id"]: c for c in body["cases"]}
    assert "demo-case" in ids and ids["demo-case"]["demo"] is True
    assert "old-case" not in ids
    assert client.get("/trace/old-case").status_code == 200


def test_a_new_trace_of_a_demo_address_is_owned_not_public(client):
    case_id = trace(client, DEMO, ALICE)
    assert case_id in listed(client, ALICE)
    assert case_id not in listed(client, BOB)


# -- correlation ---------------------------------------------------------------
def test_other_peoples_cases_are_anonymised_in_correlation():
    clusters = [{
        "address": "0xshared", "chain": "ethereum",
        "cases": [
            {"case_id": "mine", "reported_address": "0xa", "traced_at": "t", "value_in_native": 1.0},
            {"case_id": "theirs", "reported_address": "0xb", "traced_at": "t", "value_in_native": 9.0},
        ],
        "reported_addresses": ["0xa", "0xb"],
    }]
    out = ownership.redact_clusters(clusters, {"mine"})[0]
    assert out["reported_addresses"] == ["0xa"]
    assert out["other_complaints"] == 1
    hidden = out["cases"][1]
    assert hidden["case_id"] is None and hidden["reported_address"] is None
    assert hidden["value_in_native"] is None and hidden["hidden"] is True

    related = [{"case_id": "theirs", "reported_address": "0xb", "traced_at": "t",
                "exchange": "Binance", "shared": [{"address": "0xshared", "value_in_native": 9.0}]}]
    entry = ownership.redact_related(related, {"mine"})[0]
    assert entry["case_id"] is None and entry["reported_address"] is None
    assert entry["ref"] == "Another complaint #1" and entry["exchange"] == "Binance"
    assert entry["shared"][0] == {"address": "0xshared", "value_in_native": None}


# -- the ledger ----------------------------------------------------------------
def test_ledger_never_shows_another_persons_reported_address(client):
    models.save_case("private", OTHER, {
        "address": OTHER, "chain": "ethereum",
        "graph": {"nodes": [{"id": OTHER, "is_seed": True}]},
    }, owner_hash=ownership.owner_hash(ALICE))
    entries = client.get("/ledger?chain=ethereum&limit=4000").json()["entries"]
    assert OTHER not in {e["a"] for e in entries}


# -- migration -----------------------------------------------------------------
def test_an_old_store_gains_the_owner_column(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE cases (id VARCHAR(36) PRIMARY KEY, address VARCHAR(42), "
                          "created_at VARCHAR(32), result_json TEXT)"))
        conn.execute(text("INSERT INTO cases VALUES ('x', :a, 't', '{}')"), {"a": DEMO})
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    models.init_db()  # idempotent
    assert models.get_case("x").owner_hash is None


# -- rate limit ----------------------------------------------------------------
def test_sliding_window_limits_and_recovers():
    limiter = rate_limit.SlidingWindowLimiter(2, 60)
    assert limiter.check("ip", now=0) is None
    assert limiter.check("ip", now=1) is None
    assert limiter.check("ip", now=2) == pytest.approx(58)
    assert limiter.check("other", now=2) is None
    assert limiter.check("ip", now=61) is None


def test_trace_endpoint_turns_away_a_client_over_its_hourly_limit(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "traces", rate_limit.SlidingWindowLimiter(2, 3600))
    body = {"address": OTHER, "save": False}
    assert client.post("/trace", json=body).status_code == 200
    assert client.post("/trace", json=body).status_code == 200
    refused = client.post("/trace", json=body)
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) > 0


def test_client_ip_trusts_proxy_headers_only_when_told(monkeypatch):
    headers = {"x-forwarded-for": "6.6.6.6, 203.0.113.9"}
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", False)
    assert rate_limit.client_ip(headers, "10.0.0.1") == "10.0.0.1"
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
    # The proxy appended the last entry; the first could be invented.
    assert rate_limit.client_ip(headers, "10.0.0.1") == "203.0.113.9"
    assert rate_limit.client_ip({"x-real-ip": "198.51.100.4", **headers}, "10.0.0.1") == "198.51.100.4"


def test_repeated_demo_traces_are_listed_once(client):
    models.save_case("demo-old", DEMO, {"address": DEMO}, created_at="2026-09-15T00:00:00+00:00")
    models.save_case("demo-new", DEMO, {"address": DEMO}, created_at="2026-09-17T00:00:00+00:00")
    models.save_case("demo-rev", DEMO, {"address": DEMO, "direction": "incoming"},
                     created_at="2026-09-16T00:00:00+00:00")
    assert listed(client) == {"demo-new", "demo-rev"}
