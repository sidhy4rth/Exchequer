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


def test_a_known_exchange_under_the_share_is_still_reached_and_not_reported_untraced():
    # #382: 0.2 of 44.2 straight to the exchange is under 1%, but the walk never
    # expands an exchange, so keeping it costs no read; leaving it out hid it.
    history, mules = split(12)
    history[SEED].append(tx(2000, SEED, EXCH, 0.2, 1))
    result = walk(history, branch_min_share=0.01)
    assert result.graph.has_edge(SEED, EXCH)
    assert EXCH in result.terminal_addresses
    assert result.untraced == []


def test_an_ordinary_address_under_the_share_is_still_left_untraced_beside_a_kept_exchange():
    # Silent on ordinary activity: only an address is_terminal names is kept.
    history, mules = split(12, smallest=0.2)
    history[SEED].append(tx(2000, SEED, EXCH, 0.1, 1))
    result = walk(history, branch_min_share=0.01)
    assert result.graph.has_edge(SEED, EXCH)
    assert not result.graph.has_node(mules[-1])
    ((left,),) = [result.untraced]
    assert left["counterparties"] == 1 and left["value_native"] == 0.2 and left["rule"] == "min_share"


def test_the_hard_cap_bounds_kept_known_addresses_too():
    many = [addr(f"e{i:03x}") for i in range(60)]
    history = {SEED: [tx(1, SEED, addr("b16"), 1000.0, 1)] + [tx(10 + i, SEED, e, 0.01, 1) for i, e in enumerate(many)]}
    result = build_trace_graph(SEED, Client(history), cfg=TraceConfig(max_depth=2, branch_min_share=0.01,
                                                                      max_branches_hard=50),
                               is_terminal=lambda a: a in many, direction=OUTGOING)
    assert sum(1 for e in many if result.graph.has_node(e)) == 50
    assert result.untraced[0]["counterparties"] == 10


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


def test_with_the_flag_on_a_small_direct_payment_to_an_exchange_still_names_it(monkeypatch):
    # #382, through the pipeline with the flag on: 5 of the 10,005 sent goes
    # straight to the exchange. It is the case's exchange (the share rule only
    # stops the walk from expanding small branches), not "no exchange found".
    history = {SEED: [tx(1, SEED, addr("ee11"), 10000.0, 1), tx(2, SEED, EXCH, 5.0, 2)]}

    @contextmanager
    def open_source(_chain, _asset):
        yield Client(history)

    labels = {EXCH: {"exchange": "Binance", "label": "Binance 14", "type": "hot_wallet"}}
    monkeypatch.setattr(pipeline, "open_source", open_source)
    monkeypatch.setattr(pipeline, "get_matcher", lambda key: ExchangeMatcher(labels, chain="ethereum"))
    monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
    monkeypatch.setattr(config, "TAINT_EXPANSION", True)
    result = pipeline.run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=3))
    assert result["exchange"] == "Binance" and result["exchange_address"] == EXCH
    assert not any(u["address"] == SEED for u in result["untraced"])
