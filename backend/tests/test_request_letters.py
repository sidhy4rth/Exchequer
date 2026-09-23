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
