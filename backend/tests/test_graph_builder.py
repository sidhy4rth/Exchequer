"""Tests for the BFS traversal.

The traversal spends API budget and decides what an investigator sees, so the
four brakes documented in graph_builder are what these tests pin down. The
client is a stub: a test that called a real chain could not tell a broken
brake from a rate limit.
"""
from __future__ import annotations

import pytest

from app.etherscan_client import EtherscanError, Transaction
from app.graph_builder import (
    INCOMING,
    OUTGOING,
    InvalidAddressError,
    InvalidDirectionError,
    TraceConfig,
    build_trace_graph,
    graph_to_dict,
)

from conftest import addr

SEED = addr("5eed")


def tx(src: str, dst: str, value: float, ts: int = 1_700_000_000) -> Transaction:
    return Transaction(
        hash=f"0x{abs(hash((src, dst, value))):064x}"[:66],
        from_address=src,
        to_address=dst,
        value_native=value,
        value_wei=int(value * 10**18),
        timestamp=ts,
        block_number=18_000_000,
        is_error=False,
        asset="ETH",
    )


class FakeClient:
    """Serves a fixed address -> outgoing-transfers map and counts the calls.

    The incoming view is derived from the same ledger rather than declared
    separately, so the two directions cannot drift apart and a reverse-trace
    test is genuinely walking the same transfers backwards.
    """

    def __init__(self, ledger: dict[str, list[Transaction]], fail_on: set[str] | None = None):
        self.ledger = ledger
        self.fail_on = fail_on or set()
        self.calls: list[str] = []

    def _check(self, address: str) -> None:
        self.calls.append(address)
        if address in self.fail_on:
            raise EtherscanError(f"simulated upstream failure for {address}")

    def get_outgoing_transactions(self, address, limit=None):
        self._check(address)
        return self.ledger.get(address, [])

    def get_incoming_transactions(self, address, limit=None):
        self._check(address)
        return [
            t for txs in self.ledger.values() for t in txs if t.to_address == address
        ]


def test_rejects_a_malformed_address():
    with pytest.raises(InvalidAddressError):
        build_trace_graph("not-an-address", FakeClient({}))


def test_an_address_that_never_sent_anything_yields_a_lone_seed():
    """A valid answer, not an error -- the caller must be able to tell them apart."""
    result = build_trace_graph(SEED, FakeClient({}))

    assert result.node_count == 1
    assert result.edge_count == 0
    assert result.graph.nodes[SEED]["is_seed"] is True


def test_follows_transfers_outward_hop_by_hop():
    client = FakeClient({
        SEED: [tx(SEED, addr("a1"), 10.0)],
        addr("a1"): [tx(addr("a1"), addr("b2"), 9.0)],
    })
    result = build_trace_graph(SEED, client, cfg=TraceConfig(max_depth=4))

    assert result.node_count == 3
    assert result.graph.nodes[addr("b2")]["depth"] == 2
    # depth_reached counts addresses *expanded*, and b2 is expanded (it simply
    # has nothing outgoing), so the walk did reach depth 2.
    assert result.depth_reached == 2


def test_repeated_transfers_to_one_recipient_are_a_single_edge():
    """Grouping happens before the branch limit -- that is the peel-chain shape."""
    client = FakeClient({
        SEED: [tx(SEED, addr("a1"), 4.0), tx(SEED, addr("a1"), 6.0)],
    })
    result = build_trace_graph(SEED, client)

    edge = result.graph.edges[SEED, addr("a1")]
    assert result.edge_count == 1
    assert edge["value_native"] == pytest.approx(10.0)
    assert edge["tx_count"] == 2


# ---------------------------------------------------------------------------
# The four brakes
# ---------------------------------------------------------------------------
def test_brake_1_depth_limit_stops_the_walk():
    ledger = {
        SEED: [tx(SEED, addr("a1"), 10.0)],
        addr("a1"): [tx(addr("a1"), addr("b2"), 9.0)],
        addr("b2"): [tx(addr("b2"), addr("c3"), 8.0)],
    }
    result = build_trace_graph(SEED, FakeClient(ledger), cfg=TraceConfig(max_depth=2))

    assert addr("c3") not in result.graph
    assert result.truncated is True
    assert any("depth limit" in r for r in result.truncation_reasons)


def test_brake_2_fan_out_limit_keeps_the_highest_value_destinations():
    """Laundering follows the money; dust and airdrop spam do not carry it."""
    client = FakeClient({
        SEED: [tx(SEED, addr(f"a{i}"), float(i)) for i in range(1, 6)],
    })
    result = build_trace_graph(
        SEED, client, cfg=TraceConfig(max_branches_per_node=2, min_value_native=0.0)
    )

    assert set(result.graph.successors(SEED)) == {addr("a5"), addr("a4")}
    assert any("fan-out limit" in r for r in result.truncation_reasons)


def test_brake_3_dust_is_dropped_before_ranking():
    client = FakeClient({
        SEED: [tx(SEED, addr("a1"), 10.0), tx(SEED, addr("d1"), 0.0000001)],
    })
    result = build_trace_graph(SEED, client, cfg=TraceConfig(min_value_native=0.001))

    assert addr("d1") not in result.graph
    assert addr("a1") in result.graph


def test_brake_4_expansion_stops_at_an_attributed_address():
    """Exchange hot wallets have millions of unrelated transactions."""
    exchange = addr("e11")
    ledger = {
        SEED: [tx(SEED, exchange, 10.0)],
        exchange: [tx(exchange, addr("f1"), 9.0)],
    }
    client = FakeClient(ledger)
    result = build_trace_graph(SEED, client, is_terminal=lambda a: a == exchange)

    assert addr("f1") not in result.graph
    assert exchange not in client.calls
    assert result.terminal_addresses == [exchange]
    assert result.graph.nodes[exchange]["is_terminal"] is True


def test_node_limit_stops_the_graph_growing():
    ledger = {SEED: [tx(SEED, addr(f"a{i}"), float(i)) for i in range(1, 6)]}
    result = build_trace_graph(
        SEED, FakeClient(ledger), cfg=TraceConfig(max_nodes=3, min_value_native=0.0)
    )
    assert any("node limit" in r for r in result.truncation_reasons)


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------
def test_an_unreadable_seed_is_a_hard_error():
    """An empty graph would be indistinguishable from 'never sent anything'."""
    client = FakeClient({}, fail_on={SEED})
    with pytest.raises(EtherscanError):
        build_trace_graph(SEED, client)


def test_an_unreadable_address_deeper_in_degrades_to_a_warning():
    """One unreachable wallet must not destroy the rest of the trace."""
    ledger = {SEED: [tx(SEED, addr("a1"), 10.0)]}
    client = FakeClient(ledger, fail_on={addr("a1")})
    result = build_trace_graph(SEED, client)

    assert result.node_count == 2
    assert len(result.warnings) == 1
    assert result.graph.nodes[addr("a1")]["fetch_failed"] is True


# ---------------------------------------------------------------------------
# Annotation and serialization
# ---------------------------------------------------------------------------
def test_node_totals_are_annotated_for_the_heuristics():
    ledger = {
        SEED: [tx(SEED, addr("a1"), 10.0)],
        addr("a1"): [tx(addr("a1"), addr("b2"), 6.0), tx(addr("a1"), addr("c3"), 3.0)],
    }
    result = build_trace_graph(SEED, FakeClient(ledger))
    node = result.graph.nodes[addr("a1")]

    assert node["total_in_native"] == pytest.approx(10.0)
    assert node["total_out_native"] == pytest.approx(9.0)
    assert node["in_degree"] == 1
    assert node["out_degree"] == 2
    assert node["activity_count"] == 3


def test_a_revisited_address_keeps_its_shortest_depth():
    """Confidence rewards short paths, so depth must not drift upward."""
    ledger = {
        SEED: [tx(SEED, addr("a1"), 10.0), tx(SEED, addr("b2"), 8.0)],
        addr("a1"): [tx(addr("a1"), addr("b2"), 4.0)],
    }
    result = build_trace_graph(SEED, FakeClient(ledger))
    assert result.graph.nodes[addr("b2")]["depth"] == 1


def test_graph_to_dict_drops_per_transaction_detail():
    """The frontend draws aggregate edges; shipping every hash bloats the response."""
    ledger = {SEED: [tx(SEED, addr("a1"), 10.0)]}
    result = build_trace_graph(SEED, FakeClient(ledger))
    payload = graph_to_dict(result.graph)

    assert [n["id"] for n in payload["nodes"]] == [SEED, addr("a1")]
    edge = payload["edges"][0]
    assert "transactions" not in edge
    assert edge["value_native"] == 10.0
    assert edge["flags"] == []


# ---------------------------------------------------------------------------
# Reverse traversal
# ---------------------------------------------------------------------------
def test_a_reverse_trace_walks_back_to_the_funders():
    """On a scammer's wallet these senders are the candidate other victims."""
    ledger = {
        addr("d1"): [tx(addr("d1"), SEED, 5.0)],
        addr("d2"): [tx(addr("d2"), SEED, 3.0)],
        addr("d3"): [tx(addr("d3"), addr("d1"), 5.0)],
    }
    result = build_trace_graph(SEED, FakeClient(ledger), direction=INCOMING)

    assert set(result.graph.predecessors(SEED)) == {addr("d1"), addr("d2")}
    assert result.graph.nodes[addr("d3")]["depth"] == 2
    assert result.direction == INCOMING


def test_a_reverse_trace_keeps_edges_pointing_the_way_money_moved():
    """Downstream code reads value flow, not walk order."""
    ledger = {addr("d1"): [tx(addr("d1"), SEED, 5.0)]}
    result = build_trace_graph(SEED, FakeClient(ledger), direction=INCOMING)

    assert result.graph.has_edge(addr("d1"), SEED)
    assert not result.graph.has_edge(SEED, addr("d1"))
    assert result.graph.edges[addr("d1"), SEED]["value_native"] == pytest.approx(5.0)


def test_a_reverse_trace_annotates_the_seed_as_a_receiver():
    ledger = {
        addr("d1"): [tx(addr("d1"), SEED, 5.0)],
        addr("d2"): [tx(addr("d2"), SEED, 3.0)],
    }
    result = build_trace_graph(SEED, FakeClient(ledger), direction=INCOMING)
    node = result.graph.nodes[SEED]

    assert node["total_in_native"] == pytest.approx(8.0)
    assert node["total_out_native"] == 0.0
    assert node["in_degree"] == 2


def test_the_brakes_apply_in_reverse_too():
    """A busy wallet must not blow up a reverse trace either."""
    ledger = {
        addr(f"d{i}"): [tx(addr(f"d{i}"), SEED, float(i))] for i in range(1, 6)
    }
    result = build_trace_graph(
        SEED,
        FakeClient(ledger),
        cfg=TraceConfig(max_branches_per_node=2, min_value_native=0.0),
        direction=INCOMING,
    )

    assert set(result.graph.predecessors(SEED)) == {addr("d5"), addr("d4")}
    assert any("fan-out limit" in r for r in result.truncation_reasons)


def test_a_reverse_trace_stops_at_an_exchange():
    """Funds arriving from an exchange were withdrawn there; going further
    would walk into that exchange's unrelated customer traffic."""
    exchange = addr("e11")
    ledger = {
        exchange: [tx(exchange, SEED, 5.0)],
        addr("d9"): [tx(addr("d9"), exchange, 5.0)],
    }
    client = FakeClient(ledger)
    result = build_trace_graph(
        SEED, client, is_terminal=lambda a: a == exchange, direction=INCOMING
    )

    assert addr("d9") not in result.graph
    assert exchange not in client.calls


def test_an_unknown_direction_is_rejected():
    with pytest.raises(InvalidDirectionError):
        build_trace_graph(SEED, FakeClient({}), direction="sideways")


def test_direction_defaults_to_outgoing():
    ledger = {SEED: [tx(SEED, addr("a1"), 10.0)]}
    result = build_trace_graph(SEED, FakeClient(ledger))

    assert result.direction == OUTGOING
    assert result.graph.has_edge(SEED, addr("a1"))


# ---------------------------------------------------------------------------
# Concurrent level fetching
# ---------------------------------------------------------------------------
def test_results_keep_input_order_however_the_requests_finish():
    """The graph a trace produces must not depend on network timing, so a
    slow first request must not reorder the level behind it."""
    import time

    from app.graph_builder import _fetch_level

    pending = [(addr(f"a{i}"), 1) for i in range(1, 5)]

    def fetch(address, limit=None):
        # Reverse the natural completion order: the first submitted finishes last.
        time.sleep(0.05 * (4 - int(address[3], 16)))
        return [tx(address, SEED, float(int(address[3], 16)))]

    results = _fetch_level(pending, fetch, TraceConfig())

    assert [txs[0].from_address for txs, _ in results] == [a for a, _ in pending]


def test_a_failure_is_returned_not_raised_so_the_caller_can_classify_it():
    """Fatal at the seed, a warning deeper in -- only the caller knows which."""
    from app.graph_builder import _fetch_level

    def fetch(address, limit=None):
        if address == addr("a2"):
            raise EtherscanError("boom")
        return [tx(address, SEED, 1.0)]

    results = _fetch_level([(addr("a1"), 1), (addr("a2"), 1)], fetch, TraceConfig())

    assert results[0][1] is None
    assert isinstance(results[1][1], EtherscanError)
    assert results[1][0] == []


def test_a_single_address_is_fetched_without_a_thread_pool():
    """The common case -- the seed, and any level that narrows to one."""
    from app.graph_builder import _fetch_level

    calls = []

    def fetch(address, limit=None):
        calls.append(address)
        return [tx(address, SEED, 1.0)]

    results = _fetch_level([(addr("a1"), 0)], fetch, TraceConfig())

    assert calls == [addr("a1")]
    assert results[0][1] is None


def test_concurrency_does_not_change_the_graph():
    """Same ledger, one worker or six: byte-identical result."""
    ledger = {
        SEED: [tx(SEED, addr(f"a{i}"), float(i)) for i in range(1, 6)],
        **{addr(f"a{i}"): [tx(addr(f"a{i}"), addr(f"b{i}"), float(i) / 2)] for i in range(1, 6)},
    }

    def build(workers):
        result = build_trace_graph(
            SEED,
            FakeClient(dict(ledger)),
            cfg=TraceConfig(max_concurrent_fetches=workers, min_value_native=0.0),
        )
        return graph_to_dict(result.graph)

    serial, parallel = build(1), build(6)

    assert sorted(n["id"] for n in serial["nodes"]) == sorted(n["id"] for n in parallel["nodes"])
    assert sorted((e["source"], e["target"], e["value_native"]) for e in serial["edges"]) == \
           sorted((e["source"], e["target"], e["value_native"]) for e in parallel["edges"])
