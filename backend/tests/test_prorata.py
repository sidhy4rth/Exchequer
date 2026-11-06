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
    """A provider row. Hash, ends and block are optional, as the oldest fixtures had none."""

    def __init__(self, value, hash=None, from_address=None, to_address=None, block=None):
        self.value_native = value
        self.hash = hash
        self.from_address = from_address
        self.to_address = to_address
        self.block_number = block
        self.timestamp = block


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


# ---------------------------------------------------------------------------
# Not estimated: no amount credit (audit r2-g2-documented-claims-vs-code-7-2)
# ---------------------------------------------------------------------------
def _scored(complete):
    from app.exchange_matcher import ExchangeMatch
    # V -> M 40, M -> X 100; M received 1,000 in the window.
    g = path_graph(sent=40.0, onward=100.0)
    g.nodes["V"]["depth"], g.nodes["M"]["depth"], g.nodes["X"]["depth"] = 0, 1, 2
    match = ExchangeMatch(address="X", exchange="Binance", label="Binance: Hot Wallet 6",
                          wallet_type="hot_wallet", depth=2, value_received_native=100.0)
    prorata = estimate(g, ["V", "M", "X"], lambda *a: ([Tx(40.0), Tx(960.0)], complete))
    return score_case(g, "V", match, native_symbol="USDT", prorata=prorata), prorata


def test_an_incomplete_read_never_scores_above_a_complete_one():
    from app.scoring import _BAND_ORDER
    full, _ = _scored(True)
    part, prorata = _scored(False)
    assert prorata["status"] == "unknown"
    assert part.score <= full.score
    assert _BAND_ORDER.index(part.band) <= _BAND_ORDER.index(full.band)


def test_not_estimated_gets_no_amount_credit_and_says_so():
    part, _ = _scored(False)
    amount = next(c for c in part.components if c.name == "amount_correlation")
    assert amount.raw_value == 0.0
    assert amount.explanation.startswith("Not estimated:")
    assert "no credit is given" in amount.explanation
    assert "survived the route" not in amount.explanation
    assert part.band != "high"


def test_the_unknown_caveat_says_traced_funds_not_reported_funds():
    part, _ = _scored(False)
    caveat = next(c for c in part.caveats if "could not be estimated" in c)
    assert "the traced funds" in caveat and "the reported funds" not in caveat
    assert "No amount credit was given" in caveat
    assert "first and last hop" not in caveat


def test_a_hop_diluted_before_an_unknown_one_is_still_called_out():
    # V -> M1 -> M2 -> X: M1 is read (victim 4% of it), M2's read is cut short.
    g = nx.DiGraph()
    edge(g, "V", "M1", 40.0, 100)
    edge(g, "M1", "M2", 1000.0, 200)
    edge(g, "M2", "X", 1000.0, 300)

    def reads(address, *window):
        return ([Tx(40.0), Tx(960.0)], True) if address == "M1" else ([Tx(1000.0)], False)

    result = estimate(g, ["V", "M1", "M2", "X"], reads)
    assert result["status"] == "unknown"
    assert result["diluted"] is True and result["lowest_share"] == 0.04
    from app.scoring import _prorata_caveats
    assert any("only 4.0%" in c and "M1" in c for c in _prorata_caveats(result, "USDT"))



# ---------------------------------------------------------------------------
# What counts as other people's money (audit r1-attribution-integrity-5, -6)
# ---------------------------------------------------------------------------
def _hop_wallet(onward=10_000.0):
    """V -> W 10,000 at block 100; W -> X `onward` at block 200."""
    g = nx.DiGraph()
    edge(g, "V", "W", 10_000.0, 100)
    edge(g, "W", "X", onward, 200)
    return g


VICTIM_ROW = Tx(10_000.0, hash="VW", from_address="V", to_address="W", block=100)
ONWARD_ROW = Tx(10_000.0, hash="WX", from_address="W", to_address="X", block=200)


def test_a_self_send_does_not_dilute():
    # Nine sends of the same 10,000 from W to W, for gas only.
    selfs = [Tx(10_000.0, hash=f"s{i}", from_address="W", to_address="W", block=110 + i) for i in range(9)]
    result = estimate(_hop_wallet(), ["V", "W", "X"], lambda *a: ([VICTIM_ROW, *selfs], True))
    hop = result["hops"][0]
    assert result["estimated"] == 10_000.0 and not result["diluted"]
    assert hop["self_transfers"] == 90_000.0 and hop["received_in_window"] == 10_000.0


def test_a_round_trip_through_a_helper_is_netted():
    # W -> X2 -> W nine times: no third party's money ever joined.
    out = [Tx(10_000.0, hash=f"o{i}", from_address="W", to_address="H", block=110 + 2 * i) for i in range(9)]
    back = [Tx(10_000.0, hash=f"b{i}", from_address="H", to_address="W", block=111 + 2 * i) for i in range(9)]
    flows = lambda *a: ([VICTIM_ROW, *back], [*out, ONWARD_ROW], True)  # noqa: E731
    result = estimate(_hop_wallet(), ["V", "W", "X"], None, flows_between=flows)
    hop = result["hops"][0]
    assert result["status"] == "estimated" and result["estimated"] == 10_000.0
    assert hop["recycled_in_window"] == 90_000.0 and hop["recycled_via"][0]["address"] == "H"
    assert not result["diluted"]


def test_a_refund_before_any_payment_is_not_netted():
    # H paid W first and W paid H back later: H's money did join W.
    came = Tx(10_000.0, hash="h1", from_address="H", to_address="W", block=110)
    went = Tx(10_000.0, hash="w1", from_address="W", to_address="H", block=120)
    flows = lambda *a: ([VICTIM_ROW, came], [went, ONWARD_ROW], True)  # noqa: E731
    result = estimate(_hop_wallet(), ["V", "W", "X"], None, flows_between=flows)
    assert result["hops"][0]["recycled_in_window"] == 0.0
    assert result["estimated"] == 5_000.0


def test_the_denominator_is_the_union_of_the_route_and_the_read():
    # The route's own 10 arrived by internal transfer, which the provider's
    # list does not carry; a stranger's 10 is in it. Half was the victim's.
    g = nx.DiGraph()
    edge(g, "V", "W", 10.0, 100)
    edge(g, "W", "X", 10.0, 200)
    stranger = Tx(10.0, hash="st", from_address="S", to_address="W", block=150)
    result = estimate(g, ["V", "W", "X"], lambda *a: ([stranger], True))
    assert result["hops"][0]["victim_share"] == 0.5 and result["estimated"] == 5.0


def test_the_routes_own_transfer_is_not_counted_twice():
    g = nx.DiGraph()
    edge(g, "V", "W", 10.0, 100)
    edge(g, "W", "X", 10.0, 200)
    listed = Tx(10.0, hash="VW", from_address="V", to_address="W", block=100)
    result = estimate(g, ["V", "W", "X"], lambda *a: ([listed], True))
    assert result["hops"][0]["victim_share"] == 1.0 and result["estimated"] == 10.0


def test_a_row_without_a_hash_matches_the_route_by_value():
    # Never double-counted: a hashless row of the route's value is that transfer.
    g = nx.DiGraph()
    edge(g, "V", "W", 10.0, 100)
    edge(g, "W", "X", 10.0, 200)
    result = estimate(g, ["V", "W", "X"], lambda *a: ([Tx(10.0)], True))
    assert result["hops"][0]["victim_share"] == 1.0


def test_netted_value_is_said_in_the_caveats():
    from app.scoring import _prorata_caveats
    selfs = [Tx(10_000.0, hash=f"s{i}", from_address="W", to_address="W", block=110 + i) for i in range(9)]
    result = estimate(_hop_wallet(), ["V", "W", "X"], lambda *a: ([VICTIM_ROW, *selfs], True))
    text = " ".join(_prorata_caveats(result, "USDT"))
    assert "W sent 90,000.0000 USDT to itself" in text and "netted out" in text
    assert "upper bound" not in text


# ---------------------------------------------------------------------------
# A cap on the starting figure (audit r1-attribution-integrity-7, r1-evidence-crypto-5)
# ---------------------------------------------------------------------------
def test_the_estimate_never_exceeds_the_seed_cap():
    # The reported wallet sent 50,000 on, of which the victim paid 1,000.
    g = path_graph(sent=50_000.0, onward=50_000.0)
    result = estimate(g, ["V", "M", "X"], lambda *a: ([Tx(50_000.0)], True),
                      seed_cap=1_000.0, cap_basis="reported_amount")
    assert result["estimated"] == 1_000.0 and result["sent"] == 50_000.0
    assert result["seed_cap"] == {"amount": 1_000.0, "basis": "reported_amount", "applied": True}
    assert result["ratio"] == 1.0  # all of the capped amount arrived
    direct = nx.DiGraph()
    edge(direct, "V", "X", 5_000.0, 100)
    assert estimate(direct, ["V", "X"], None, seed_cap=100.0, cap_basis="swap_output")["estimated"] == 100.0


def test_a_cap_above_what_was_sent_changes_nothing():
    g = path_graph(sent=40.0, onward=40.0)
    result = estimate(g, ["V", "M", "X"], lambda *a: ([Tx(40.0)], True), seed_cap=100.0, cap_basis="swap_output")
    assert result["estimated"] == 40.0 and result["seed_cap"]["applied"] is False
