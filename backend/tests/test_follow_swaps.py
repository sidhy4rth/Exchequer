"""Tests for following a swap into a stablecoin as its own trace.

A follow-on trace answers where the money went after it changed asset, so two
things matter: it must start at the swap (anything the wallet sent in the new
asset beforehand was not the swapped money), and it must never blend its
amounts or score into the original asset's. The providers are faked, and swap
detection -- tested on real receipts elsewhere -- is given its answer, so this
tests the wiring and nothing else.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from app import pipeline as main
from app.etherscan_client import Transaction
from app.pipeline import TraceRequest, run_trace

from conftest import addr

SEED = addr("5eed")
ROUTER = addr("7007e7")
STRAY = addr("57a7")
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"
SWAP_AT = 1_700_000_000


def tx(src, dst, value, when, asset):
    return Transaction(hash=f"0x{abs(hash((src, dst, when))):064x}"[:66], from_address=src,
                       to_address=dst, value_native=value, value_wei=int(value * 1e18),
                       timestamp=when, block_number=when // 12, is_error=False, asset=asset)


class FakeClient:
    """One asset's outgoing history for every address, keyed by sender."""

    def __init__(self, history):
        self.history = history

    def get_outgoing_transactions(self, address, limit=None):
        return [t for t in self.history if t.from_address == address]


HISTORY = {
    "ETH": [tx(SEED, ROUTER, 1.0, SWAP_AT, "ETH")],
    "USDT": [
        tx(SEED, STRAY, 500.0, SWAP_AT - 100, "USDT"),         # before the swap: not the swapped money
        tx(SEED, BINANCE_14, 2400.0, SWAP_AT + 60, "USDT"),     # after it
    ],
}

SWAP = {
    "router": ROUTER, "router_address": ROUTER, "router_label": "Uniswap V3: Router 2", "sender": SEED, "tx": "0xabc",
    "timestamp": SWAP_AT, "asset_in": "ETH", "amount_in": 1.0, "asset_out": "USDT",
    "amount_out": 2400.0, "output_read": True,
}


@pytest.fixture
def faked(monkeypatch):
    @contextmanager
    def open_source(chain, asset):
        yield FakeClient(HISTORY[asset])

    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(main, "detect_swaps", lambda graph, *a, **k: [SWAP] if k.get("asset_symbol") == "ETH" else [])


def request(**kw):
    return TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=3, **kw)


def test_the_swapped_stablecoin_is_traced_to_the_exchange(faked):
    result = run_trace(request())

    (follow,) = result["follow_ons"]
    assert follow["asset"] == "USDT" and follow["address"] == SEED
    assert follow["result"]["exchange"] == "Binance"
    assert result["followed_attribution"]["exchange"] == "Binance"
    assert "followed the USDT" in result["message"]


def test_the_original_trace_keeps_its_own_asset_and_score(faked):
    result = run_trace(request())

    assert result["exchange"] is None and result["asset"] == "ETH"
    assert result["follow_ons"][0]["result"]["asset"] == "USDT"


def test_the_follow_on_starts_at_the_swap(faked):
    follow = run_trace(request())["follow_ons"][0]["result"]

    reached = {n["id"] for n in follow["graph"]["nodes"]}
    assert STRAY.lower() not in reached
    assert follow["transfers_excluded_by_time"] == 1


def test_following_can_be_switched_off(faked):
    result = run_trace(request(follow_swaps=False))
    assert result["follow_ons"] == [] and result["followed_attribution"] is None


def test_a_swap_into_an_asset_the_chain_does_not_trace_is_not_followed(faked, monkeypatch):
    other = {**SWAP, "asset_out": "token 0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0"}
    monkeypatch.setattr(main, "detect_swaps", lambda graph, *a, **k: [other] if k.get("asset_symbol") == "ETH" else [])
    assert run_trace(request())["follow_ons"] == []


def test_the_report_prints_the_follow_on(faked):
    from app.models import Case
    from app.report import build_report, render_text_report

    result = run_trace(request())
    import json
    case = Case(id="c1", address=SEED, created_at="2026-09-24T00:00:00+00:00",
                result_json=json.dumps(result, default=str))
    text = render_text_report(build_report(case))

    assert "FOLLOW-ON TRACES (THE MONEY AFTER A SWAP)" in text
    assert "reached             : Binance" in text
    assert "never added to the trace above" in " ".join(text.split())


def test_a_follow_on_that_finds_nothing_says_so_instead_of_asking_for_a_rerun(faked, monkeypatch):
    monkeypatch.setitem(HISTORY, "USDT", [tx(SEED, STRAY, 2400.0, SWAP_AT + 60, "USDT")])
    result = run_trace(request())

    assert result["followed_attribution"] is None
    assert "reached no known exchange either" in result["message"]
    assert "re-run" not in result["message"]


def test_a_time_budget_covers_the_follow_on_too(faked, monkeypatch):
    """'Stop after 1:30' means the case, not each trace in it: one clock
    (api_budget.TraceBudget) is shared by the trace and its follow-ons."""
    from app.api_budget import TraceBudget
    now = [0.0]
    budget = TraceBudget(90, 60, clock=lambda: now[0])
    real = main.build_trace_graph

    def slow(*a, **k):
        result = real(*a, **k)
        now[0] += 95.0  # the original trace used all of its 90 s
        return result

    monkeypatch.setattr(main, "build_trace_graph", slow)
    (follow,) = run_trace(request(time_budget_seconds=90), budget=budget)["follow_ons"]
    assert "time budget was spent" in follow["error"] and "result" not in follow


def test_a_follow_on_that_crashes_keeps_the_trace_that_found_it(faked, monkeypatch):
    """Only HTTP errors were caught: any other failure in the follow-on threw
    away the finished original trace."""
    real = main.run_trace

    def flaky(sub, seed_window=None, budget=None, **kw):
        if sub.asset == "USDT":
            raise RuntimeError("provider answered something odd")
        return real(sub, seed_window=seed_window, budget=budget, **kw)

    monkeypatch.setattr(main, "run_trace", flaky)
    result = real(request())
    (follow,) = result["follow_ons"]
    assert "result" not in follow and "could not be traced" in follow["error"]
    assert "provider answered" not in follow["error"]  # a fixed sentence, never raw text
    assert result["asset"] == "ETH"


MID = addr("a1d")


def test_a_follow_on_counts_hops_from_the_reported_address(faked, monkeypatch):
    """The swap sat one hop out; the USDT went straight to Binance. Two hops
    from the reported address, so the follow-on is not scored as a direct
    deposit (audit r1-attribution-integrity-8)."""
    monkeypatch.setitem(HISTORY, "ETH", [tx(SEED, MID, 1.0, SWAP_AT - 60, "ETH"),
                                         tx(MID, ROUTER, 1.0, SWAP_AT, "ETH")])
    monkeypatch.setitem(HISTORY, "USDT", [tx(MID, BINANCE_14, 2400.0, SWAP_AT + 60, "USDT")])
    swap = {**SWAP, "sender": MID}
    monkeypatch.setattr(main, "detect_swaps", lambda graph, *a, **k: [swap] if k.get("asset_symbol") == "ETH" else [])

    found = run_trace(request())["follow_ons"][0]["result"]
    proximity = next(c for c in found["confidence_detail"]["components"] if c["name"] == "hop_proximity")
    assert found["hop_count"] == 1
    assert proximity["raw_value"] == 0.75
    assert "2 hops from the reported address (1 after the swap)" in proximity["explanation"]


def test_the_follow_on_estimate_is_capped_at_the_swap_output(faked, monkeypatch):
    """Audit r1-evidence-crypto-5: the swap returned 100 USDT, but the wallet
    already held more and sent 5,000 to Binance. At most 100 can be the
    swapped money."""
    monkeypatch.setitem(HISTORY, "USDT", [tx(SEED, BINANCE_14, 5000.0, SWAP_AT + 60, "USDT")])
    swap = {**SWAP, "amount_in": 0.04, "amount_out": 100.0}
    monkeypatch.setattr(main, "detect_swaps", lambda graph, *a, **k: [swap] if k.get("asset_symbol") == "ETH" else [])

    found = run_trace(request())["follow_ons"][0]["result"]
    assert found["prorata"]["estimated"] == 100.0
    assert found["prorata"]["seed_cap"] == {"amount": 100.0, "basis": "swap_output", "applied": True}
    assert found["materiality"]["basis"] == "swap_output" and found["materiality"]["denominator"] == 100.0


def test_the_follow_on_keeps_the_route_to_the_swap(faked, monkeypatch):
    monkeypatch.setitem(HISTORY, "ETH", [tx(SEED, MID, 1.0, SWAP_AT - 60, "ETH"),
                                         tx(MID, ROUTER, 1.0, SWAP_AT, "ETH")])
    monkeypatch.setitem(HISTORY, "USDT", [tx(MID, BINANCE_14, 2400.0, SWAP_AT + 60, "USDT")])
    swap = {**SWAP, "sender": MID}
    monkeypatch.setattr(main, "detect_swaps", lambda graph, *a, **k: [swap] if k.get("asset_symbol") == "ETH" else [])

    (follow,) = run_trace(request())["follow_ons"]
    assert [step["address"] for step in follow["route"]] == [SEED, MID]
    assert follow["route"][1]["value_native"] == 1.0
