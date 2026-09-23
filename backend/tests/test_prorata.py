"""Tests for pro-rata tracing through wallets that mix in other money.

The case that matters is the one found on a real BSC trace: 40 USDT of the
victim's joining a wallet that moves far more. Comparing the first and last hop
called that "100% survived"; pro-rata must say how little of it can be theirs,
and must still say "all of it" when nothing else joined.
"""
from __future__ import annotations

import networkx as nx

from app.prorata import estimate
from app.scoring import score_case


class Tx:
    def __init__(self, value):
        self.value_native = value


def edge(graph, a, b, value, block, ts=None):
    graph.add_edge(a, b, value_native=value, transactions=[
        {"hash": f"{a}{b}", "value_native": value, "block_number": block, "timestamp": ts or block}])


def path_graph(sent=40.0, onward=1001.5):
    g = nx.DiGraph()
    edge(g, "V", "M", sent, 100)
    edge(g, "M", "X", onward, 200)
    return g


def test_nothing_else_joined_means_all_of_it_arrived():
    g = path_graph(sent=40.0, onward=40.0)
    result = estimate(g, ["V", "M", "X"], lambda *a: ([Tx(40.0)], True))
    assert result["status"] == "estimated" and result["estimated"] == 40.0 and result["ratio"] == 1.0


def test_other_money_joining_dilutes_the_share_and_the_amount():
    # 40 of the victim's plus 961 from elsewhere; the wallet sends 1,001.50 on.
    g = path_graph(sent=40.0, onward=1001.5)
    result = estimate(g, ["V", "M", "X"], lambda *a: ([Tx(40.0), Tx(961.0)], True))
    hop = result["hops"][0]
    assert abs(hop["victim_share"] - 40 / 1001) < 1e-4
    # All of the victim's 40 went on (the wallet sent everything), and no more.
    assert result["estimated"] == 40.0 and result["arrived_total"] == 1001.5


def test_only_part_sent_on_carries_only_the_victims_share_of_it():
    # Victim 40 of 100 received; only 50 sent on toward the exchange -> 20.
    g = path_graph(sent=40.0, onward=50.0)
    result = estimate(g, ["V", "M", "X"], lambda *a: ([Tx(40.0), Tx(60.0)], True))
    assert result["estimated"] == 20.0 and result["ratio"] == 0.5 and not result["diluted"]


def test_a_small_share_is_flagged_as_diluted():
    g = path_graph(sent=40.0, onward=100.0)
    result = estimate(g, ["V", "M", "X"], lambda *a: ([Tx(40.0), Tx(960.0)], True))
    assert result["diluted"] and result["estimated"] == 4.0


def test_an_incomplete_read_is_unknown_never_a_guess():
    g = path_graph()
    result = estimate(g, ["V", "M", "X"], lambda *a: ([Tx(40.0)], False))
    assert result["status"] == "unknown" and "too many" in result["reason"]


def test_a_failed_read_is_unknown_and_never_fails_the_trace():
    def boom(*a):
        raise RuntimeError("rate limited")
    assert estimate(path_graph(), ["V", "M", "X"], boom)["status"] == "unknown"


def test_a_direct_deposit_needs_no_reads():
    g = nx.DiGraph()
    edge(g, "V", "X", 5.0, 100)
    assert estimate(g, ["V", "X"], None)["estimated"] == 5.0


def test_the_score_uses_the_estimate_and_says_so():
    from app.exchange_matcher import ExchangeMatch
    g = path_graph(sent=40.0, onward=100.0)
    g.nodes["V"]["depth"], g.nodes["M"]["depth"], g.nodes["X"]["depth"] = 0, 1, 2
    match = ExchangeMatch(address="X", exchange="Binance", label="Binance: Hot Wallet 6",
                          wallet_type="hot_wallet", depth=2, value_received_native=100.0)
    prorata = estimate(g, ["V", "M", "X"], lambda *a: ([Tx(40.0), Tx(960.0)], True))
    score = score_case(g, "V", match, max_depth=3, native_symbol="USDT", prorata=prorata)
    amount = next(c for c in score.components if c.name == "amount_correlation")
    assert amount.raw_value == 0.1 and "Pro-rata" in amount.explanation
    assert any("only 4.0%" in c for c in score.caveats)


def test_tron_transfers_without_block_numbers_are_windowed_by_time():
    g = nx.DiGraph()
    g.add_edge("V", "M", value_native=40.0, transactions=[{"value_native": 40.0, "timestamp": 100}])
    g.add_edge("M", "X", value_native=100.0, transactions=[{"value_native": 100.0, "timestamp": 200}])
    result = estimate(g, ["V", "M", "X"], lambda *a: ([Tx(40.0), Tx(60.0)], True))
    assert result["status"] == "estimated" and result["estimated"] == 40.0
