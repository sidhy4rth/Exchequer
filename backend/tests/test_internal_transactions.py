"""Tests for internal transactions on Ethereum.

Value moved by a contract call -- a multisig paying out, a router returning
ETH -- never appears in Etherscan's txlist. Reading txlistinternal too costs a
second request per address, so the tests pin both halves: that the money is
seen, and that the cost is exactly one extra request and nothing on a token
trace, where the switch does not apply.
"""
from __future__ import annotations

import httpx

from app.etherscan_client import EtherscanClient

ADDR = "0xAAaa0000000000000000000000000000000000aa"
OTHER = "0xBBbb0000000000000000000000000000000000bb"
MULTISIG = "0xCCcc0000000000000000000000000000000000cc"

NORMAL = {"hash": "0x01", "from": ADDR, "to": OTHER, "value": "1000000000000000000",
          "timeStamp": "1700000100", "blockNumber": "18000001", "isError": "0"}
INTERNAL = {"hash": "0x02", "from": MULTISIG, "to": ADDR, "value": "5000000000000000000",
            "timeStamp": "1700000200", "blockNumber": "18000002", "isError": "0",
            "type": "call", "traceId": "0"}


def make_client(**kwargs):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        action = request.url.params.get("action")
        seen.append(action)
        rows = [NORMAL] if action == "txlist" else [INTERNAL] if action == "txlistinternal" else []
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})

    client = EtherscanClient(api_key="k", chain_id=1, min_interval=0.0,
                             client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)
    return client, seen


def test_internal_transfers_are_merged_and_tagged():
    client, seen = make_client(include_internal=True)
    txs = client.get_transactions(ADDR)

    assert seen == ["txlist", "txlistinternal"]
    assert [t.hash for t in txs] == ["0x02", "0x01"]  # newest first across both sources
    assert txs[0].internal is True and txs[0].value_native == 5.0
    assert txs[1].internal is False


def test_a_wallet_that_signs_transfers_costs_one_request_on_a_forward_trace():
    """It cannot originate an internal transfer, so the second request is
    never made for it."""
    client, seen = make_client(include_internal=True)
    client.get_outgoing_transactions(ADDR)
    assert seen == ["txlist"]


def test_a_contract_with_no_signed_outflow_is_asked_for_internal_payouts():
    client, seen = make_client(include_internal=True)
    out = client.get_outgoing_transactions(MULTISIG)
    assert seen == ["txlist", "txlistinternal"]
    assert [t.to_address for t in out] == [ADDR.lower()]
    assert out[0].internal is True


def test_the_incoming_view_sees_a_contract_payout():
    """A multisig paying the reported address is exactly what was invisible."""
    client, _ = make_client(include_internal=True)
    incoming = client.get_incoming_transactions(ADDR)
    assert [t.from_address for t in incoming] == [MULTISIG.lower()]
    assert incoming[0].internal is True


def test_the_switch_off_costs_one_request_and_sees_no_internal_value():
    client, seen = make_client(include_internal=False)
    txs = client.get_transactions(ADDR)
    assert seen == ["txlist"]
    assert all(not t.internal for t in txs)


def test_a_token_trace_never_asks_for_internal_transactions():
    """ERC-20 transfers are events, not internal calls; the switch does not apply."""
    client, seen = make_client(include_internal=True,
                               contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7")
    client.get_transactions(ADDR)
    assert seen == ["tokentx"]


def test_both_requests_are_cached_so_the_second_ask_is_free():
    client, seen = make_client(include_internal=True)
    client.get_transactions(ADDR)
    client.get_transactions(ADDR)
    assert len(seen) == 2


def test_internal_transfers_never_displace_signed_ones():
    """Each source is capped by its own request; the union is not capped
    again, or a burst of recent internal inflows would push the older signed
    outflows the trace is following out of the window."""
    client, _ = make_client(include_internal=True)
    txs = client.get_transactions(ADDR, limit=1)
    assert {t.hash for t in txs} == {"0x01", "0x02"}
