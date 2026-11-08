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
CAROL = "c" * 32
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


# Two reported addresses whose money met at one unlabelled wallet.
SHARED = "0x" + "5e" * 20
A1, A2, B1 = "0x" + "a1" * 20, "0x" + "a2" * 20, "0x" + "b1" * 20


def save_converging(case_id, reported, value, owner):
    models.save_case(case_id, reported, {
        "address": reported, "chain": "ethereum", "asset": "ETH",
        "graph": {"nodes": [{"id": reported, "is_seed": True},
                            {"id": SHARED, "depth": 2, "total_in_native": value}]},
    }, owner_hash=ownership.owner_hash(owner) if owner else None)


def correlate_as(client, owner=None, case_id=None):
    headers = {ownership.OWNER_HEADER: owner} if owner else {}
    query = f"?case_id={case_id}" if case_id else ""
    response = client.get(f"/cases/correlate{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response


def test_correlation_shows_a_stranger_nothing_of_other_peoples_cases(client):
    save_converging("alice-case", A1, 3.25, ALICE)
    save_converging("bob-case", B1, 1.75, BOB)
    for stranger in (None, CAROL):
        response = correlate_as(client, stranger)
        assert response.json()["clusters"] == []
        assert response.json()["cases_examined"] == 0  # not even how many exist
        # The whole body, not named fields: a field added later cannot leak either.
        for secret in (SHARED, A1, B1, "alice-case", "bob-case", "3.25", "1.75"):
            assert secret not in response.text


def test_correlating_your_own_case_reveals_nothing_of_anyone_elses(client):
    save_converging("alice-case", A1, 3.25, ALICE)
    save_converging("bob-case", B1, 1.75, BOB)
    body = correlate_as(client, BOB, "bob-case")
    assert body.json()["cases_examined"] == 1
    assert body.json()["clusters"] == [] and body.json()["related_cases"] == []
    for secret in (A1, "alice-case", "3.25"):
        assert secret not in body.text


def test_a_case_link_opens_that_case_not_its_owners_other_cases(client):
    save_converging("alice-1", A1, 3.25, ALICE)
    save_converging("alice-2", A2, 0.5, ALICE)
    response = correlate_as(client, BOB, "alice-1")
    assert response.json()["clusters"] == []
    assert "alice-2" not in response.text and A2 not in response.text


def test_one_callers_cached_correlation_is_never_served_to_another(client):
    save_converging("alice-1", A1, 3.25, ALICE)
    save_converging("alice-2", A2, 0.5, ALICE)
    assert correlate_as(client, ALICE).json()["cluster_count"] == 1  # now cached
    response = correlate_as(client, BOB)
    assert response.json()["cluster_count"] == 0
    assert "alice-1" not in response.text and SHARED not in response.text


def test_your_own_cases_still_correlate_in_full(client):
    save_converging("alice-1", A1, 3.25, ALICE)
    save_converging("alice-2", A2, 0.5, ALICE)
    body = correlate_as(client, ALICE, "alice-1").json()
    [cluster] = body["clusters"]
    assert cluster["address"] == SHARED
    assert cluster["reported_addresses"] == [A1, A2]
    assert {m["value_in_native"] for m in cluster["cases"]} == {3.25, 0.5}
    assert not any(m.get("hidden") for m in cluster["cases"])
    [related] = body["related_cases"]
    assert related["case_id"] == "alice-2" and related["hidden"] is False


def test_demo_cases_still_correlate_with_anyones_case(client):
    save_converging("demo-case", DEMO, 2.0, None)
    save_converging("carol-case", B1, 1.75, CAROL)
    [cluster] = correlate_as(client, CAROL).json()["clusters"]
    assert cluster["reported_addresses"] == sorted([DEMO, B1])


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


def test_a_mistyped_address_does_not_spend_the_hourly_allowance(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "traces", rate_limit.SlidingWindowLimiter(1, 3600))
    for path in ("/trace", "/trace/jobs"):
        assert client.post(path, json={"address": "0xzz", "save": False}).status_code == 400
        assert client.post(path, json={"address": OTHER, "asset": "NOPE", "save": False}).status_code == 400
    assert client.post("/trace", json={"address": OTHER, "save": False}).status_code == 200


def test_client_ip_trusts_proxy_headers_only_when_told(monkeypatch):
    headers = {"x-forwarded-for": "6.6.6.6, 203.0.113.9"}
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", False)
    assert rate_limit.client_ip(headers, "10.0.0.1") == "10.0.0.1"
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
    # The proxy appended the last entry; the first could be invented.
    assert rate_limit.client_ip(headers, "10.0.0.1") == "203.0.113.9"
    assert rate_limit.client_ip({"x-real-ip": "198.51.100.4", **headers}, "10.0.0.1") == "198.51.100.4"


def test_client_ip_behind_render_believes_the_edge_not_the_client(monkeypatch):
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(config, "PROXY_CLIENT_FIRST", True)
    monkeypatch.setattr(config, "CLIENT_IP_HEADER", "cf-connecting-ip")
    # Render keeps a client-sent X-Forwarded-For and does not set X-Real-IP,
    # so neither a forged leftmost entry nor X-Real-IP may decide the key.
    headers = {"x-forwarded-for": "6.6.6.6, 203.0.113.9, 104.22.17.40", "x-real-ip": "6.6.6.6",
               "cf-connecting-ip": "203.0.113.9"}
    assert rate_limit.client_ip(headers, "10.0.0.1") == "203.0.113.9"
    assert rate_limit.client_ip({}, "10.0.0.1") == "10.0.0.1"


def test_repeated_demo_traces_are_listed_once(client):
    models.save_case("demo-old", DEMO, {"address": DEMO}, created_at="2026-09-15T00:00:00+00:00")
    models.save_case("demo-new", DEMO, {"address": DEMO}, created_at="2026-09-17T00:00:00+00:00")
    models.save_case("demo-rev", DEMO, {"address": DEMO, "direction": "incoming"},
                     created_at="2026-09-16T00:00:00+00:00")
    assert listed(client) == {"demo-new", "demo-rev"}


def test_correlation_is_recomputed_once_a_case_is_stored(client, monkeypatch):
    from app.routes import casebook as routes
    calls = []
    real = routes.index_cases
    monkeypatch.setattr(routes, "index_cases", lambda *a, **k: calls.append(1) or real(*a, **k))
    client.get("/cases/correlate")
    client.get("/cases/correlate")
    assert len(calls) == 1  # second answer from the cache
    trace(client, OTHER, ALICE)
    client.get("/cases/correlate", headers={ownership.OWNER_HEADER: ALICE})
    assert len(calls) == 2  # Alice's new case changes what she can correlate
    client.get("/cases/correlate")
    assert len(calls) == 2  # but not what a stranger can


# -- the store's cap ------------------------------------------------------------
def test_a_full_store_still_returns_the_trace_but_does_not_save_it(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "MAX_STORED_CASES", 2)
    assert trace(client, OTHER) and trace(client, OTHER)
    third = client.post("/trace", json={"address": OTHER}).json()
    assert third["case_id"] is None
    assert any("case store is full" in w for w in third["warnings"])
    assert models.case_count() == 2  # nothing deleted to make room


def test_a_failed_save_hands_back_no_case_id(client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("disk full")
    monkeypatch.setattr(models, "save_case", broken)
    body = client.post("/trace", json={"address": OTHER}).json()
    assert body["case_id"] is None  # the page must not open a case that does not exist
    assert any("could not be saved" in w for w in body["warnings"])
