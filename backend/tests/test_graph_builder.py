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
    # ...but the graph past that wallet is missing, and a report that did not
    # say so would present a partial picture as the whole one.
    assert result.truncated is True
    assert any("could not be fetched" in r for r in result.truncation_reasons)


# ---------------------------------------------------------------------------
# The time rule: money cannot be forwarded before it arrives
# ---------------------------------------------------------------------------
def test_transfers_made_before_the_funds_arrived_are_not_followed():
    """a1 received the traced funds at t=100. What it sent at t=50 was its own
    prior money, and following it would report a stranger's payment as the
    victim's."""
    ledger = {
        SEED: [tx(SEED, addr("a1"), 10.0, ts=100)],
        addr("a1"): [
            tx(addr("a1"), addr("b2"), 7.0, ts=50),    # before the funds arrived
            tx(addr("a1"), addr("c3"), 7.0, ts=150),   # after
        ],
    }
    result = build_trace_graph(SEED, FakeClient(ledger))

    assert addr("b2") not in result.graph
    assert addr("c3") in result.graph
    assert result.graph.nodes[addr("a1")]["window_start"] == 100
    assert result.graph.nodes[addr("a1")]["excluded_by_time"] == 1
    assert result.transfers_excluded_by_time == 1


def test_a_transfer_in_the_same_second_as_the_arrival_is_followed():
    """Funds can arrive and leave in one block; 'at or after' is the rule."""
    ledger = {
        SEED: [tx(SEED, addr("a1"), 10.0, ts=100)],
        addr("a1"): [tx(addr("a1"), addr("b2"), 9.0, ts=100)],
    }
    result = build_trace_graph(SEED, FakeClient(ledger))
    assert addr("b2") in result.graph
    assert result.transfers_excluded_by_time == 0


def test_the_earliest_of_several_arrivals_opens_the_window():
    """Two transfers brought funds in; anything after the first can carry them."""
    ledger = {
        SEED: [tx(SEED, addr("a1"), 4.0, ts=300), tx(SEED, addr("a1"), 6.0, ts=100)],
        addr("a1"): [tx(addr("a1"), addr("b2"), 3.0, ts=200)],
    }
    result = build_trace_graph(SEED, FakeClient(ledger))
    assert addr("b2") in result.graph
    assert result.graph.nodes[addr("a1")]["window_start"] == 100


def test_the_seed_itself_is_never_windowed():
    """The trace starts at the reported address and does not know when the
    victim's funds reached it, so all of its outflows are in scope."""
    ledger = {SEED: [tx(SEED, addr("a1"), 1.0, ts=10), tx(SEED, addr("b2"), 1.0, ts=900)]}
    result = build_trace_graph(SEED, FakeClient(ledger))
    assert {addr("a1"), addr("b2")} <= set(result.graph.nodes)
    assert "window_start" not in result.graph.nodes[SEED]


def test_a_reverse_trace_only_follows_money_that_was_already_there():
    """d1 paid the seed at t=100. Funds d1 received at t=150 could not have
    been what it paid with, so they are not the victim's money's origin."""
    ledger = {
        addr("d1"): [tx(addr("d1"), SEED, 5.0, ts=100)],
        addr("a1"): [tx(addr("a1"), addr("d1"), 5.0, ts=150)],   # arrived after
        addr("b1"): [tx(addr("b1"), addr("d1"), 5.0, ts=50)],    # already held
    }
    result = build_trace_graph(SEED, FakeClient(ledger), direction=INCOMING)

    assert addr("a1") not in result.graph
    assert addr("b1") in result.graph
    assert result.graph.nodes[addr("d1")]["window_end"] == 100
    assert result.transfers_excluded_by_time == 1


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


# ---------------------------------------------------------------------------
# Brake 5: a contract that pays out to many addresses is a service
# ---------------------------------------------------------------------------
def itx(src, dst, value, ts=1_700_000_100):
    """A contract-originated transfer (Etherscan txlistinternal)."""
    t = tx(src, dst, value, ts=ts)
    return Transaction(**{**t.__dict__, "internal": True})


def test_a_contract_paying_out_to_many_addresses_is_not_expanded():
    """WETH, a pool, a router: its payouts are other people's money. Reading
    internal transactions made the flagship demo expand ten of these."""
    weth = addr("c02a")
    ledger = {
        SEED: [tx(SEED, weth, 10.0)],
        weth: [itx(weth, addr(f"a{i}"), 1.0) for i in range(1, 8)],
    }
    result = build_trace_graph(SEED, FakeClient(ledger))

    assert result.graph.out_degree(weth) == 0
    assert result.graph.nodes[weth]["is_service_contract"] is True
    assert result.service_contracts == [weth]
    assert any("pays out to many" in r for r in result.truncation_reasons)


def test_a_multisig_forwarding_to_a_few_recipients_is_still_followed():
    """The reason internal transactions are read at all."""
    safe = addr("5afe")
    ledger = {
        SEED: [tx(SEED, safe, 10.0)],
        safe: [itx(safe, addr("a1"), 6.0), itx(safe, addr("a2"), 3.9)],
    }
    result = build_trace_graph(SEED, FakeClient(ledger))
    assert set(result.graph.successors(safe)) == {addr("a1"), addr("a2")}
    assert "is_service_contract" not in result.graph.nodes[safe]


def test_a_wallet_with_signed_transfers_is_never_a_service_contract():
    """A wallet paying many people is fan-out, handled by brake 2, not this."""
    busy = addr("b05")
    ledger = {
        SEED: [tx(SEED, busy, 10.0)],
        busy: [tx(busy, addr(f"a{i}"), 0.5) for i in range(1, 8)],
    }
    result = build_trace_graph(SEED, FakeClient(ledger))
    assert result.graph.out_degree(busy) == 7
    assert result.service_contracts == []


def test_the_reported_address_is_expanded_whatever_it_is():
    ledger = {SEED: [itx(SEED, addr(f"a{i}"), 1.0) for i in range(1, 8)]}
    result = build_trace_graph(SEED, FakeClient(ledger))
    assert result.graph.out_degree(SEED) == 7


def test_a_reverse_trace_stops_at_a_contract_fed_by_many():
    """Walking back into WETH would enumerate everyone who ever wrapped ETH."""
    weth = addr("c02a")
    ledger = {
        weth: [itx(weth, SEED, 5.0)],
        **{addr(f"d{i}"): [itx(addr(f"d{i}"), weth, 1.0)] for i in range(1, 8)},
    }
    result = build_trace_graph(SEED, FakeClient(ledger), direction=INCOMING)
    assert result.graph.in_degree(weth) == 0
    assert weth in result.service_contracts


# --- Brake 6: the time budget -----------------------------------------------
class SlowClient(FakeClient):
    """Every fetch takes `delay` seconds, so a budget can be made to run out."""

    def __init__(self, ledger, delay: float):
        super().__init__(ledger)
        self.delay = delay

    def get_outgoing_transactions(self, address, limit=None):
        import time
        time.sleep(self.delay)
        return super().get_outgoing_transactions(address, limit)


def _wide_ledger(levels: int = 3, fan: int = 4):
    """A seed that fans out `fan` ways at every level for `levels` hops."""
    ledger = {}
    frontier = [SEED]
    counter = 0
    for _ in range(levels):
        nxt = []
        for node in frontier:
            outs = []
            for _ in range(fan):
                counter += 1
                child = addr(f"b{counter:03x}")
                outs.append(tx(node, child, 1.0))
                nxt.append(child)
            ledger[node] = outs
        frontier = nxt
    return ledger


def test_without_a_time_budget_the_walk_is_unchanged():
    """Off by default: a config with no budget produces the same graph as before."""
    ledger = _wide_ledger()
    plain = build_trace_graph(SEED, FakeClient(ledger), cfg=TraceConfig(max_depth=3, max_branches_per_node=10))
    budgeted = build_trace_graph(SEED, FakeClient(ledger), cfg=TraceConfig(max_depth=3, max_branches_per_node=10, time_budget_seconds=60))

    assert plain.node_count == budgeted.node_count == 1 + 4 + 16 + 64
    assert budgeted.addresses_unexpanded_by_time == 0
    assert not any("time budget" in r for r in budgeted.truncation_reasons)
    assert budgeted.seconds_elapsed >= 0


def test_a_spent_time_budget_stops_the_walk_and_says_so():
    """The clock runs out: what was reached is kept, what was not read is
    counted, and the truncation names the budget."""
    ledger = _wide_ledger(levels=3, fan=4)
    # Each fetch costs 0.05 s; one batch of concurrent fetches is 0.05 s. A
    # 0.12 s budget admits the seed and roughly one level.
    client = SlowClient(ledger, delay=0.05)
    result = build_trace_graph(
        SEED, client,
        cfg=TraceConfig(max_depth=3, max_branches_per_node=10, max_concurrent_fetches=4, time_budget_seconds=0.12),
    )

    assert result.truncated
    assert any("time budget of 0 s" in r or "time budget" in r for r in result.truncation_reasons)
    assert result.addresses_unexpanded_by_time > 0
    # Nothing beyond the seed's fan-out is guaranteed, but the seed always is.
    assert result.node_count >= 1 + 4
    assert result.node_count < 1 + 4 + 16 + 64
    # The addresses the clock cut off were never asked for.
    assert len(client.calls) < 1 + 4 + 16


def test_the_reported_address_is_always_read_whatever_the_budget():
    """A budget too short for even the seed would be no trace at all."""
    ledger = _wide_ledger(levels=1, fan=3)
    client = SlowClient(ledger, delay=0.05)
    result = build_trace_graph(SEED, client, cfg=TraceConfig(max_depth=1, time_budget_seconds=0.001))

    assert client.calls[0] == SEED
    assert result.node_count == 1 + 3
