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
    import app.main as main

    seen = []

    def fake_run_trace(request):
        seen.append((request.address, request.direction, request.max_depth))
        return {"exchange": "Binance", "evidence": {"from_cache": 3, "retrieved": 4}}

    monkeypatch.setattr(main, "run_trace", fake_run_trace)
    before = len(models.list_cases(limit=500))

    records = warmup.warm_once()

    assert len(seen) == 2
    assert seen[0] == ("0x" + "a1".ljust(40, "0"), "outgoing", 2)
    assert all(r["ok"] for r in records)
    assert records[0]["exchange"] == "Binance"
    assert records[0]["retrieved"] == 4
    assert len(models.list_cases(limit=500)) == before


def test_one_failing_demo_does_not_stop_the_rest(demo_file, monkeypatch):
    import app.main as main

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
    from app.main import TraceRequest

    seeds = warmup.load_demo_requests()
    assert len(seeds) >= 10
    for seed in seeds:
        request = TraceRequest(**seed)
        chain = config.get_chain(request.chain)
        assert chain.validate_address(request.address), seed
