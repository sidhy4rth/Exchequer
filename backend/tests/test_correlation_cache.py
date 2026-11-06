"""The correlation and ledger caches cannot be emptied by the caller
(routes/casebook.py, routes/coverage.py).

The correlation cache was keyed on the raw owner key, case id and min_cases
plus the store's version, so a fresh owner key or a made-up case id on every
call forced a reload of every visible case, random ids flushed the cache for
everyone, and any save anywhere reset both caches. It is now keyed on the set
of cases the caller can actually see: callers who see the same cases share
one answer, an unknown case id never reaches the cache, and only a save into
the caller's own set changes their answer. The ledger reads only the public
demo cases, which no route writes, so it is built once per chain.
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
    casebook._CLUSTER_CACHE.clear()
    with TestClient(app) as c:
        calls = []
        real = casebook.correlate
        monkeypatch.setattr(casebook, "correlate", lambda *a, **k: calls.append(1) or real(*a, **k))
        c.calls = calls
        yield c
    casebook._CLUSTER_CACHE.clear()


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
