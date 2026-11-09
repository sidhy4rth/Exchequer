"""The correlation and ledger caches cannot be emptied by the caller
(routes/casebook.py, routes/coverage.py).

The correlation cache was keyed on the raw owner key, case id and min_cases
plus the store's version, so a fresh owner key or a made-up case id on every
call forced a reload of every visible case, random ids flushed the cache for
everyone, and any save anywhere reset both caches. It is now keyed on the set
of cases the caller can actually see: callers who see the same cases share
one answer, an unknown case id never reaches the cache, and only a save into
the caller's own set changes their answer. min_cases and case_id, which the
caller also chooses, are filters on the kept answer, not part of the key, so
cycling through them never forces a reload either. The ledger reads only the
public demo cases, which no route writes, so it is built once per chain.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import models, ownership
from app.main import app
from app.routes import casebook, coverage

SHARED = "0x" + "5e" * 20
A1, A2, B1 = "0x" + "a1" * 20, "0x" + "a2" * 20, "0x" + "b1" * 20
ALICE, BOB = "alice-key-" + "a" * 22, "bob-key-" + "b" * 24


def save_converging(case_id, reported, owner):
    models.save_case(case_id, reported, {
        "address": reported, "chain": "ethereum", "asset": "ETH",
        "graph": {"nodes": [{"id": reported, "is_seed": True},
                            {"id": SHARED, "depth": 2, "total_in_native": 1.0}]},
    }, owner_hash=ownership.owner_hash(owner) if owner else None)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True))
    casebook.clear_cluster_cache()
    # These tests count reloads over many requests from one connection, not the rate limit.
    monkeypatch.setattr(casebook, "correlations", casebook.rate_limit.SlidingWindowLimiter(100_000, 60))
    with TestClient(app) as c:
        calls = []
        real = casebook.index_cases
        monkeypatch.setattr(casebook, "index_cases", lambda *a, **k: calls.append(1) or real(*a, **k))
        c.calls = calls
        yield c
    casebook.clear_cluster_cache()


def correlate_as(client, owner=None, **params):
    headers = {ownership.OWNER_HEADER: owner} if owner else {}
    response = client.get("/cases/correlate", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_callers_who_see_the_same_cases_share_one_computation(client):
    for _ in range(20):
        correlate_as(client, secrets.token_urlsafe(24))
    correlate_as(client)
    assert len(client.calls) == 1


def test_unknown_case_ids_never_reach_the_cache(client):
    for _ in range(20):
        body = correlate_as(client, case_id=secrets.token_hex(16))
        assert body["clusters"] == [] and body["related_cases"] == []
    assert client.calls == [] and len(casebook._CLUSTER_CACHE) == 0


def test_different_visible_sets_never_share_an_answer(client):
    save_converging("alice-1", A1, ALICE)
    save_converging("alice-2", A2, ALICE)
    save_converging("bob-1", B1, BOB)
    assert correlate_as(client, ALICE)["cluster_count"] == 1
    assert correlate_as(client, BOB)["cluster_count"] == 0
    assert correlate_as(client)["cluster_count"] == 0
    assert correlate_as(client, ALICE)["cluster_count"] == 1


def test_a_new_case_in_the_callers_own_set_is_correlated(client):
    save_converging("alice-1", A1, ALICE)
    assert correlate_as(client, ALICE)["cluster_count"] == 0
    correlate_as(client)
    save_converging("alice-2", A2, ALICE)
    assert correlate_as(client, ALICE)["cluster_count"] == 1
    before = len(client.calls)
    correlate_as(client)  # a stranger's set did not change: no recomputation
    assert len(client.calls) == before


def test_a_case_saved_while_the_answer_is_computed_is_never_served_to_another_set(client, monkeypatch):
    """The answer is stored under the cases it was really computed from."""
    save_converging("alice-1", A1, ALICE)
    real = ownership.correlatable_cases

    def racing(caller, case_id=None, limit=2000):
        if caller == ownership.owner_hash(BOB):
            save_converging("alice-2", A2, ALICE)  # lands between the id read and the load
        return real(caller, case_id, limit)
    monkeypatch.setattr(ownership, "correlatable_cases", racing)
    correlate_as(client, BOB)
    monkeypatch.setattr(ownership, "correlatable_cases", real)
    assert correlate_as(client, ALICE)["cluster_count"] == 1


def test_rotating_min_cases_and_case_id_never_forces_a_reload(client, monkeypatch):
    """r1-dos-cost-12: min_cases and case_id are filters applied after the
    lookup, so one caller cycling through them still costs one computation."""
    for n, reported in enumerate((A1, A2, B1)):
        save_converging(f"alice-{n}", reported, ALICE)
    loads = []
    real = ownership.correlatable_cases
    monkeypatch.setattr(ownership, "correlatable_cases", lambda *a, **k: loads.append(1) or real(*a, **k))
    for _ in range(3):
        for case_id in (None, "alice-0", "alice-1", "alice-2"):
            for min_cases in range(2, 51):
                correlate_as(client, ALICE, min_cases=min_cases, **({"case_id": case_id} if case_id else {}))
    assert len(client.calls) == 1 and len(loads) == 1
    assert len(casebook._CLUSTER_CACHE) == 1


def test_cycling_other_peoples_case_ids_never_reloads_the_callers_cases(client, monkeypatch):
    """The 8 Nov probe: a caller cycling through case ids it cannot list
    (another owner's, links it holds) forced a full reload of every case it
    can see on each request, since each id made a new cache key. The key is
    now the caller's own set; each linked case is read alone."""
    for n in range(30):
        save_converging(f"alice-{n}", "0x" + f"{n + 1:040x}", ALICE)
    bob_ids = [f"bob-{n}" for n in range(150)]
    for n, cid in enumerate(bob_ids):
        save_converging(cid, "0x" + f"{n + 1000:040x}", BOB)
    loads = []
    real = ownership.correlatable_cases
    monkeypatch.setattr(ownership, "correlatable_cases", lambda *a, **k: loads.append(1) or real(*a, **k))
    for _ in range(2):
        for cid in bob_ids:
            body = correlate_as(client, ALICE, case_id=cid)
            assert body["cases_examined"] == 31
            # Bob's case meets all 30 of Alice's at the shared wallet.
            assert body["cluster_count"] == 1 and len(body["related_cases"]) == 30
    assert len(loads) == 1
    assert len(casebook._CLUSTER_CACHE) == 1


@pytest.mark.parametrize("case_id", [None, "alice-0", "alice-2", "bob-0"])
@pytest.mark.parametrize("min_cases", [2, 3, 4])
def test_filtering_after_the_lookup_gives_the_same_answer_as_computing_it(client, case_id, min_cases):
    from app.correlation import correlate, related_cases
    for n, reported in enumerate((A1, A2, B1)):
        save_converging(f"alice-{n}", reported, ALICE)
    save_converging("bob-0", "0x" + "b2" * 20, BOB)  # a linked case: its link is held, not its owner's key
    params = {"min_cases": min_cases, **({"case_id": case_id} if case_id else {})}
    correlate_as(client, ALICE)  # fill the cache with another filter first
    body = correlate_as(client, ALICE, **params)
    direct = correlate(ownership.correlatable_cases(ownership.owner_hash(ALICE), case_id), only_case=case_id,
                       min_cases=min_cases, excluded=casebook._known_contract_or_exchange)
    assert body["cluster_count"] == len(direct)
    assert [c["address"] for c in body["clusters"]] == [c["address"] for c in direct]
    assert [c["case_count"] for c in body["clusters"]] == [c["case_count"] for c in direct]
    if case_id:
        assert [r["case_id"] for r in body["related_cases"]] == [r["case_id"] for r in related_cases(direct, case_id)]


def test_saving_a_case_does_not_rebuild_the_ledger(client, monkeypatch):
    coverage._LEDGER_CACHE.clear()
    built = []
    real = coverage._build_ledger
    monkeypatch.setattr(coverage, "_build_ledger", lambda chain: built.append(chain) or real(chain))
    client.get("/ledger?chain=ethereum&limit=50")
    save_converging("alice-1", A1, ALICE)  # an owned case: never on the public backdrop
    client.get("/ledger?chain=ethereum&limit=50")
    assert built == ["ethereum"]
    coverage._LEDGER_CACHE.clear()


# -- a large set is kept too, and correlation is rate limited (8 Nov re-check) -------------
# c8917c8 refused to keep any set whose index held more than the cache's
# 100,000 (address, case) entries, and /cases/correlate had no rate limit, so
# one owner with 100 cases of 1,100 intermediaries got a full reload (about
# 0.5 s) on every request (probe_corr_big). A set over the bound is now kept
# on its own (the others are evicted, least recently used first), and each
# connection may correlate a limited number of times a minute.

def _dense(owner, cases, nodes, first=0):
    for i in range(first, first + cases):
        reported = "0x" + f"{i + 1:040x}"
        models.save_case(f"big-{i}", reported, {
            "address": reported, "chain": "ethereum", "asset": "ETH",
            "graph": {"nodes": [{"id": reported, "is_seed": True}]
                      + [{"id": "0x" + f"{(i + 1) * 10**6 + j:040x}", "depth": 1} for j in range(nodes)]},
        }, owner_hash=ownership.owner_hash(owner))


def test_a_set_over_the_entry_bound_is_still_kept(client, monkeypatch):
    monkeypatch.setattr(casebook, "_CLUSTER_CACHE_ENTRIES", 500)
    save_converging("bob-1", B1, BOB)
    correlate_as(client, BOB)  # a small set, kept
    _dense(ALICE, 10, 60)  # 600 entries: over the bound on its own
    client.calls.clear()
    for _ in range(5):
        assert correlate_as(client, ALICE)["cases_examined"] >= 10
    assert len(client.calls) == 1  # computed once, then served from the cache
    assert casebook._cluster_entries[0] >= 600 and len(casebook._CLUSTER_CACHE) == 1  # kept alone


def test_the_cache_evicts_the_least_recently_used_set_by_entries(client, monkeypatch):
    monkeypatch.setattr(casebook, "_CLUSTER_CACHE_ENTRIES", 250)
    save_converging("a-1", A1, ALICE)
    _dense(BOB, 2, 100)  # 200 entries
    correlate_as(client, ALICE)
    correlate_as(client, BOB)
    correlate_as(client, ALICE)  # Alice's set used last
    _dense("carol-key-" + "c" * 22, 1, 100, first=2)
    correlate_as(client, "carol-key-" + "c" * 22)  # 100 more: Bob's set (least recently used) goes
    client.calls.clear()
    correlate_as(client, ALICE)
    assert client.calls == []  # still kept
    correlate_as(client, BOB)
    assert len(client.calls) == 1  # evicted, computed again
    assert casebook._cluster_entries[0] == sum(v[1].entries() for v in casebook._CLUSTER_CACHE.values())


def test_the_rechecks_probe_ten_identical_requests_reload_once(client):
    _dense(ALICE, 100, 1100)  # the probe: 110,000 entries, over the old bound
    client.calls.clear()
    for _ in range(10):
        correlate_as(client, ALICE)
    assert len(client.calls) == 1


def test_one_connection_may_correlate_only_so_often_a_minute(client, monkeypatch):
    monkeypatch.setattr(casebook, "correlations",
                        casebook.rate_limit.SlidingWindowLimiter(casebook.CORRELATIONS_PER_MINUTE_PER_CLIENT, 60))
    assert casebook.CORRELATIONS_PER_MINUTE_PER_CLIENT == 20
    for _ in range(20):
        correlate_as(client, ALICE)
    refused = client.get("/cases/correlate", headers={ownership.OWNER_HEADER: ALICE})
    assert refused.status_code == 429 and int(refused.headers["Retry-After"]) >= 1
    assert "correlat" in refused.json()["detail"].lower()
    # Fresh owner keys from the same connection do not get round it.
    assert client.get("/cases/correlate", headers={ownership.OWNER_HEADER: BOB}).status_code == 429
