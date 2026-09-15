"""Shared fixtures for the TraceChain test suite.

The rules under test (pattern detection, scoring) are pure functions over a
networkx graph, so nothing here touches the network, an API key, or the
database. A test that needed a live chain could not tell a broken rule from a
rate limit, which is the opposite of what these tests are for.
"""
from __future__ import annotations

import sys
from pathlib import Path

import networkx as nx
import pytest

# backend/tests/conftest.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.graph_builder import _annotate_node_totals  # noqa: E402


def addr(tag: str) -> str:
    """A syntactically valid EVM address that is readable in a failure message.

    `addr("a1")` -> 0xa1000...0000. Real addresses would make an assertion
    error unreadable, and the rules never inspect an address's content.
    """
    body = tag.lower().replace("_", "")
    if not all(c in "0123456789abcdef" for c in body):
        raise ValueError(f"tag {tag!r} must be hex so it forms a valid address")
    return "0x" + body.ljust(40, "0")


def make_graph(
    edges: list[tuple[str, str, float]],
    seed: str | None = None,
    exchanges: dict[str, str] | None = None,
    tx_count: int = 1,
) -> nx.DiGraph:
    """Build a trace graph in exactly the shape build_trace_graph produces.

    `edges` are (source, target, value_native) triples. Node depth is the
    shortest hop distance from `seed`, matching the real builder, and node
    totals are annotated by the production function rather than a copy of it --
    so a change to how totals are computed shows up here.
    """
    graph = nx.DiGraph()
    exchanges = exchanges or {}

    for src, dst, value in edges:
        for node in (src, dst):
            if node not in graph:
                graph.add_node(node, address=node, is_seed=False, expanded=False)
        graph.add_edge(
            src,
            dst,
            value_native=float(value),
            tx_count=tx_count,
            first_seen=1_700_000_000,
            last_seen=1_700_000_000,
            transactions=[
                {
                    "hash": f"0x{abs(hash((src, dst))):064x}"[:66],
                    "value_native": float(value),
                    "timestamp": 1_700_000_000,
                    "block_number": 18_000_000,
                }
            ],
        )

    if seed is not None and seed in graph:
        graph.nodes[seed]["is_seed"] = True
        depths = nx.single_source_shortest_path_length(graph, seed)
        for node in graph.nodes:
            graph.nodes[node]["depth"] = depths.get(node, 0)
    else:
        for node in graph.nodes:
            graph.nodes[node].setdefault("depth", 0)

    for address, name in exchanges.items():
        if address in graph:
            graph.nodes[address].update(
                is_exchange=True, is_terminal=True, exchange=name, label=name
            )

    _annotate_node_totals(graph)
    return graph


@pytest.fixture
def peel_chain_graph() -> nx.DiGraph:
    """seed -> A -> B -> exit, amounts declining gently at every hop.

    Two single-use intermediates is the shortest run the rule accepts, and
    each hop forwards ~90% -- a peel, not a split.
    """
    seed = addr("5eed")
    return make_graph(
        [
            (seed, addr("a1"), 10.0),
            (addr("a1"), addr("b2"), 9.0),
            (addr("b2"), addr("e11"), 8.0),
        ],
        seed=seed,
    )


@pytest.fixture
def amount_split_graph() -> nx.DiGraph:
    """A wallet that receives 10 and fans 9 out across three recipients."""
    seed = addr("5eed")
    splitter = addr("5911")
    return make_graph(
        [
            (seed, splitter, 10.0),
            (splitter, addr("c1"), 3.0),
            (splitter, addr("c2"), 3.0),
            (splitter, addr("c3"), 3.0),
        ],
        seed=seed,
    )


@pytest.fixture(autouse=True)
def _reset_api_budget():
    """Keep the shared pacer and response cache from leaking between tests.

    Both are process-wide by design -- the provider enforces its rate limit per
    credential, not per client -- which means without this a cached response or
    a widened interval from one test would silently change the next one's
    result. Test order must never affect an outcome.
    """
    from app import api_budget

    api_budget.reset()
    yield
    api_budget.reset()
