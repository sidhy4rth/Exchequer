"""Server-wide hourly ceilings on what spends the provider quota.

Every per-client limit is keyed on the client's address as the proxy headers
report it, and those headers may be set by the client itself. A ceiling over
all clients cannot be dodged that way: traces (a batch counts each row) and
watches stop for everyone once the site has started its hourly maximum.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import config, models, ownership, rate_limit
from app.main import app
from app.routes import cases


def http(ip: str) -> SimpleNamespace:
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'g.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(config, "TRACES_RUNNING_PER_CLIENT", 2)
    monkeypatch.setattr(cases, "_running", threading.BoundedSemaphore(4))
    monkeypatch.setattr(cases, "_running_by_client", {})
    monkeypatch.setattr(rate_limit, "traces", rate_limit.SlidingWindowLimiter(30, 3600))
    monkeypatch.setattr(rate_limit, "traces_total", rate_limit.SlidingWindowLimiter(3, 3600))
    monkeypatch.setattr(rate_limit, "watches", rate_limit.SlidingWindowLimiter(20, 3600))
    monkeypatch.setattr(rate_limit, "watches_total", rate_limit.SlidingWindowLimiter(2, 3600))


def test_traces_stop_for_everyone_at_the_site_wide_ceiling():
    for i in range(3):  # three different "clients", as a rotated header would make them
        cases.release(cases.admit(http(f"10.0.0.{i}")))
    with pytest.raises(HTTPException) as exc:
        cases.admit(http("10.0.0.99"))
    assert exc.value.status_code == 429 and "this site" in exc.value.detail.lower()
    # The refused client was not charged, and no slot leaked.
    assert rate_limit.traces.remaining("10.0.0.99") == 30
    assert cases._running_by_client == {}
    assert all(cases._running.acquire(blocking=False) for _ in range(4))


def test_a_batch_counts_every_row_against_the_ceiling():
    client = TestClient(app)
    owner = {ownership.OWNER_HEADER: "o" * 32}
    rows = [{"address": "0x" + f"{i:040x}"} for i in range(1, 5)]
    response = client.post("/batches", json={"name": "b", "rows": rows}, headers=owner)
    assert response.status_code == 429 and "this site" in response.json()["detail"].lower()
    assert rate_limit.traces.remaining("testclient") == 30


def test_watches_stop_for_everyone_at_the_site_wide_ceiling():
    client = TestClient(app)
    made = []
    for i in range(3):
        headers = {ownership.OWNER_HEADER: f"{i}" * 32}
        made.append(client.post("/watches", json={"address": "0x" + f"{i + 1:040x}"}, headers=headers).status_code)
    assert made[:2] == [201, 201]
    assert made[2] == 429


def test_asking_about_a_client_never_adds_it():
    # The demo-code middleware asks remaining() on every guarded request;
    # each new (possibly invented) address used to stay in memory for good.
    limiter = rate_limit.SlidingWindowLimiter(10, 3600)
    for i in range(20_000):
        assert limiter.remaining(f"10.{i // 65536}.{i // 256 % 256}.{i % 256}") == 10
    assert len(limiter._hits) == 0


def test_clients_whose_hits_have_expired_are_forgotten():
    limiter = rate_limit.SlidingWindowLimiter(10, 60)
    for i in range(12_000):
        limiter.check(f"old-{i}", now=0.0)
    limiter.check("new", now=1_000.0)  # long after every old hit expired
    assert set(limiter._hits) == {"new"}
