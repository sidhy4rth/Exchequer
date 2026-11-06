"""Batches cannot crowd out live traces (routes/batches.py, batches.py).

Each batch ran in its own thread and took any trace slot that came free, with
no limit on how many batches ran: a few batches kept every slot busy and the
console answered "traces are already running" for hours. Now all batches
together hold at most BATCH_SLOTS of the slots, a browser has one active batch
at a time, and the site at most MAX_ACTIVE_BATCHES.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import batches, config, models, ownership, pipeline, rate_limit
from app.main import app
from app.routes import batches as batch_routes
from app.routes import cases


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'b.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(config, "TRACES_RUNNING_PER_CLIENT", 2)
    monkeypatch.setattr(cases, "_running", threading.BoundedSemaphore(4))
    monkeypatch.setattr(cases, "_running_by_client", {})
    monkeypatch.setattr(batch_routes, "_batch_slots", threading.BoundedSemaphore(batches.BATCH_SLOTS))
    monkeypatch.setattr(batch_routes, "_active", {})
    for name in ("traces", "traces_total"):
        monkeypatch.setattr(rate_limit, name, rate_limit.SlidingWindowLimiter(1000, 3600))
    gate = threading.Event()
    started = []

    def slow_trace(request):
        started.append(request.address)
        gate.wait(10)
        return {"address": request.address, "chain": "ethereum"}
    monkeypatch.setattr(pipeline, "run_trace", slow_trace)
    monkeypatch.setattr(cases, "store_result", lambda payload, request, owner: {**payload, "case_id": None})
    yield SimpleNamespace(client=TestClient(app), gate=gate, started=started)
    gate.set()
    # Let every batch thread finish before the patched slots are put back.
    assert wait_for(lambda: not batch_routes._active, timeout=15)


def post_batch(client, key, n=2):
    rows = [{"address": "0x" + f"{i + 1:040x}"} for i in range(n)]
    return client.post("/batches", json={"name": "b", "rows": rows}, headers={ownership.OWNER_HEADER: key})


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_running_batches_leave_the_other_slots_to_live_traces(setup):
    for key in ("a" * 32, "b" * 32, "c" * 32):
        assert post_batch(setup.client, key).status_code == 202
    assert wait_for(lambda: len(setup.started) >= 1)
    time.sleep(0.3)
    assert len(setup.started) == batches.BATCH_SLOTS  # the other batches wait their turn
    slots = [cases.admit(SimpleNamespace(headers={}, client=SimpleNamespace(host=f"10.0.0.{i}")))
             for i in range(4 - batches.BATCH_SLOTS)]
    for slot in slots:
        cases.release(slot)


def test_one_active_batch_per_browser(setup):
    assert post_batch(setup.client, "a" * 32).status_code == 202
    second = post_batch(setup.client, "a" * 32)
    assert second.status_code == 429 and "batch" in second.json()["detail"].lower()


def test_the_site_has_a_ceiling_on_active_batches(setup):
    keys = [f"{i}" * 32 for i in range(batches.MAX_ACTIVE_BATCHES)]
    assert all(post_batch(setup.client, k).status_code == 202 for k in keys)
    over = post_batch(setup.client, "z" * 32)
    assert over.status_code == 429 and "this site" in over.json()["detail"].lower()


def test_a_finished_batch_frees_its_owner(setup):
    assert post_batch(setup.client, "a" * 32, n=1).status_code == 202
    setup.gate.set()
    assert wait_for(lambda: not batch_routes._active)
    assert post_batch(setup.client, "a" * 32, n=1).status_code == 202
