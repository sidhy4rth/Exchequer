"""The operator's depth setting is a ceiling, and an address is bounded (r1-authz-routes-9).

TraceRequest.max_depth was checked against a literal 6, so an operator who
lowered TRACE_MAX_DEPTH to save quota was overridden by any caller asking for
6; batch rows allowed 6 the same way. An invalid address of any length was
quoted whole in the 400 detail.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import batches, config, pipeline
from app.etherscan_client import Transaction
from app.main import app
from app.pipeline import TraceRequest, run_trace
from conftest import addr

T = 1_700_000_000


@pytest.fixture
def chain_provider(monkeypatch):
    hops = [addr(f"{i + 1:x}") for i in range(10)]
    history = [Transaction(hash="0x" + f"{i + 1:064x}", from_address=a, to_address=b, value_native=1.0,
                           value_wei=10**18, timestamp=T + i, block_number=i + 1, is_error=False, asset="ETH")
               for i, (a, b) in enumerate(zip(hops, hops[1:], strict=False))]

    class Chain:
        budget = None

        def get_outgoing_transactions(self, address, limit=None):
            return [t for t in history if t.from_address == address]

        def close(self):
            pass

    @contextmanager
    def open_source(chain, asset):
        yield Chain()
    monkeypatch.setattr(pipeline, "open_source", open_source)
    monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
    return hops[0]


def test_a_request_cannot_go_deeper_than_the_servers_ceiling(chain_provider, monkeypatch):
    monkeypatch.setattr(config, "TRACE_MAX_DEPTH_CEILING", 2)
    r = run_trace(TraceRequest(address=chain_provider, chain="ethereum", max_depth=6, follow_swaps=False))
    assert r["max_depth"] == 2
    assert max(n["depth"] for n in r["graph"]["nodes"]) == 2
    assert any("capped at 2 hops" in w for w in r["warnings"])


def test_a_request_within_the_ceiling_is_unchanged(chain_provider, monkeypatch):
    monkeypatch.setattr(config, "TRACE_MAX_DEPTH_CEILING", 6)
    r = run_trace(TraceRequest(address=chain_provider, chain="ethereum", max_depth=3, follow_swaps=False))
    assert r["max_depth"] == 3
    assert not any("capped at" in w for w in r["warnings"])


def test_the_default_depth_never_exceeds_the_ceiling(chain_provider, monkeypatch):
    monkeypatch.setattr(config, "TRACE_MAX_DEPTH", 4)
    monkeypatch.setattr(config, "TRACE_MAX_DEPTH_CEILING", 3)
    assert run_trace(TraceRequest(address=chain_provider, chain="ethereum", follow_swaps=False))["max_depth"] == 3


def test_a_batch_row_deeper_than_the_ceiling_is_refused_and_names_it(monkeypatch):
    monkeypatch.setattr(config, "TRACE_MAX_DEPTH_CEILING", 4)
    with pytest.raises(batches.BatchError) as exc:
        batches.validate_rows([{"address": addr("a1"), "depth": 6}])
    assert "1 to 4" in exc.value.row_errors[0]["error"]
    assert batches.validate_rows([{"address": addr("a1"), "depth": 4}])[0]["max_depth"] == 4


def test_an_overlong_address_is_refused_by_the_model():
    with pytest.raises(ValidationError):
        TraceRequest(address="0x" + "a" * 2000, chain="ethereum")


def test_a_bad_address_is_quoted_short_in_the_error():
    bad = "0x" + "z" * 120
    with pytest.raises(HTTPException) as exc:
        pipeline.check_request(TraceRequest(address=bad, chain="ethereum"))
    assert exc.value.status_code == 400
    assert bad not in exc.value.detail and bad[:40] in exc.value.detail


def test_chains_states_the_depth_ceiling(monkeypatch):
    monkeypatch.setattr(config, "TRACE_MAX_DEPTH_CEILING", 5)
    with TestClient(app) as client:
        body = client.get("/chains").json()
    assert body["max_depth_ceiling"] == 5
