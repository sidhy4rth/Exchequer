"""The startup warm-up: traces the demo addresses so they answer from cache,
and stores nothing while doing it."""
from __future__ import annotations

import json

import pytest

from app import config, models, warmup


@pytest.fixture
def demo_file(tmp_path, monkeypatch):
    path = tmp_path / "demo_traces.json"
    path.write_text(json.dumps([
        {"address": "0x" + "a1".ljust(40, "0"), "chain": "ethereum", "asset": "ETH",
         "direction": "outgoing", "max_depth": 2},
        {"address": "0x" + "b2".ljust(40, "0"), "chain": "ethereum", "asset": "ETH",
         "direction": "incoming", "max_depth": 1},
    ]))
    monkeypatch.setattr(warmup, "DEMO_TRACES_PATH", path)
    return path


def test_warm_once_runs_every_demo_and_stores_no_case(demo_file, monkeypatch):
    import app.pipeline as main

    seen = []

    def fake_run_trace(request):
        seen.append((request.address, request.direction, request.max_depth))
        return {"exchange": "Binance", "evidence": {"from_cache": 3, "retrieved": 4}}

    monkeypatch.setattr(main, "run_trace", fake_run_trace)
    before = len(models.list_cases(limit=500, everyone=True))

    records = warmup.warm_once()

    assert len(seen) == 2
    assert seen[0] == ("0x" + "a1".ljust(40, "0"), "outgoing", 2)
    assert all(r["ok"] for r in records)
    assert records[0]["exchange"] == "Binance"
    assert records[0]["retrieved"] == 4
    assert len(models.list_cases(limit=500, everyone=True)) == before


def test_one_failing_demo_does_not_stop_the_rest(demo_file, monkeypatch):
    import app.pipeline as main

    calls = []

    def flaky(request):
        calls.append(request.address)
        if len(calls) == 1:
            raise RuntimeError("provider down")
        return {"exchange": None, "evidence": None}

    monkeypatch.setattr(main, "run_trace", flaky)
    records = warmup.warm_once()
    assert len(records) == 2
    assert records[0]["ok"] is False and "provider down" in records[0]["error"]
    assert records[1]["ok"] is True


def test_warm_up_is_off_unless_configured(demo_file, monkeypatch):
    monkeypatch.setattr(config, "WARM_CACHE_AT_STARTUP", False)
    assert warmup.start_in_background() is False
    assert warmup.status()["enabled"] is False


def test_the_shipped_demo_list_is_valid_trace_requests():
    """Every entry must be something POST /trace would accept as written."""
    from app.pipeline import TraceRequest

    seeds = warmup.load_demo_requests()
    assert len(seeds) >= 10
    for seed in seeds:
        request = TraceRequest(**seed)
        chain = config.get_chain(request.chain)
        assert chain.validate_address(request.address), seed


# -- when it may run: not where its cache cannot outlive the instance ------------
@pytest.fixture
def warm_on(monkeypatch, demo_file, tmp_path):
    monkeypatch.setattr(config, "WARM_CACHE_AT_STARTUP", True)
    monkeypatch.setattr(config, "WARM_CACHE_FORCED", False, raising=False)
    monkeypatch.setattr(config, "TEMPORARY_DISK", False)
    monkeypatch.setattr(config, "API_CACHE_PATH", tmp_path / "provider_cache.db")
    started = []
    monkeypatch.setattr(warmup, "_loop", lambda interval: started.append(interval))
    monkeypatch.setattr(warmup, "_state", {**warmup._state, "enabled": False})
    return started


def test_warm_up_refuses_a_temporary_disk(warm_on, monkeypatch):
    # Render's free plan wipes the cache at every sleep: each wake would
    # re-trace every demo for nothing.
    monkeypatch.setattr(config, "TEMPORARY_DISK", True)
    assert warmup.start_in_background() is False
    assert warmup.status()["skipped"] == "temporary disk"


def test_warm_up_refuses_a_memory_only_cache(warm_on, monkeypatch):
    monkeypatch.setattr(config, "API_CACHE_PATH", None)
    assert warmup.start_in_background() is False


def test_force_overrides_the_guard(warm_on, monkeypatch):
    import time
    monkeypatch.setattr(config, "TEMPORARY_DISK", True)
    monkeypatch.setattr(config, "WARM_CACHE_FORCED", True)
    assert warmup.start_in_background() is True
    for _ in range(100):
        if warm_on:
            break
        time.sleep(0.01)
    assert warm_on


def test_each_demo_takes_a_trace_slot(demo_file, monkeypatch):
    # The warm-up shares the server's running ceiling with live traces
    # instead of running beside all of them.
    import threading

    import app.pipeline as main
    from app.routes import cases
    monkeypatch.setattr(cases, "_running", threading.BoundedSemaphore(1))
    held = []

    def fake_run_trace(request):
        held.append(not cases._running.acquire(blocking=False))
        return {"exchange": None, "evidence": None}
    monkeypatch.setattr(main, "run_trace", fake_run_trace)
    warmup.warm_once()
    assert held == [True, True]
    assert cases._running.acquire(blocking=False)  # given back after each


# -- the thread never dies quietly ------------------------------------------------
def test_a_non_object_entry_is_skipped_and_the_rest_warm(demo_file, monkeypatch):
    import app.pipeline as main
    good = json.loads(demo_file.read_text())
    demo_file.write_text(json.dumps([good[0], 7, good[1]]))
    monkeypatch.setattr(main, "run_trace", lambda request: {"exchange": None, "evidence": None})
    records = warmup.warm_once()
    assert [r["address"] for r in records] == [good[0]["address"], good[1]["address"]]


def test_a_demo_file_that_is_not_a_list_warms_nothing(demo_file):
    demo_file.write_text(json.dumps({"address": "0x"}))
    assert warmup.load_demo_requests() == []


class _StopLoop(Exception):
    pass


def test_the_loop_survives_warm_once_raising(monkeypatch):
    def broken():
        raise RuntimeError("pipeline import failed")
    monkeypatch.setattr(warmup, "warm_once", broken)

    def stop(_seconds):
        raise _StopLoop
    monkeypatch.setattr(warmup, "_wait", stop, raising=False)
    monkeypatch.setattr(warmup, "_state", {**warmup._state, "runs_completed": 0, "last_error": None})
    with pytest.raises(_StopLoop):
        warmup._loop(1)
    state = warmup.status()
    assert state["runs_completed"] == 1 and state["in_progress"] is False
    assert state["last_error"] == "RuntimeError: pipeline import failed"
    assert state["last_run"] == []
