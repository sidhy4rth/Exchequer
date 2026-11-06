"""Every trace has a wall clock, enforced at every provider request (api_budget.TraceBudget).

The time budget used to be optional (off by default) and checked only
between fetch batches -- never inside a fetch, during retry backoff, at the
seed, or in the reads after the walk -- so one slow trace held a server slot
for as long as the provider let it. Now a trace stops expanding after the
server's default (or the smaller time it asked for, never above the
maximum), the later reads get a short grace, and nothing outlasts that.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

import httpx
import pytest
from fastapi import HTTPException

from app import api_budget, config, pipeline
from app.api_budget import DeadlineReached, TraceBudget
from app.etherscan_client import EtherscanClient, Transaction
from app.pipeline import TraceRequest, run_trace
from conftest import addr

T = 1_700_000_000


def test_the_server_default_applies_when_none_is_asked_for():
    assert TraceBudget.for_request(None).walk_seconds == config.TRACE_TIME_BUDGET_DEFAULT


def test_a_request_cannot_ask_for_more_than_the_maximum():
    assert TraceBudget.for_request(600).walk_seconds == config.TRACE_TIME_BUDGET_MAX
    assert TraceBudget.for_request(60).walk_seconds == 60


def test_a_retry_backoff_never_sleeps_past_the_deadline():
    calls = []

    def always_busy(request):
        calls.append(request)
        return httpx.Response(429)
    client = EtherscanClient(api_key="k", chain_id=1, min_interval=0.0,
                             client=httpx.Client(transport=httpx.MockTransport(always_busy)))
    client.budget = TraceBudget(0.0, 0.3)
    start = time.monotonic()
    with pytest.raises(DeadlineReached):
        client.get_outgoing_transactions("0x" + "1" * 40)
    assert time.monotonic() - start < 1.5  # 4 retries would sleep ~7.5 s
    assert len(calls) <= 2
    client.close()


def _chain_history(n: int) -> list[Transaction]:
    hops = [addr(f"{i + 1:x}") for i in range(n + 1)]
    return [Transaction(hash="0x" + f"{i + 1:064x}", from_address=a, to_address=b, value_native=1.0,
                        value_wei=10**18, timestamp=T + i, block_number=i, is_error=False, asset="ETH")
            for i, (a, b) in enumerate(zip(hops, hops[1:], strict=False))]


@pytest.fixture
def slow_provider(monkeypatch):
    history = _chain_history(12)

    class Slow:
        budget = None

        def get_outgoing_transactions(self, address, limit=None):
            time.sleep(0.25)
            if self.budget is not None:
                self.budget.check()
            return [t for t in history if t.from_address == address]

    @contextmanager
    def open_source(chain, asset):
        yield Slow()
    monkeypatch.setattr(pipeline, "open_source", open_source)
    monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
    return history[0].from_address


def test_a_slow_trace_stops_at_its_time_limit_and_says_so(slow_provider):
    start = time.monotonic()
    r = run_trace(TraceRequest(address=slow_provider, chain="ethereum", max_depth=6, follow_swaps=False),
                  budget=TraceBudget(0.6, 0.5))
    assert time.monotonic() - start < 3.0
    assert r["truncated"] is True and r["stopped_by"] == "time"
    assert r["time_limit_seconds"] == 0.6


def test_a_normal_trace_reports_its_limit_and_no_stop(slow_provider):
    r = run_trace(TraceRequest(address=slow_provider, chain="ethereum", max_depth=2, follow_swaps=False))
    assert r["time_limit_seconds"] == config.TRACE_TIME_BUDGET_DEFAULT
    assert r["stopped_by"] is None


def test_a_seed_that_cannot_be_read_in_time_is_a_clear_503(slow_provider):
    with pytest.raises(HTTPException) as exc:
        run_trace(TraceRequest(address=slow_provider, chain="ethereum", follow_swaps=False),
                  budget=TraceBudget(0.0, 0.1))
    assert exc.value.status_code == 503
    assert "time limit" in exc.value.detail


def test_the_budget_classes_are_exported():
    assert issubclass(api_budget.DeadlineReached, api_budget.TraceStopped)
