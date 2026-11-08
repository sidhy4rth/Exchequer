"""The hop count and the printed route come from one search (r1-trace-engine-11).

The case's hop count (its proximity score, the summary's "N hops") and the
route the report and the letter print must describe the same path. On a
reverse trace they came from two different searches -- one from the reported
address over the senders, one forward from the exchange -- and the widest-route
search broke ties on hops in a way that depended on which end it started from,
so an exact width tie could give "2 hops upstream" over a 3-hop printed route
(8 Nov re-check, p_rev_e2e; 1,783 of 20,000 random graphs).

The rule is now one search, read the same way everywhere: the widest route
(the one whose narrowest hop carried the most), then the fewest hops among the
widest, then the first address order from the reported address.
"""
from __future__ import annotations

import random
from contextlib import contextmanager

import networkx as nx
import pytest

from app import pipeline
from app.etherscan_client import Transaction
from app.graph_builder import INCOMING, OUTGOING
from app.pipeline import TraceRequest, run_trace
from app.scoring import principal_path, widest_routes
from conftest import addr

SEED = addr("5eed")
M1, M2 = addr("a1"), addr("a2")
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"
T = 1_700_000_000


def _random_graph(rng: random.Random) -> nx.DiGraph:
    n = rng.randint(4, 8)
    nodes = ["s"] + [f"n{i}" for i in range(n)]
    g = nx.DiGraph()
    g.add_node("s")
    for _ in range(rng.randint(n, 3 * n)):
        a, b = rng.sample(nodes, 2)
        g.add_edge(a, b, value_native=float(rng.choice([1, 2, 3, 5])))
    return g


def _fewest_hops_at_width(g: nx.DiGraph, source: str, target: str, width: float, forward: bool) -> int:
    """The fewest hops of any route whose every hop carried at least `width`."""
    wide = nx.DiGraph([(u, v) for u, v, d in g.edges(data="value_native") if d >= width])
    if not forward:
        wide = wide.reverse()
    return nx.shortest_path_length(wide, source, target)


def _bottleneck(g: nx.DiGraph, path: list[str]) -> float:
    return min(g.edges[a, b]["value_native"] for a, b in zip(path, path[1:], strict=False))


@pytest.mark.parametrize("direction", [OUTGOING, INCOMING])
def test_the_hop_count_is_the_printed_routes_length_on_random_graphs(direction):
    # A seeded fuzz: a few hundred small graphs with many exact width ties.
    rng = random.Random(20261108)
    checked = 0
    for _ in range(400):
        g = _random_graph(rng)
        reach, hops = widest_routes(g, "s", direction)
        for target, h in hops.items():
            # The route as the case prints it: money order, exchange last on a
            # forward trace and first on a reverse one.
            source, destination = ("s", target) if direction == OUTGOING else (target, "s")
            path = principal_path(g, source, destination, direction=direction)
            assert path[0] == source and path[-1] == destination
            assert len(path) - 1 == h, (direction, target, h, path, list(g.edges(data="value_native")))
            # The widest route, and the fewest hops among the widest.
            assert _bottleneck(g, path) == reach[target]
            assert h == _fewest_hops_at_width(g, "s", target, reach[target], direction == OUTGOING)
            checked += 1
    assert checked > 1000


def test_the_route_is_the_same_every_time():
    rng = random.Random(7)
    for _ in range(50):
        g = _random_graph(rng)
        shuffled = nx.DiGraph()
        shuffled.add_node("s")
        edges = list(g.edges(data=True))
        rng.shuffle(edges)
        shuffled.add_edges_from(edges)
        for direction in (OUTGOING, INCOMING):
            a = widest_routes(g, "s", direction)
            b = widest_routes(shuffled, "s", direction)
            assert a == b
            for target in a[1]:
                ends = ("s", target) if direction == OUTGOING else (target, "s")
                assert (principal_path(g, *ends, direction=direction)
                        == principal_path(shuffled, *ends, direction=direction))


def test_a_wider_but_longer_prefix_does_not_lengthen_the_route():
    # Two routes reach x: 5 wide in 3 hops and 3 wide in 1 hop. x -> t is 3
    # wide, so both routes to t are 3 wide, and the 2-hop one is the route.
    a, b, x, t = "a", "b", "x", "t"
    g = nx.DiGraph()
    for u, v, w in [("s", a, 5.0), (a, b, 5.0), (b, x, 5.0), ("s", x, 3.0), (x, t, 3.0)]:
        g.add_edge(u, v, value_native=w)
    reach, hops = widest_routes(g, "s", OUTGOING)
    assert reach[t] == 3.0 and hops[t] == 2
    assert principal_path(g, "s", t) == ["s", x, t]
    # x itself keeps its widest route.
    assert hops[x] == 3 and principal_path(g, "s", x) == ["s", a, b, x]


def test_a_reverse_trace_says_the_hops_its_route_prints():
    # 8 Nov re-check p_rev_e2e: Binance 14 -> m1 3, Binance 14 -> m2 2,
    # m2 -> m1 3, m1 -> m2 5, m2 -> seed 2. Every route to the seed is 2 wide;
    # the fewest hops is Binance 14 -> m2 -> seed. It said "2 hops upstream"
    # and printed the 3-hop route through m1.
    counter = iter(range(1, 10**6))

    def tx(s, d, v, t):
        return Transaction(hash="0x%064x" % next(counter), from_address=s, to_address=d, value_native=v,
                           value_wei=int(v * 1e18), timestamp=t, block_number=t - T + 10**6, is_error=False,
                           asset="ETH")
    history = [tx(BINANCE_14, M1, 3.0, T + 1), tx(BINANCE_14, M2, 2.0, T + 2), tx(M2, M1, 3.0, T + 3),
               tx(M1, M2, 5.0, T + 4), tx(M2, SEED, 2.0, T + 5)]

    class Fake:
        def get_outgoing_transactions(self, address, limit=None):
            return [t for t in history if t.from_address == address]

        def get_incoming_transactions(self, address, limit=None):
            return [t for t in history if t.to_address == address]

    @contextmanager
    def open_source(chain, asset):
        yield Fake()

    mp = pytest.MonkeyPatch()
    mp.setattr(pipeline, "open_source", open_source)
    mp.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
    try:
        r = run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=4, follow_swaps=False,
                                   direction="incoming"))
    finally:
        mp.undo()
    assert r["exchange"] == "Binance"
    route = [s["address"] for s in r["trace_path"]]
    assert route == [BINANCE_14, M2, SEED]
    assert r["hop_count"] == len(route) - 1 == 2
    assert "2 hops upstream" in r["confidence_detail"]["summary"]
