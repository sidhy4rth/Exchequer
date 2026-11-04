"""R5: a split into eleven or more parts no longer hides the money.

The walk used to follow only the ten largest destinations of each address. A
launderer who splits 40 ETH into twelve parts hides the two smallest; if one
of them is the path to the exchange, the trace never finds it. With the flag
on, every destination carrying at least a set share of what the address sent
is followed, and whatever is not followed is reported with its value.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from app import config, pipeline
from app.etherscan_client import Transaction
from app.exchange_matcher import ExchangeMatcher
from app.graph_builder import OUTGOING, TraceConfig, build_trace_graph
from app.pipeline import TraceRequest

from conftest import addr

SEED, EXCH = addr("5eed"), addr("e8c4")
T0, B0 = 1_700_000_000, 18_000_000


def tx(n, src, dst, value, step=0):
    return Transaction(hash=f"0x{n:064x}", from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 1e18), timestamp=T0 + step, block_number=B0 + step,
                       is_error=False, asset="ETH")


def split(parts, smallest=None):
    """SEED splits its money into `parts` mules; the last, smallest mule pays the exchange."""
    mules = [addr(f"a{i:02x}") for i in range(parts)]
    sizes = [4.0] * (parts - 1) + [smallest or 2.0]
    history = {SEED: [tx(i, SEED, m, v, 1) for i, (m, v) in enumerate(zip(mules, sizes, strict=True))]}
    history[mules[-1]] = [tx(1000, mules[-1], EXCH, sizes[-1] - 0.01, 2)]
    return history, mules


class Client:
    def __init__(self, history):
        self.history = history

    def get_outgoing_transactions(self, address, limit=None):
        return list(self.history.get(address, []))


def walk(history, **cfg):
    return build_trace_graph(SEED, Client(history), cfg=TraceConfig(max_depth=3, **cfg),
                             is_terminal=lambda a: a == EXCH, direction=OUTGOING)


def test_the_old_rule_hides_the_smallest_parts_and_now_says_how_much():
    history, mules = split(12)
    result = walk(history)  # top ten, as before
    assert not result.graph.has_node(EXCH)
    ((left,),) = [result.untraced]
    assert left["address"] == SEED and left["counterparties"] == 2 and left["rule"] == "top_n"
    assert left["value_native"] == 6.0  # one 4.0 mule and the 2.0 mule to the exchange
    assert result.truncated


def test_a_share_rule_follows_every_part_and_reaches_the_exchange():
    history, mules = split(12)
    result = walk(history, branch_min_share=0.01)
    assert result.graph.has_edge(mules[-1], EXCH)
    assert all(result.graph.has_edge(SEED, m) for m in mules)
    assert result.untraced == []


def test_a_part_below_the_share_is_not_followed_but_is_reported():
    # 0.2 of 44.2 sent is under 1%: not followed, and its value is stated.
    history, mules = split(12, smallest=0.2)
    result = walk(history, branch_min_share=0.01)
    assert not result.graph.has_node(EXCH)
    ((left,),) = [result.untraced]
    assert left["counterparties"] == 1 and left["value_native"] == 0.2 and left["rule"] == "min_share"
    assert left["share_of_outflow"] == round(0.2 / 44.2, 4)


def test_dust_is_still_dropped_before_any_rule():
    history, _ = split(3, smallest=0.0005)  # below min_value_native
    result = walk(history, branch_min_share=0.0)
    assert result.untraced == []  # dust is spam, not untraced money


def test_the_hard_cap_still_bounds_one_wallet():
    history, mules = split(60)
    result = walk(history, branch_min_share=0.0, max_branches_hard=50)
    assert sum(1 for m in mules if result.graph.has_edge(SEED, m)) == 50
    assert any("safety cap of 50" in r for r in result.truncation_reasons)
    assert result.untraced[0]["counterparties"] == 10


# ---------------------------------------------------------------------------
# Through the pipeline: the flag decides the rule; the case reports the rest
# ---------------------------------------------------------------------------
@pytest.fixture
def traced(monkeypatch):
    history, _ = split(12)

    @contextmanager
    def open_source(_chain, _asset):
        yield Client(history)

    labels = {EXCH: {"exchange": "Binance", "label": "Binance 14", "type": "hot_wallet"}}
    monkeypatch.setattr(pipeline, "open_source", open_source)
    monkeypatch.setattr(pipeline, "get_matcher", lambda key: ExchangeMatcher(labels, chain="ethereum"))
    monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])

    def run(on):
        monkeypatch.setattr(config, "TAINT_EXPANSION", on)
        return pipeline.run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=3))
    return run


def test_with_the_flag_off_the_trace_is_as_before_and_reports_what_it_left(traced):
    result = traced(False)
    assert result["exchange"] is None
    assert result["untraced"][0]["value_native"] == 6.0


def test_with_the_flag_on_the_split_no_longer_hides_the_exchange(traced):
    result = traced(True)
    assert result["exchange"] == "Binance"
    assert result["untraced"] == []


def test_the_flag_is_off_by_default():
    assert config.FLAGS["EXCHEQUER_TAINT_EXPANSION"]["on"] is False
