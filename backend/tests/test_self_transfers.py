"""A wallet paying itself is not a branch (r1-attribution-integrity-9).

A self-send became an address->address edge: it took a fan-out slot, counted
in the wallet's totals and made both its in- and out-degree 2, so one
self-send at any hop removed the peel-chain finding the report relies on.
"""
from __future__ import annotations

from app.etherscan_client import Transaction
from app.graph_builder import INCOMING, TraceConfig, build_trace_graph, graph_to_dict
from app.pattern_detection import detect_patterns
from conftest import addr

S, P1, P2, P3, OUT = addr("5eed"), addr("b1"), addr("b2"), addr("b3"), addr("e0")


def _tx(n: int, src: str, dst: str, value: float, ts: int) -> Transaction:
    return Transaction(hash=f"0x{n:064x}", from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 10**18), timestamp=ts, block_number=ts // 12, is_error=False)


PEEL = [_tx(1, S, P1, 10, 100), _tx(2, P1, P2, 9.5, 200), _tx(3, P2, P3, 9.0, 300), _tx(4, P3, OUT, 8.5, 400)]
SELF_SEND = _tx(5, P2, P2, 9.5, 250)


class _Chain:
    def __init__(self, history):
        self.history = history

    def get_outgoing_transactions(self, address, limit=None):
        return [t for t in self.history if t.from_address == address]

    def get_incoming_transactions(self, address, limit=None):
        return [t for t in self.history if t.to_address == address]


def test_a_self_send_makes_no_self_loop():
    graph = build_trace_graph(S, _Chain(PEEL + [SELF_SEND]), TraceConfig(max_depth=5)).graph
    assert not [(u, v) for u, v in graph.edges if u == v]
    node = graph.nodes[P2]
    assert node["self_transfer_count"] == 1
    assert node["self_transfer_value_native"] == 9.5
    # Totals count only what moved between different addresses.
    assert node["total_in_native"] == 9.5 and node["total_out_native"] == 9.0
    assert node["in_degree"] == 1 and node["out_degree"] == 1
    shown = next(n for n in graph_to_dict(graph)["nodes"] if n["address"] == P2)
    assert shown["self_transfer_count"] == 1 and shown["self_transfer_value_native"] == 9.5


def test_a_peel_chain_with_a_self_send_is_still_a_peel_chain():
    plain = build_trace_graph(S, _Chain(PEEL), TraceConfig(max_depth=5)).graph
    sent_to_self = build_trace_graph(S, _Chain(PEEL + [SELF_SEND]), TraceConfig(max_depth=5)).graph
    assert [f.pattern for f in detect_patterns(plain)] == ["peel_chain"]
    assert [f.pattern for f in detect_patterns(sent_to_self)] == ["peel_chain"]


def test_a_self_send_never_takes_a_branch_slot():
    # Ten real recipients and a large self-send: all ten are still followed.
    fan = [_tx(10 + i, S, addr(f"c{i:x}"), 1.0 + i / 10, 100 + i) for i in range(10)]
    result = build_trace_graph(S, _Chain(fan + [_tx(99, S, S, 50.0, 90)]), TraceConfig(max_depth=1))
    assert set(result.graph.successors(S)) == {addr(f"c{i:x}") for i in range(10)}
    assert not result.truncated or all("fan-out" not in r for r in result.truncation_reasons)


def test_walking_back_a_self_send_is_not_a_sender():
    result = build_trace_graph(OUT, _Chain(PEEL + [_tx(6, OUT, OUT, 3.0, 450)]),
                               TraceConfig(max_depth=2), direction=INCOMING)
    assert (OUT, OUT) not in result.graph.edges
    assert result.graph.nodes[OUT]["self_transfer_count"] == 1


def test_the_report_says_where_self_transfers_were_ignored():
    import json

    from app.models import Case
    from app.report import build_report, render_text_report

    result = {"address": S, "chain": "ethereum", "asset": "ETH", "native_symbol": "ETH",
              "direction": "outgoing", "graph": {"nodes": [{"id": S}, {"id": P2, "self_transfer_count": 2}],
                                                 "edges": []},
              "transfers": [], "truncation_reasons": [], "warnings": []}
    case = Case(id="case-1", address=S, created_at="2026-09-15T12:00:00+00:00", result_json=json.dumps(result))
    assert f"Self-transfers ignored     : 2 at {P2}" in render_text_report(build_report(case))
