"""A level is read in batches and stops at the node cap (r1-trace-engine-9).

The node cap was checked before a level and while processing it, but the
whole level was fetched first, so on a wide trace most of the last level's
reads were thrown away (287 addresses read, 120 used), and `api_calls`
counted addresses processed, not requests made.
"""
from __future__ import annotations

from contextlib import contextmanager

from app import pipeline
from app.etherscan_client import Transaction
from app.graph_builder import TraceConfig, build_trace_graph
from app.pipeline import TraceRequest, run_trace
from conftest import addr

SEED = addr("5eed")


def _fan(fan: int, depth: int) -> dict[str, list[Transaction]]:
    out: dict[str, list[Transaction]] = {}
    level, n = [SEED], 0
    for _ in range(depth):
        nxt = []
        for a in level:
            for _ in range(fan):
                n += 1
                child = "0x" + f"{n:040x}"
                out.setdefault(a, []).append(Transaction(
                    hash=f"0x{n:064x}", from_address=a, to_address=child, value_native=1.0 + n / 1e6,
                    value_wei=10**18 + n, timestamp=1_700_000_000 + n, block_number=n, is_error=False))
                nxt.append(child)
        level = nxt
    return out


HISTORY = _fan(20, 2)


class Counting:
    def __init__(self):
        self.read: list[str] = []

    def get_outgoing_transactions(self, address, limit=None):
        self.read.append(address)
        return list(HISTORY.get(address, []))


def _shape(result):
    return sorted(result.graph.nodes), sorted(result.graph.edges)


def test_a_level_stops_being_read_once_the_node_cap_is_reached():
    client = Counting()
    cfg = TraceConfig(max_depth=3, max_nodes=50, max_concurrent_fetches=6, max_branches_per_node=20)
    result = build_trace_graph(SEED, client, cfg)
    assert len(client.read) <= result.addresses_expanded + 6  # at most one batch past the cap
    assert any("node limit of 50" in r for r in result.truncation_reasons)
    assert result.addresses_read == len(client.read)


def test_batching_never_changes_the_graph():
    shapes = {
        workers: _shape(build_trace_graph(SEED, Counting(), TraceConfig(max_depth=3, max_nodes=50, max_branches_per_node=20,
                                                                        max_concurrent_fetches=workers)))
        for workers in (1, 6, 1000)  # 1000: the whole level in one batch, as before
    }
    assert shapes[1] == shapes[6] == shapes[1000]


def test_api_calls_counts_the_requests_the_provider_was_sent(monkeypatch):
    from test_request_budget import SEED as TREE_SEED, _etherscan

    calls: list = []

    @contextmanager
    def open_source(chain, asset):
        yield _etherscan(calls)
    monkeypatch.setattr(pipeline, "open_source", open_source)
    r = run_trace(TraceRequest(address=TREE_SEED, chain="ethereum", max_depth=2, follow_swaps=False))
    # The walk's reads and the wallet statement's, not one per address expanded.
    assert r["api_calls"] == len(calls) > r["addresses_expanded"]
    assert r["addresses_read"] >= r["addresses_expanded"]
