"""Tests for swap detection at DEX routers.

The receipt fixture is a real Ethereum mainnet receipt (tx 0x5782df21...,
2,000 ETH into 1inch v4, 1,901.31 wstETH back to the sender), saved so the
parser is tested against the provider's actual shape rather than a guess at
it. The other side of every test is that nothing is claimed when the receipt
does not show a token coming back: a swap into the native coin leaves no
Transfer to the sender, and the rule must say "could not read", not invent an
output.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import config
from app.exchange_matcher import ExchangeMatcher
from app.swap_detection import TRANSFER_TOPIC, describe, detect_swaps, parse_swap_outputs

from conftest import addr, make_graph

FIXTURE = Path(__file__).parent / "fixtures" / "receipt_1inch_v4_eth_to_wsteth.json"
RECEIPT = json.loads(FIXTURE.read_text())
SENDER = "0x4655b7ad0b5f5bacb9cf960bbffceb3f0e51f363"
ROUTER = "0x1111111254fb6c44bac0bed2854e76f90643097d"
WSTETH = "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0"
ETHEREUM = config.CHAINS["ethereum"]

SEED = addr("5eed")


def routers():
    return ExchangeMatcher(
        {ROUTER: {"exchange": "1inch", "label": "1inch v4: Aggregation Router", "type": "router"}},
        chain="ethereum",
    )


def router_graph(sender: str = SENDER, tx_hash: str = RECEIPT["transactionHash"]):
    graph = make_graph([(SEED, sender, 2000.0), (sender, ROUTER, 2000.0)], seed=SEED)
    graph.edges[sender, ROUTER]["transactions"][0]["hash"] = tx_hash
    return graph


# ---------------------------------------------------------------------------
# Reading the receipt
# ---------------------------------------------------------------------------
def test_the_swap_output_is_the_transfer_back_to_the_sender():
    outputs = parse_swap_outputs(RECEIPT, SENDER)
    assert len(outputs) == 1
    assert outputs[0]["contract"] == WSTETH
    assert outputs[0]["units"] == 1901312050502850484000


def test_transfers_to_other_parties_are_not_outputs():
    """The receipt holds six Transfer events; only one is to the sender."""
    transfers = [l for l in RECEIPT["logs"] if l["topics"][0] == TRANSFER_TOPIC]
    assert len(transfers) > 1
    assert parse_swap_outputs(RECEIPT, addr("c1")) == []


def test_a_receipt_with_no_transfer_to_the_sender_yields_nothing():
    receipt = {"logs": [{"address": WSTETH, "topics": [TRANSFER_TOPIC], "data": "0x1"}]}
    assert parse_swap_outputs(receipt, SENDER) == []


# ---------------------------------------------------------------------------
# Annotating the graph
# ---------------------------------------------------------------------------
def test_a_swap_is_recorded_on_the_edge_and_the_router_is_marked():
    graph = router_graph()
    swaps = detect_swaps(graph, routers(), lambda h: RECEIPT, ETHEREUM, "ETH")

    assert len(swaps) == 1
    swap = swaps[0]
    assert swap["router"] == "1inch"
    assert swap["asset_in"] == "ETH"
    assert swap["amount_in"] == 2000.0
    assert swap["output_read"] is True
    assert swap["asset_out_contract"] == WSTETH
    # wstETH is not a configured token, so the amount is left in units rather
    # than divided by a guessed 18 decimals.
    assert swap["asset_out"] == f"token {WSTETH}"
    assert swap["amount_out"] is None
    assert swap["amount_out_units"] == "1901312050502850484000"
    assert graph.edges[SENDER, ROUTER]["swap"] is swap
    assert graph.nodes[ROUTER]["is_router"] is True
    assert graph.nodes[ROUTER]["router"] == "1inch"


def test_a_configured_token_is_named_with_a_human_amount():
    usdt = ETHEREUM.tokens[0]
    receipt = {"logs": [{
        "address": usdt.address,
        "topics": [TRANSFER_TOPIC, "0x" + "0" * 24 + ROUTER[2:], "0x" + "0" * 24 + SENDER[2:]],
        "data": hex(2_400_000_000),
    }]}
    swaps = detect_swaps(router_graph(), routers(), lambda h: receipt, ETHEREUM, "ETH")
    assert swaps[0]["asset_out"] == "USDT"
    assert swaps[0]["amount_out"] == pytest.approx(2400.0)


def test_a_transfer_to_an_ordinary_wallet_is_not_a_swap():
    graph = make_graph([(SEED, addr("a1"), 1.0), (addr("a1"), addr("b2"), 1.0)], seed=SEED)
    assert detect_swaps(graph, routers(), lambda h: RECEIPT, ETHEREUM, "ETH") == []
    assert "swap" not in graph.edges[addr("a1"), addr("b2")]


def test_a_swap_whose_output_cannot_be_read_is_reported_not_guessed():
    """Native-coin outputs leave no Transfer to the sender."""
    swaps = detect_swaps(router_graph(), routers(), lambda h: {"logs": []}, ETHEREUM, "ETH")
    assert swaps[0]["output_read"] is False
    assert swaps[0]["asset_out"] is None
    assert "could not be read" in describe(swaps[0])


def test_a_failed_receipt_lookup_does_not_kill_the_trace():
    def boom(_h):
        raise RuntimeError("provider down")

    swaps = detect_swaps(router_graph(), routers(), boom, ETHEREUM, "ETH")
    assert len(swaps) == 1
    assert swaps[0]["output_read"] is False


def test_no_receipt_source_still_marks_the_router():
    graph = router_graph()
    swaps = detect_swaps(graph, routers(), None, ETHEREUM, "ETH")
    assert graph.nodes[ROUTER]["is_router"] is True
    assert swaps[0]["output_read"] is False


def test_receipts_per_edge_are_capped():
    graph = router_graph()
    edge = graph.edges[SENDER, ROUTER]
    edge["transactions"] = [dict(edge["transactions"][0], hash=f"0x{i:064x}") for i in range(5)]
    calls = []

    def receipt_of(h):
        calls.append(h)
        return RECEIPT

    detect_swaps(graph, routers(), receipt_of, ETHEREUM, "ETH")
    assert len(calls) == 2


def test_the_sentence_says_where_to_resume():
    swaps = detect_swaps(router_graph(), routers(), lambda h: RECEIPT, ETHEREUM, "ETH")
    text = describe(swaps[0])
    assert "a swap, not a payment" in text
    assert f"re-run it on token {WSTETH} from {SENDER}" in text


# ---------------------------------------------------------------------------
# Second adversarial pass: what must never be called a swap
# ---------------------------------------------------------------------------
def test_a_refund_of_the_traced_token_is_not_a_swap_output():
    """On a USDT trace, unspent USDT coming back is a refund; reporting it as
    'swapped USDT for USDT' would send an officer chasing nothing."""
    usdt = ETHEREUM.tokens[0]
    receipt = {"logs": [{
        "address": usdt.address,
        "topics": [TRANSFER_TOPIC, "0x" + "0" * 24 + ROUTER[2:], "0x" + "0" * 24 + SENDER[2:]],
        "data": hex(5_000_000),
    }]}
    swaps = detect_swaps(router_graph(), routers(), lambda h: receipt, ETHEREUM, "USDT",
                         asset_contract=usdt.address)
    assert swaps[0]["output_read"] is False


def test_a_contracts_internal_payout_to_a_router_is_not_its_swap():
    """A pool settling a stranger's swap pays the router by internal transfer.
    Reading that receipt would report the stranger's input as the pool's
    output and tell the officer to re-run from the pool."""
    graph = router_graph()
    for t in graph.edges[SENDER, ROUTER]["transactions"]:
        t["internal"] = True
    swaps = detect_swaps(graph, routers(), lambda h: RECEIPT, ETHEREUM, "ETH")
    assert swaps == []
    assert "swap" not in graph.edges[SENDER, ROUTER]
