"""Shared fixtures for the Exchequer test suite.

The rules under test (pattern detection, scoring) are pure functions over a
networkx graph, so nothing here touches the network, an API key, or the
database. A test that needed a live chain could not tell a broken rule from a
rate limit, which is the opposite of what these tests are for.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import networkx as nx
import pytest

# backend/tests/conftest.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import config  # noqa: E402
from app.graph_builder import _annotate_node_totals  # noqa: E402

# The suite never touches the network, so it never needs a cached response to
# survive a restart -- and it must not leave a provider_cache.db beside the
# real case store or read one a previous run left. Set at import, before any
# module-scoped TestClient starts the app.
config.API_CACHE_PATH = None
# Nor may it screen against a label store built on this machine: the suite
# must give the same answers here as on CI, where no store exists.
config.LABEL_STORE_PATH = None
# Nor carry one test's provider spend into the next through the case store:
# tests/test_provider_allowance.py turns the stored meter on where it is tested.
config.PERSIST_METERS = False

# Reports are signed; the suite signs with a key of its own rather than
# creating report_signing_key.pem beside the real case store.
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from app import signing  # noqa: E402

signing.reset_for_tests(signing.Signer(Ed25519PrivateKey.generate(), "file"))

# The old demo 3 (0x536c4921...) as recorded on 14 Oct 2026, kept as a fixture
# when demo 3 moved to another wallet (#284): it is the only recorded trace with
# a swap and a USDT follow-on, which the letter, verify_case, contract and read
# tests are pinned to. The contract fixtures are built from it too.
from scripts.build_contract_fixtures import SWAP_RECORDING as SWAP_RECORDING_PATH  # noqa: E402


def swap_recording() -> dict:
    """That recording's row ({demo, recorded_at, result}), a fresh copy each call."""
    import json
    return json.loads(SWAP_RECORDING_PATH.read_text(encoding="utf-8"))[0]


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
    """A wallet that receives 10 and fans 9.6 out evenly across four recipients."""
    seed = addr("5eed")
    splitter = addr("5911")
    return make_graph(
        [
            (seed, splitter, 10.0),
            (splitter, addr("c1"), 2.4),
            (splitter, addr("c2"), 2.4),
            (splitter, addr("c3"), 2.4),
            (splitter, addr("c4"), 2.4),
        ],
        seed=seed,
    )


@pytest.fixture(autouse=True)
def _reset_api_budget(monkeypatch):
    """Keep the shared pacer and response cache from leaking between tests.

    Both are process-wide by design -- the provider enforces its rate limit per
    credential, not per client -- which means without this a cached response or
    a widened interval from one test would silently change the next one's
    result. Test order must never affect an outcome. The cache is also kept
    in memory here: a test must not leave a provider_cache.db beside the real
    case store, and must not read one a previous run left.
    """
    from app import api_budget

    monkeypatch.setattr(config, "API_CACHE_PATH", None)
    api_budget.reset()
    yield
    api_budget.reset()


@pytest.fixture(autouse=True)
def _fresh_trace_rate_limit():
    """The per-client trace limit is process-wide; the suite's TestClient is
    one client, so without this the 31st trace in a run would be refused.
    The site-wide ceilings are process-wide too."""
    from app import rate_limit
    from app.routes import case_bundle, casebook, cases
    for limiter in (rate_limit.traces, rate_limit.traces_total, rate_limit.watches_total, casebook.case_lists,
                    casebook.correlations, rate_limit.rechecks, rate_limit.rechecks_total,
                    case_bundle.bundles, case_bundle.bundles_total):
        limiter.reset()
    for limiter in (*rate_limit.officer_hour.values(), *rate_limit.officer_day.values()):
        limiter.reset()
    # Likewise the minutes each connection held trace slots, and the kept demo list.
    cases._slot_clock.reset()
    casebook.clear_public_lists()
    yield


@pytest.fixture(autouse=True)
def _fresh_report_cache():
    """Rendered reports and the PDF render limits are process-wide (report_cache.py);
    a report kept from one test must not answer the next."""
    from app import report_cache
    report_cache.reset()
    yield
    report_cache.reset()


# Threads a request starts and leaves running after its response: a batch and
# its heartbeat (app/batches.py), a background trace (app/routes/jobs.py).
BACKGROUND_RUNNERS = ("batch-", "heartbeat-", "trace-job-")
RUNNER_STOP_SECONDS = 10.0


@pytest.fixture(autouse=True)
def _wait_for_background_runners(monkeypatch):
    """Wait, at teardown, for every batch or trace thread the test started.

    They read models._engine when they run, not when they start. One still
    going when the next test swaps in its own throwaway store writes into
    that store while it is being migrated. Taking monkeypatch makes this
    teardown run before the test's patches are undone, so the threads end
    against the test's own engine and stubs. A thread that does not stop in
    time fails the test rather than being left behind.
    """
    before = set(threading.enumerate())
    yield

    def running():
        return [t for t in threading.enumerate()
                if t not in before and t.name.startswith(BACKGROUND_RUNNERS) and t.is_alive()]

    deadline = time.monotonic() + RUNNER_STOP_SECONDS
    # A batch thread starts its heartbeat thread itself: look again after each join.
    while (left := running()) and time.monotonic() < deadline:
        for thread in left:
            thread.join(max(0.0, deadline - time.monotonic()))
    if left := running():
        pytest.fail(f"background threads still running {RUNNER_STOP_SECONDS:.0f} s after the test: "
                    f"{sorted(t.name for t in left)}")


def pytest_collection_modifyitems(config, items):
    """On CI, keep only this shard's files (tests/shards.py, test.yml)."""
    import shards

    files = {item.path for item in items}
    kept = shards.keep(files)
    if kept is None:
        return
    deselected = [item for item in items if item.path not in kept]
    items[:] = [item for item in items if item.path in kept]
    config.hook.pytest_deselected(items=deselected)
