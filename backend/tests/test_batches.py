"""Bulk intake (app/batches.py, app/routes/batches.py)."""
from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import batches, models, ownership, pipeline, rate_limit
from app.main import app

ALICE = "a" * 32
A1, A2, A3 = ("0x" + c * 40 for c in "123")
SHARED = "0x" + "e" * 40
BIN = "0x28c6c06298d514db089934071355e5743bf21d60"


def fake_trace(request):
    if request.address == A3:
        raise HTTPException(status_code=502, detail="provider down")
    nodes = [{"id": request.address, "is_seed": True, "depth": 0},
             {"id": SHARED, "depth": 1}, {"id": BIN, "depth": 2, "exchange": "Binance"}]
    edges = [{"source": request.address, "target": SHARED, "value_native": 1.0},
             {"source": SHARED, "target": BIN, "value_native": 1.0}]
    return {"address": request.address, "chain": "ethereum", "asset": "ETH", "exchange": "Binance",
            "confidence": 0.7, "direction": "outgoing", "graph": {"nodes": nodes, "edges": edges}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'b.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(pipeline, "run_trace", fake_trace)
    with TestClient(app) as c:
        yield c


def wait_done(client, batch_id):
    for _ in range(100):
        body = client.get(f"/batches/{batch_id}", headers={ownership.OWNER_HEADER: ALICE}).json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("batch did not finish")


def test_rows_are_checked_before_anything_runs():
    with pytest.raises(batches.BatchError) as err:
        batches.validate_rows([{"address": A1}, {"address": "nope"}, {"address": A2, "chain": "doge"},
                               {"address": A1, "asset": "XYZ"}, {"address": A1, "depth": 9}])
    assert [e["row"] for e in err.value.row_errors] == [2, 3, 4, 5]
    with pytest.raises(batches.BatchError):
        batches.validate_rows([{"address": A1}] * (batches.MAX_ROWS + 1))
    ok = batches.validate_rows([{"address": A1, "chain": "Ethereum", "asset": "usdt", "reference": "NCRP-1"}])
    assert ok[0]["chain"] == "ethereum" and ok[0]["asset"] == "USDT" and ok[0]["reference"] == "NCRP-1"


def test_a_batch_traces_each_row_and_finds_what_they_share(client):
    h = {ownership.OWNER_HEADER: ALICE}
    started = client.post("/batches", json={"name": "Bank export", "rows": [
        {"address": A1, "reference": "C-1"}, {"address": A2, "reference": "C-2"}, {"address": A3}]}, headers=h)
    assert started.status_code == 202
    done = wait_done(client, started.json()["batch_id"])
    assert (done["done"], done["failed"]) == (2, 1)
    assert done["rows"][2]["error"] == "provider down"
    assert done["exchanges"] == [["Binance", 2]]
    shared = {w["address"]: w for w in done["shared_wallets"]}
    assert shared[SHARED]["rows"] == [1, 2] and shared[SHARED]["references"] == ["C-1", "C-2"]
    assert BIN not in shared  # an exchange is a shared bank, not a shared offender
    # The cases are ordinary cases of this browser.
    listed = {c["case_id"] for c in client.get("/cases", headers=h).json()["cases"]}
    assert {r["case_id"] for r in done["rows"][:2]} <= listed
    assert client.get(f"/batches/{done['batch_id']}", headers={ownership.OWNER_HEADER: "b" * 32}).status_code == 404


def test_bad_rows_come_back_by_number(client):
    r = client.post("/batches", json={"rows": [{"address": A1}, {"address": "x"}]},
                    headers={ownership.OWNER_HEADER: ALICE})
    assert r.status_code == 400 and r.json()["row_errors"][0]["row"] == 2


def test_a_batch_is_charged_against_the_hourly_limit_in_full(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "traces", rate_limit.SlidingWindowLimiter(2, 3600))
    r = client.post("/batches", json={"rows": [{"address": A1}, {"address": A2}, {"address": A1}]},
                    headers={ownership.OWNER_HEADER: ALICE})
    assert r.status_code == 429 and "needs 3 traces" in r.json()["detail"]


def test_a_restart_marks_unfinished_rows_interrupted(client):
    owner = ownership.owner_hash(ALICE)
    b = batches.create(owner, "", batches.validate_rows([{"address": A1}, {"address": A2}]))
    batches.mark_interrupted()
    body = batches.summary(batches.get(owner, b.id))
    assert body["status"] == "interrupted" and body["interrupted"] == 2


def test_cost_limiter_is_all_or_nothing():
    lim = rate_limit.SlidingWindowLimiter(5, 60)
    assert lim.check("k", now=0, cost=3) is None
    assert lim.check("k", now=1, cost=3) is not None  # would make 6
    assert lim.remaining("k", now=1) == 2
    assert lim.check("k", now=1, cost=2) is None
    assert lim.check("k", now=61, cost=3) is None  # the first three expired
