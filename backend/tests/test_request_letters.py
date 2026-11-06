"""Tests for the draft request letters a case produces.

A letter goes to a company in a police force's name, so what must never happen
is a letter that asserts what the case does not hold -- an exchange it did not
reach, a legal power the tool picked for the officer -- or one that leaves out
the facts a compliance team needs to find the account.
"""
from __future__ import annotations

import pytest

from app.request_letters import LetterNotApplicable, available, draft

SEED = "0x" + "5eed".ljust(40, "0")
DEPOSIT = "0x" + "de9".ljust(40, "0")
TX = "0x" + "ab" * 32


def case(**over):
    result = {
        "address": SEED, "chain": "ethereum", "chain_name": "Ethereum Mainnet", "asset": "ETH",
        "direction": "outgoing", "created_at": "2026-09-24T10:00:00+00:00",
        "exchange": "Binance", "exchange_label": "Binance Dep: 0xde9…", "exchange_address": DEPOSIT,
        "attribution_inferred": False,
        "trace_path": [
            {"address": SEED, "depth": 0},
            {"address": DEPOSIT, "depth": 1, "label": "Binance Dep: 0xde9…", "value_native": 2.5,
             "tx_count": 1, "first_seen": 1_758_000_000, "last_seen": 1_758_000_000, "tx_hashes": [TX]},
        ],
        "risk_matches": [], "follow_ons": [],
        "evidence": {"manifest_sha256": "f" * 64},
    }
    result.update(over)
    return result


def test_the_exchange_letter_names_the_address_and_every_hop():
    text = draft("case-1", case(), "exchange")
    assert "Binance" in text and DEPOSIT in text and TX in text
    assert "2.500000 ETH" in text and "f" * 64 in text


def test_the_officer_supplies_the_legal_basis_the_tool_only_suggests_one():
    text = draft("case-1", case(), "exchange")
    assert "In exercise of the powers under [____" in text
    assert "officer to confirm" in text
    assert text.startswith("DRAFT")


def test_no_exchange_means_no_exchange_letter():
    result = case(exchange=None, exchange_address=None, trace_path=[])
    assert all(letter["to"] != "exchange" for letter in available(result))
    with pytest.raises(LetterNotApplicable):
        draft("case-1", result, "exchange")


def test_an_attribution_found_after_a_swap_is_written_from_the_follow_on():
    follow = case(asset="USDT", exchange="Binance", exchange_address=DEPOSIT)
    swap = {"sender": SEED, "amount_in": 1.0, "asset_in": "ETH", "router_label": "Uniswap V3: Router 2", "tx": TX}
    result = case(exchange=None, exchange_address=None,
                  follow_ons=[{"asset": "USDT", "swap": swap, "result": follow}])
    text = draft("case-1", result, "exchange")
    assert "for USDT at Uniswap V3: Router 2" in text and DEPOSIT in text


def test_the_tether_letter_lists_each_frozen_address_and_its_freeze():
    frozen = {"address": DEPOSIT, "category": "frozen", "label": "USDT frozen by Tether on 2026-09-11",
              "source": "Tether USDT contract on Tron, AddedBlackList event, tx abc"}
    result = case(risk_matches=[frozen])
    assert {"to": "tether", "title": "Request to Tether"} in available(result)
    text = draft("case-1", result, "tether")
    assert "USDT frozen by Tether on 2026-09-11" in text and "AddedBlackList" in text


def test_an_eth_trace_touching_no_usdt_offers_no_tether_letter():
    with pytest.raises(LetterNotApplicable):
        draft("case-1", case(), "tether")


def test_a_usdt_trace_on_tron_offers_a_tether_letter():
    result = case(chain="tron", chain_name="Tron", asset="USDT")
    assert any(letter["to"] == "tether" for letter in available(result))
    assert "USDT on Tron moved from" in draft("case-1", result, "tether")


def test_the_exchange_letter_names_the_pro_rata_amount():
    from app.request_letters import draft
    result = {
        "address": "0x" + "1" * 40, "chain_name": "BNB Smart Chain", "asset": "USDT",
        "direction": "outgoing", "exchange": "Binance", "exchange_address": "0x" + "2" * 40,
        "exchange_label": "Binance: Hot Wallet 6", "trace_path": [],
        "prorata": {"status": "estimated", "estimated": 9.42, "sent": 40.0, "arrived_total": 98.0},
    }
    letter = draft("c1", result, "exchange")
    assert "about 9.420000 USDT" in letter and "98.000000 USDT arrived" in letter
    assert "your own records of the deposits are authoritative" in letter


def test_recycled_value_is_never_called_other_sources():
    # Audit r1-attribution-integrity-5: W bounced the victim's 10,000 through
    # H nine times before sending it on. Nobody else's money joined, so the
    # letter must not say 9,000 "came from other sources".
    import networkx as nx

    from app.prorata import estimate

    class Row:
        def __init__(self, value, hash_, frm, to, block):
            self.value_native, self.hash, self.from_address, self.to_address = value, hash_, frm, to
            self.block_number = self.timestamp = block

    g = nx.DiGraph()
    g.add_edge("V", "W", value_native=10_000.0, transactions=[
        {"hash": "vw", "value_native": 10_000.0, "block_number": 100, "timestamp": 100}])
    g.add_edge("W", "X", value_native=10_000.0, transactions=[
        {"hash": "wx", "value_native": 10_000.0, "block_number": 200, "timestamp": 200}])
    out = [Row(10_000.0, f"o{i}", "W", "H", 110 + 2 * i) for i in range(9)]
    back = [Row(10_000.0, f"b{i}", "H", "W", 111 + 2 * i) for i in range(9)]
    prorata = estimate(g, ["V", "W", "X"], None, flows_between=lambda *a: (
        [Row(10_000.0, "vw", "V", "W", 100), *back], [*out, Row(10_000.0, "wx", "W", "X", 200)], True))
    letter = " ".join(draft("c1", case(asset="USDT", prorata=prorata), "exchange").split())
    assert "about 10,000.000000 USDT" in letter
    assert "other sources" not in letter


# ---------------------------------------------------------------------------
# The amount a letter states
# ---------------------------------------------------------------------------
PRORATA = {"status": "estimated", "estimated": 6000.0, "sent": 10000.0, "arrived_total": 6000.0, "hops": []}


def test_the_letter_states_the_conservative_figure():
    # Audit r1-attribution-integrity-12: the case view says a letter states the
    # smallest figure, so the letter must state it.
    methods = {"figures": {"fifo": 2000.0, "prorata": 6000.0, "libr": 4000.0},
               "range": {"low": 2000.0, "high": 6000.0}, "conservative": 2000.0, "conservative_method": "fifo"}
    result = case(asset="USDT", prorata=PRORATA, tracing_methods=methods,
                  estimates={"fifo": 2000.0, "prorata": 6000.0, "libr": 4000.0, "conservative": 2000.0})
    letter = " ".join(draft("c1", result, "exchange").split())
    assert "about 2,000.000000 USDT" in letter
    assert "(by FIFO, the smallest of the tracing rules applied; they give 2,000.000000 to 6,000.000000)" in letter
    assert "about 6,000.000000" not in letter
    # The figure the case view says a letter states.
    assert f"about {methods['conservative']:,.6f} USDT" in letter


def test_without_tracing_methods_the_letter_states_pro_rata():
    letter = " ".join(draft("c1", case(asset="USDT", prorata=PRORATA), "exchange").split())
    assert "about 6,000.000000 USDT" in letter and "tracing rules" not in letter


def test_an_address_only_letter_says_the_figure_may_include_other_peoples_money():
    # Audit r1-attribution-integrity-7.
    letter = " ".join(draft("c1", case(asset="USDT", prorata=PRORATA), "exchange").split())
    assert "of everything the reported address sent along this route" in letter
    assert "can include other people's money, not only the complainant's" in letter


def test_an_intake_letter_states_at_most_the_reported_amount():
    # An older intake case, traced before the cap: the letter applies it anyway.
    result = case(asset="USDT", prorata=PRORATA, reported_amount=1000.0,
                  intake={"mode": "payment", "payments": [{"tx_hash": TX, "amount": 1000.0}]})
    letter = " ".join(draft("c1", result, "exchange").split())
    assert "about 1,000.000000 of the 1,000.000000 USDT the victim reported paying reached this address" in letter
    assert "about 6,000.000000" not in letter


SWAPPER = "0x" + "5a9".ljust(40, "0")


def follow_on_case(**swap_over):
    follow = case(address=SWAPPER, asset="USDT", prorata={**PRORATA, "estimated": 5000.0, "sent": 5000.0,
                                                          "arrived_total": 5000.0})
    swap = {"sender": SWAPPER, "amount_in": 0.04, "asset_in": "ETH", "asset_out": "USDT", "amount_out": 100.0,
            "router_label": "Uniswap V3: Router 2", "tx": TX, **swap_over}
    route = [{"address": SEED, "depth": 0},
             {"address": SWAPPER, "depth": 1, "value_native": 0.04, "tx_count": 1,
              "first_seen": 1_758_000_000, "last_seen": 1_758_000_000, "tx_hashes": ["0x" + "cd" * 32]}]
    return case(exchange=None, exchange_address=None,
                follow_ons=[{"asset": "USDT", "address": SWAPPER, "swap": swap, "route": route, "result": follow}])


def test_a_follow_on_letter_never_states_more_than_the_swap_returned():
    # Audit r1-evidence-crypto-5: 0.04 ETH swapped for 100 USDT; the swapper
    # sent 5,000 USDT on.
    letter = " ".join(draft("c1", follow_on_case(), "exchange").split())
    assert "of the 100.000000 USDT the swap returned, about 100.000000 USDT reached this address" in letter
    assert "sent from the reported address" not in letter
    assert "5,000.000000 USDT reached" not in letter


def test_a_follow_on_letter_does_not_call_the_swapper_the_reported_address():
    letter = draft("c1", follow_on_case(), "exchange")
    assert f"Reported address: {SEED}" in letter
    assert f"Swapping wallet (follow-on start): {SWAPPER}" in letter
    assert f"Reported address: {SWAPPER}" not in letter
    assert "0x" + "cd" * 32 in letter  # the route to the swap, in ETH


def test_paragraph_two_names_the_asset_the_reported_address_sent():
    letter = " ".join(draft("c1", follow_on_case(), "exchange").split())
    assert "show ETH moving from that address and, after a swap at Uniswap V3: Router 2" in letter
    assert f"USDT moving from {SWAPPER} to the address" in letter
    assert "exchanged 0.040000 ETH for 100.000000 USDT" in letter


def test_an_older_follow_on_without_its_route_points_to_the_report():
    result = follow_on_case()
    del result["follow_ons"][0]["route"]
    assert "Route to the swapping wallet: see the attached report" in draft("c1", result, "exchange")
