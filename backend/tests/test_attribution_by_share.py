"""The case's exchange is where the money went, not merely the closest match.

The primary match used to be the one with the fewest hops, however little of
the traced value reached it. A scammer could send 0.002 ETH to any exchange
wallet -- or to an innocent customer's deposit address -- and that became the
case's exchange, its 'High' confidence and the addressee of the KYC/freeze
letter, while the 99 ETH cash-out went unmentioned.

Now every match carries its share of what the reported wallet sent (reach
along the strongest shortest path / the wallet's outflow, or the victim's
reported payments). The largest share wins, hops only break near-ties, and the
confidence band is capped when the attributed share is small.
"""
from __future__ import annotations

from contextlib import contextmanager

import networkx as nx
import pytest

from app import pipeline
from app.etherscan_client import Transaction
from app.exchange_matcher import ExchangeMatch, ExchangeMatcher
from app.graph_builder import INCOMING, OUTGOING
from app.pipeline import TraceRequest, run_trace
from app.scoring import reach_bottlenecks, score_case, seed_outflow
from conftest import addr

SEED = addr("5eed")
W1, W2 = addr("a1"), addr("a2")
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"  # data/exchange_labels.json
KRAKEN_1 = "0x2910543af39aba0cd09dbb2d50200b3e800a63d2"   # data/exchange_labels.json
D = addr("d0d0")  # an innocent customer's Binance deposit address
T = 1_700_000_000


def graph(edges, seed=SEED):
    g = nx.DiGraph()
    for src, dst, value in edges:
        g.add_edge(src, dst, value_native=value)
    g.nodes[seed]["depth"] = 0
    return g


def match(address, exchange, depth, value=1.0, **extra):
    return ExchangeMatch(address=address, exchange=exchange, label=exchange, wallet_type="hot_wallet",
                         depth=depth, value_received_native=value, **extra)


# --- the numbers ---------------------------------------------------------------

def test_reach_is_the_strongest_shortest_path_bottleneck():
    a, b, c = addr("a"), addr("b"), addr("c")
    g = graph([(SEED, a, 10.0), (a, b, 3.0), (SEED, c, 5.0), (c, b, 8.0)])
    reach = reach_bottlenecks(g, SEED, OUTGOING)
    assert reach[a] == 10.0 and reach[c] == 5.0
    assert reach[b] == 5.0  # via c: min(5, 8) beats via a: min(10, 3)


def test_reach_follows_the_money_upstream_on_a_reverse_trace():
    hot, x = addr("b0"), addr("c0")
    g = graph([(hot, x, 9.0), (x, SEED, 7.0)])
    assert reach_bottlenecks(g, SEED, INCOMING)[hot] == 7.0


def test_seed_outflow_nets_out_value_that_came_back():
    y = addr("e")
    g = graph([(SEED, y, 10.0), (SEED, W1, 5.0), (y, SEED, 4.0)])
    assert seed_outflow(g, SEED, OUTGOING) == pytest.approx(11.0)
    # Never below the largest single transfer out.
    g2 = graph([(SEED, y, 10.0), (y, SEED, 10.0)])
    assert seed_outflow(g2, SEED, OUTGOING) == pytest.approx(10.0)


# --- choosing the match --------------------------------------------------------

def test_the_larger_share_wins_over_the_closer_match():
    kraken, binance = match(KRAKEN_1, "Kraken", 1), match(BINANCE_14, "Binance", 2)
    shares = {KRAKEN_1: 0.33, BINANCE_14: 0.60}
    assert ExchangeMatcher.primary_match([kraken, binance], shares).exchange == "Binance"


def test_a_dust_match_never_outranks_a_material_one():
    dust, real = match(KRAKEN_1, "Kraken", 1), match(BINANCE_14, "Binance", 3)
    assert ExchangeMatcher.primary_match([dust, real], {KRAKEN_1: 0.0002, BINANCE_14: 0.99}) is real


def test_the_closer_match_wins_when_shares_are_about_equal():
    near, far = match(KRAKEN_1, "Kraken", 1), match(BINANCE_14, "Binance", 2)
    assert ExchangeMatcher.primary_match([far, near], {KRAKEN_1: 0.501, BINANCE_14: 0.499}) is near


def test_without_shares_the_old_rule_still_applies():
    near, far = match(KRAKEN_1, "Kraken", 1), match(BINANCE_14, "Binance", 2)
    assert ExchangeMatcher.primary_match([far, near]) is near


# --- the score -----------------------------------------------------------------

@pytest.mark.parametrize("share, allowed", [(0.05, {"low", "very low"}), (0.30, {"moderate", "low", "very low"})])
def test_a_small_attributed_share_caps_the_band(share, allowed):
    g = graph([(SEED, KRAKEN_1, 1.0)])
    m = match(KRAKEN_1, "Kraken", 1, value=1.0)
    capped = score_case(g, SEED, m, materiality={"primary_share": share, "threshold": 0.10, "majority": 0.50,
                                                 "denominator": 20.0, "primary_reach": 20.0 * share})
    assert capped.band in allowed
    assert any("%" in c and "reached" in c for c in capped.caveats)
    assert score_case(g, SEED, m).band == "high"  # the control: uncapped it is high


# --- end to end, with a fake provider ---------------------------------------------

_COUNTER = iter(range(1, 10**6))


def _tx(src, dst, value, when):
    return Transaction(hash="0x" + f"{next(_COUNTER):064x}", from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 1e18), timestamp=when, block_number=when // 12,
                       is_error=False, asset="ETH")


BASE = [_tx(SEED, W1, 99.0, T + 10), _tx(W1, W2, 99.0, T + 20), _tx(W2, BINANCE_14, 99.0, T + 30)]


@pytest.fixture
def trace(monkeypatch):
    def run(history):
        class Fake:
            def get_outgoing_transactions(self, address, limit=None):
                return [t for t in history if t.from_address == address]

        @contextmanager
        def open_source(chain, asset):
            yield Fake()
        monkeypatch.setattr(pipeline, "open_source", open_source)
        monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
        return run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=4,
                                      follow_swaps=False))
    return run


def test_a_dust_transfer_to_another_exchange_does_not_take_the_case(trace):
    r = trace(BASE + [_tx(SEED, KRAKEN_1, 0.002, T + 5)])
    assert r["exchange"] == "Binance" and r["exchange_address"] == BINANCE_14
    kraken = next(m for m in r["matches"] if m["address"] == KRAKEN_1)
    assert kraken["material"] is False
    assert r["materiality"]["primary_share"] > 0.98


def test_dust_to_an_innocent_deposit_address_is_not_the_attribution(trace):
    r = trace(BASE + [_tx(SEED, D, 0.002, T + 5), _tx(D, BINANCE_14, 0.5, T + 100), _tx(D, BINANCE_14, 0.7, T + 200)])
    assert r["exchange_address"] != D
    assert r["exchange"] == "Binance"


def test_the_plain_case_is_unchanged(trace):
    r = trace(BASE)
    assert r["exchange_address"] == BINANCE_14
    assert r["materiality"]["basis"] == "seed_outflow" and r["materiality"]["multiple_exchanges"] is False


def test_the_principal_path_is_found_fast_on_a_lattice_built_to_explode():
    # 2^40 equally short routes: listing them all (the old principal_path)
    # never finishes; the widest-route search reads each edge once.
    import time

    from app.scoring import principal_path
    g = nx.DiGraph()
    layers = [[SEED]] + [[addr(f"{i:02x}{j}") for j in "ab"] for i in range(40)] + [[BINANCE_14]]
    for here, there in zip(layers, layers[1:], strict=False):
        for a in here:
            for b in there:
                g.add_edge(a, b, value_native=1.0)
    start = time.monotonic()
    path = principal_path(g, SEED, BINANCE_14)
    assert time.monotonic() - start < 1.0
    assert path[0] == SEED and path[-1] == BINANCE_14 and len(path) == 42


# --- the hop count is the route's ----------------------------------------------

def test_a_dust_send_straight_to_the_exchange_does_not_shorten_the_route(trace):
    # 8 Nov check (r1-trace-engine-11): the route is the widest one (3 hops,
    # 99 ETH), but the hop count, its proximity score and the "directly, with no
    # intermediary" wording came from the shortest one, a 0.002 ETH send. One
    # dust transfer raised the score from 0.8 to 1.0 and the report contradicted
    # its own route.
    import json

    from app.models import Case
    from app.report import build_report, render_text_report

    plain = trace(BASE)
    r = trace(BASE + [_tx(SEED, BINANCE_14, 0.002, T + 5)])
    assert r["exchange_address"] == BINANCE_14
    assert len(r["trace_path"]) - 1 == 3
    assert r["hop_count"] == 3 == plain["hop_count"]
    assert r["confidence"] == plain["confidence"]
    hop = next(c for c in r["confidence_detail"]["components"] if c["name"] == "hop_proximity")
    assert "directly" not in hop["explanation"] and "3 hops" in hop["explanation"]
    assert "3 hops from the source" in r["confidence_detail"]["summary"]
    binance = next(m for m in r["matches"] if m["address"] == BINANCE_14)
    assert binance["depth"] == 3
    text = render_text_report(build_report(Case(id="c1", address=SEED, created_at="2026-11-08T00:00:00+00:00",
                                                result_json=json.dumps(r))))
    assert "Hops from source : 3" in text
    assert "no intermediary" not in text


def test_a_dust_route_to_one_exchange_does_not_win_the_tie_on_hops(trace):
    # Both exchanges received all 99 ETH (each a full share); Kraken's widest
    # route is 2 hops, Binance's 3, so Kraken leads -- even though a 0.002 ETH
    # send reached Binance in one hop.
    r = trace([_tx(SEED, W1, 99.0, T + 10), _tx(W1, W2, 99.0, T + 20), _tx(W2, BINANCE_14, 99.0, T + 30),
               _tx(SEED, addr("a3"), 99.0, T + 11), _tx(addr("a3"), KRAKEN_1, 99.0, T + 21),
               _tx(SEED, BINANCE_14, 0.002, T + 5)])
    assert r["exchange_address"] == KRAKEN_1
    assert r["hop_count"] == 2 == len(r["trace_path"]) - 1


# --- 8 Nov check (r1-trace-engine-0): recycling, intake ties, other exchanges ----

KD = addr("cd0d")  # the attacker's own Kraken deposit address


def _recycling_loop(rounds=150):
    """S pays 1 ETH into its own Kraken deposit KD, KD sweeps it to Kraken,
    Kraken pays it back out to S: the same 1 ETH, `rounds` times over."""
    out, back = [], []
    for i in range(rounds):
        out += [_tx(SEED, KD, 1.0, T - 10000 + i * 10), _tx(KD, KRAKEN_1, 1.0, T - 9995 + i * 10)]
        back.append(_tx(KRAKEN_1, SEED, 1.0, T - 9992 + i * 10))
    return out, back


@pytest.fixture
def trace_with_flows(monkeypatch):
    """A provider that can also list what a wallet received in a window."""
    def run(history, inflows=()):
        everything = list(history) + list(inflows)

        class Fake:
            def get_outgoing_transactions(self, address, limit=None):
                return [t for t in history if t.from_address == address]

            def get_flows_between(self, address, start_block, end_block, start_ts, end_ts):
                inside = [t for t in everything if start_block <= t.block_number <= end_block]
                return ([t for t in inside if t.to_address == address],
                        [t for t in inside if t.from_address == address], True)

        @contextmanager
        def open_source(chain, asset):
            yield Fake()
        monkeypatch.setattr(pipeline, "open_source", open_source)
        monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
        return run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=4,
                                      follow_swaps=False))
    return run


def test_value_recycled_through_an_exchange_counts_once(trace_with_flows):
    # 150 x 1 ETH into the attacker's own Kraken deposit, each paid back out by
    # Kraken: 150 ETH on the aggregated edge, 1 ETH of real value. It used to
    # take the case (share 0.60, High) from the 99 ETH that went to Binance.
    loop, back = _recycling_loop()
    r = trace_with_flows(BASE + loop, inflows=back)
    assert r["exchange"] == "Binance" and r["exchange_address"] == BINANCE_14
    assert r["materiality"]["primary_share"] > 0.9
    kraken = [m for m in r["matches"] if m["exchange"] == "Kraken"]
    assert kraken and all(m["share"] < 0.1 and not m["material"] for m in kraken)
    recycled = r["materiality"]["recycled"]
    assert recycled["by_exchange"]["Kraken"] == pytest.approx(150.0)
    assert any("Kraken" in w and "back" in w for w in r["warnings"])


def test_recycling_that_cannot_be_seen_is_at_least_named_in_the_letter_and_report(trace):
    # The same loop with no way to read the reported wallet's inflows: the
    # withdrawals are invisible and the edge reads 150 ETH. The case may still
    # name Kraken, but the letter and the report must say that a material
    # share also reached Binance.
    import json

    from app import request_letters
    from app.models import Case
    from app.report import build_report, render_text_report

    loop, _ = _recycling_loop()
    r = trace(BASE + loop)
    assert r["materiality"]["multiple_exchanges"] is True
    other = "Binance" if r["exchange"] == "Kraken" else "Kraken"
    letter = request_letters.draft("c1", r, "exchange")
    flat = " ".join(letter.split())
    assert "also reached" in flat and other in flat
    report = build_report(Case(id="c1", address=SEED, created_at="2026-11-08T00:00:00+00:00",
                               result_json=json.dumps(r)))
    assert any(x["exchange"] == other for x in report["attribution"]["also_reached"])
    text = render_text_report(report)
    assert "Also reached" in text and other in text


def test_a_hop_wallets_float_to_another_exchange_is_named_in_the_letter(trace):
    # W1 also sends 100 ETH of its own to Kraken: both exchanges carry the
    # whole 99 ETH share. The closer one leads; the letter names the other.
    from app import request_letters

    r = trace(BASE + [_tx(W1, KRAKEN_1, 100.0, T + 25)])
    assert r["materiality"]["multiple_exchanges"] is True
    flat = " ".join(request_letters.draft("c1", r, "exchange").split())
    other = {"Kraken": "Binance", "Binance": "Kraken"}[r["exchange"]]
    assert "also reached" in flat and other in flat


def test_a_single_exchange_letter_has_no_also_reached_paragraph(trace):
    from app import request_letters

    r = trace(BASE)
    assert "also reached" not in " ".join(request_letters.draft("c1", r, "exchange").split())


def test_on_a_payment_trace_branches_over_the_reported_amount_tie_and_the_larger_wins():
    # Intake: every branch carrying at least the reported 1,000 saturates at a
    # 1.0 share. The closest used to win, naming a 1,000 deposit address over
    # the 50,000 that went to Binance; the tie is now broken by share of
    # everything the wallet sent.
    from app.pipeline import _materiality

    g = graph([(SEED, W1, 50000.0), (W1, W2, 50000.0), (W2, BINANCE_14, 50000.0),
               (SEED, D, 1000.0), (D, BINANCE_14, 400.0)])
    ms = [match(BINANCE_14, "Binance", 3, value=50400.0),
          ExchangeMatch(address=D, exchange="Binance", label="probable Binance deposit address (inferred)",
                        wallet_type="inferred_deposit", depth=1, value_received_native=1000.0, evidence={})]
    for intake in (None, {"payments": [{"amount": 1000.0, "timestamp": 1}]}):
        _, shares = _materiality(g, SEED, OUTGOING, ms, [], intake)
        assert ExchangeMatcher.primary_match(ms, shares).address == BINANCE_14, intake
