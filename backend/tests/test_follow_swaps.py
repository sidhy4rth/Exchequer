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


def test_a_decoy_token_does_not_stop_the_follow_on(faked, monkeypatch):
    """Audit r1-attribution-integrity-4: a worthless token in the same
    receipt must not stand in for the USDT the swap returned."""
    decoy = {"contract": "0xfa4e" + "0" * 36, "asset": "token 0xfa4e" + "0" * 36, "units": str(10**18),
             "amount": None}
    usdt = {"contract": "0xdac17f958d2ee523a2206206994597c13d831ec7", "asset": "USDT", "units": "2400000000",
            "amount": 2400.0}
    # Even a record that names the decoy as its output is followed in USDT.
    swap = {**SWAP, "asset_out": decoy["asset"], "amount_out": None, "amount_out_units": decoy["units"],
            "outputs": [decoy, usdt], "other_outputs": 1}
    monkeypatch.setattr(main, "detect_swaps", lambda graph, *a, **k: [swap] if k.get("asset_symbol") == "ETH" else [])
    (follow,) = run_trace(request())["follow_ons"]
    assert follow["swap"]["amount_out"] == 2400.0
    assert follow["asset"] == "USDT" and follow["result"]["exchange"] == "Binance"


def test_every_configured_output_is_followed_once(faked, monkeypatch):
    monkeypatch.setitem(HISTORY, "USDC", [tx(SEED, BINANCE_14, 300.0, SWAP_AT + 60, "USDC")])
    outputs = [{"contract": "0xdac17f958d2ee523a2206206994597c13d831ec7", "asset": "USDT", "units": "2400000000",
                "amount": 2400.0},
               {"contract": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "asset": "USDC", "units": "300000000",
                "amount": 300.0}]
    swap = {**SWAP, "outputs": outputs, "other_outputs": 1}
    monkeypatch.setattr(main, "detect_swaps", lambda graph, *a, **k: [swap] if k.get("asset_symbol") == "ETH" else [])
    follows = run_trace(request())["follow_ons"]
    assert [(f["asset"], f["swap"]["asset_out"], f["swap"]["amount_out"]) for f in follows] == [
        ("USDT", "USDT", 2400.0), ("USDC", "USDC", 300.0)]


PAID = tx(addr("71c"), SEED, 1.0, SWAP_AT - 60, "ETH")


class PaidClient(FakeClient):
    """The same wallet, entered by the victim's payment into it."""

    def get_incoming_transactions(self, address, limit=None):
        return [PAID] if address == SEED and self.history is HISTORY["ETH"] else []


@pytest.fixture
def paid(monkeypatch, faked):
    from app import config

    @contextmanager
    def open_source(chain, asset):
        yield PaidClient(HISTORY[asset])

    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(config, "TX_INTAKE", True)


def test_a_payment_trace_still_follows_the_swap(paid):
    result = run_trace(request(payments=[{"tx_hash": PAID.hash}]))
    assert result["intake"]["mode"] == "payment"
    (follow,) = result["follow_ons"]
    assert follow["result"]["exchange"] == "Binance"
    assert result["followed_attribution"]["exchange"] == "Binance"


def test_a_follow_on_never_follows_again(faked):
    result = run_trace(request(), seed_window=SWAP_AT - 1, is_follow_on=True)
    assert result["follow_ons"] == [] and result["statement"] is None


# ---------------------------------------------------------------------------
# What a follow-on may state, and which swaps are followed (an adversarial
# check of the r1-evidence-crypto-5 fix)
# ---------------------------------------------------------------------------

USDT_ETH = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC_ETH = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


def output(asset, amount):
    return {"contract": USDT_ETH if asset == "USDT" else USDC_ETH, "asset": asset,
            "units": str(int(amount * 1e6)), "amount": amount}


def swaps_are(monkeypatch, found, asset="ETH"):
    monkeypatch.setattr(main, "detect_swaps",
                        lambda graph, *a, **k: list(found) if k.get("asset_symbol") == asset else [])


def test_a_dust_swap_before_the_real_one_does_not_cap_the_follow_on(faked, monkeypatch):
    """A 0.25 USDT swap, then the real 2,400 one, then 2,400.25 USDT to
    Binance. The first swap's output capped the whole follow-on at 0.25; the
    cap is every swap by that wallet into USDT."""
    dust = {**SWAP, "tx": "0xd057", "timestamp": SWAP_AT - 30, "amount_in": 0.0001, "amount_out": 0.25}
    monkeypatch.setitem(HISTORY, "ETH", [tx(SEED, ROUTER, 0.0001, SWAP_AT - 30, "ETH"),
                                         tx(SEED, ROUTER, 1.0, SWAP_AT, "ETH")])
    monkeypatch.setitem(HISTORY, "USDT", [tx(SEED, BINANCE_14, 2400.25, SWAP_AT + 60, "USDT")])
    swaps_are(monkeypatch, [dust, SWAP])

    (follow,) = run_trace(request())["follow_ons"]
    found = follow["result"]
    assert found["prorata"]["estimated"] == 2400.25
    assert found["prorata"]["seed_cap"] == {"amount": 2400.25, "basis": "swap_output", "applied": False}
    assert found["materiality"]["denominator"] == 2400.25
    assert follow["cap"]["swap_output"] == 2400.25 and follow["cap"]["swaps"] == 2
    assert follow["swap"]["tx"] == SWAP["tx"]  # the swap named is the largest
    assert [s["tx"] for s in follow["swaps"]] == ["0xd057", SWAP["tx"]]


def test_a_decoy_output_cannot_take_the_slot_of_the_real_swap(faked, monkeypatch):
    """The reported wallet's tiny swap also pays it 1 USDC. Its two outputs
    took both follow-on slots, so the real swap one wallet on was never
    followed. Follow-ons are chosen by how much traced money went into them."""
    tiny = {**SWAP, "tx": "0x7171", "timestamp": SWAP_AT - 30, "amount_in": 0.0001, "asset_out": "USDC",
            "amount_out": 1.0, "outputs": [output("USDC", 1.0), output("USDT", 0.25)], "other_outputs": 1}
    real = {**SWAP, "sender": MID, "tx": "0x4ea1"}
    monkeypatch.setitem(HISTORY, "ETH", [tx(SEED, ROUTER, 0.0001, SWAP_AT - 30, "ETH"),
                                         tx(SEED, MID, 1.0, SWAP_AT - 60, "ETH"),
                                         tx(MID, ROUTER, 1.0, SWAP_AT, "ETH")])
    monkeypatch.setitem(HISTORY, "USDT", [tx(MID, BINANCE_14, 2400.0, SWAP_AT + 60, "USDT")])
    monkeypatch.setitem(HISTORY, "USDC", [])
    swaps_are(monkeypatch, [tiny, real])

    result = run_trace(request())
    assert len(result["follow_ons"]) == main.MAX_FOLLOW_ONS
    first = result["follow_ons"][0]
    assert (first["address"], first["asset"]) == (MID, "USDT")
    assert first["result"]["exchange"] == "Binance"
    assert result["followed_attribution"]["exchange"] == "Binance"


def test_the_follow_on_is_capped_at_the_traced_share_of_the_swap(faked, monkeypatch):
    """0.04 ETH of the traced money reached a wallet that added its own ETH
    and swapped 10 ETH for 25,000 USDT. At most 0.4% of what the swap
    returned can be the traced money: 100 USDT, not 25,000."""
    monkeypatch.setitem(HISTORY, "ETH", [tx(SEED, MID, 0.04, SWAP_AT - 60, "ETH"),
                                         tx(MID, ROUTER, 10.0, SWAP_AT, "ETH")])
    monkeypatch.setitem(HISTORY, "USDT", [tx(MID, BINANCE_14, 25000.0, SWAP_AT + 60, "USDT")])
    swaps_are(monkeypatch, [{**SWAP, "sender": MID, "amount_in": 10.0, "amount_out": 25000.0}])

    (follow,) = run_trace(request())["follow_ons"]
    found = follow["result"]
    assert follow["cap"] == {"amount": 100.0, "basis": "swap_share", "swap_output": 25000.0, "swap_input": 10.0,
                             "traced_in": 0.04, "share": 0.004, "swaps": 1}
    assert found["prorata"]["estimated"] == 100.0
    assert found["prorata"]["seed_cap"] == {"amount": 100.0, "basis": "swap_share", "applied": True}
    # Which exchange got the money is still read against the whole output.
    assert found["materiality"]["denominator"] == 25000.0
    assert found["materiality"]["primary_share"] == 1.0
    assert found["exchange"] == "Binance"


def test_the_reported_wallets_own_swap_is_not_scaled_in_an_address_only_trace(faked):
    """Everything the reported wallet sent is the starting figure of an
    address-only trace, so its own swap is taken whole (the letter says the
    figure can include other people's money)."""
    (follow,) = run_trace(request())["follow_ons"]
    assert follow["cap"]["basis"] == "swap_output" and follow["cap"]["share"] is None
    assert follow["cap"]["amount"] == 2400.0


USDT_PAID = tx(addr("71c"), SEED, 1000.0, SWAP_AT - 60, "USDT")


class UsdtPaidClient(FakeClient):
    """The reported wallet, entered by the victim's 1,000 USDT payment."""

    def get_incoming_transactions(self, address, limit=None):
        return [USDT_PAID] if address == SEED and self.history is HISTORY["USDT"] else []


def test_an_intake_follow_on_keeps_the_victims_share(faked, monkeypatch):
    """The victim reported paying 1,000 USDT; the wallet swapped 50,000 USDT
    for 50,000 USDC and sent it to Binance. The follow-on carried no
    payments, so the cap was the whole 50,000. The victim's money can be at
    most 1,000 of the 50,000 that went into the swap."""
    from app import config

    @contextmanager
    def open_source(chain, asset):
        yield UsdtPaidClient(HISTORY[asset])

    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(config, "TX_INTAKE", True)
    monkeypatch.setitem(HISTORY, "USDT", [tx(SEED, ROUTER, 50000.0, SWAP_AT, "USDT")])
    monkeypatch.setitem(HISTORY, "USDC", [tx(SEED, BINANCE_14, 50000.0, SWAP_AT + 60, "USDC")])
    swaps_are(monkeypatch, [{**SWAP, "asset_in": "USDT", "amount_in": 50000.0, "asset_out": "USDC",
                             "amount_out": 50000.0}], asset="USDT")

    result = run_trace(TraceRequest(address=SEED, chain="ethereum", asset="USDT", max_depth=3,
                                    payments=[{"tx_hash": USDT_PAID.hash}]))
    assert result["reported_amount"] == 1000.0
    (follow,) = result["follow_ons"]
    assert follow["cap"]["basis"] == "swap_share" and follow["cap"]["amount"] == 1000.0
    assert follow["cap"]["traced_in"] == 1000.0 and follow["cap"]["share"] == 0.02
    assert follow["result"]["prorata"]["estimated"] == 1000.0


def test_the_report_states_what_the_follow_on_may_claim(faked, monkeypatch):
    import json

    from app.models import Case
    from app.report import build_report, render_text_report

    monkeypatch.setitem(HISTORY, "ETH", [tx(SEED, MID, 0.04, SWAP_AT - 60, "ETH"),
                                         tx(MID, ROUTER, 5.0, SWAP_AT, "ETH"),
                                         tx(MID, ROUTER, 5.0, SWAP_AT + 10, "ETH")])
    monkeypatch.setitem(HISTORY, "USDT", [tx(MID, BINANCE_14, 25000.0, SWAP_AT + 60, "USDT")])
    swaps_are(monkeypatch, [{**SWAP, "sender": MID, "amount_in": 5.0, "amount_out": 12500.0},
                            {**SWAP, "sender": MID, "tx": "0xdef", "timestamp": SWAP_AT + 10, "amount_in": 5.0,
                             "amount_out": 12500.0}])
    result = run_trace(request())
    case = Case(id="c1", address=SEED, created_at="2026-09-24T00:00:00+00:00",
                result_json=json.dumps(result, default=str))
    text = " ".join(render_text_report(build_report(case)).split())
    assert "swap returned : 25,000.0000 USDT (2 swaps)" in text
    assert "traced share : at most 100.0000 USDT (at most 0.0400 of the 10.0000 ETH swapped)" in text


def test_the_letter_after_a_dust_swap_states_both_swaps(faked, monkeypatch):
    """The checker's probe, end to end: the letter said 'of the 0.250000 USDT
    the swap returned, about 0.250000 USDT reached this address'."""
    from app.request_letters import draft

    dust = {**SWAP, "tx": "0xd057", "timestamp": SWAP_AT - 30, "amount_in": 0.0001, "amount_out": 0.25}
    monkeypatch.setitem(HISTORY, "ETH", [tx(SEED, ROUTER, 0.0001, SWAP_AT - 30, "ETH"),
                                         tx(SEED, ROUTER, 1.0, SWAP_AT, "ETH")])
    monkeypatch.setitem(HISTORY, "USDT", [tx(SEED, BINANCE_14, 2400.25, SWAP_AT + 60, "USDT")])
    swaps_are(monkeypatch, [dust, SWAP])
    letter = " ".join(draft("c1", run_trace(request()), "exchange").split())
    assert "of the 2,400.250000 USDT the 2 swaps returned, about 2,400.250000 USDT reached this address" in letter


def test_an_intake_letter_after_a_swap_states_at_most_the_victims_share(faked, monkeypatch):
    from app import config
    from app.request_letters import draft

    @contextmanager
    def open_source(chain, asset):
        yield UsdtPaidClient(HISTORY[asset])

    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(config, "TX_INTAKE", True)
    monkeypatch.setitem(HISTORY, "USDT", [tx(SEED, ROUTER, 50000.0, SWAP_AT, "USDT")])
    monkeypatch.setitem(HISTORY, "USDC", [tx(SEED, BINANCE_14, 50000.0, SWAP_AT + 60, "USDC")])
    swaps_are(monkeypatch, [{**SWAP, "asset_in": "USDT", "amount_in": 50000.0, "asset_out": "USDC",
                             "amount_out": 50000.0}], asset="USDT")
    result = run_trace(TraceRequest(address=SEED, chain="ethereum", asset="USDT", max_depth=3,
                                    payments=[{"tx_hash": USDT_PAID.hash}]))
    letter = " ".join(draft("c1", result, "exchange").split())
    assert "at most 1,000.000000 USDC can be the victim's" in letter
    assert "about 1,000.000000 USDC of it reached this address" in letter
    assert "about 50,000.000000" not in letter
