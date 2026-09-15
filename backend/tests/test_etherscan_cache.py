"""The response cache, exercised through the real client against a fake network.

The point of these is the request *count*, not the parsing: on a free tier a
trace's wall time is very nearly the number of requests it makes, so "the second
ask costs no request" is the behaviour worth pinning down.
"""
from __future__ import annotations

import httpx
import pytest

from app.etherscan_client import EtherscanClient


def make_client(payload: dict, **kwargs) -> tuple[EtherscanClient, list]:
    """A client wired to a fake transport that records every request it sees."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = EtherscanClient(
        api_key="test-key",
        chain_id=1,
        # No spacing: these tests are about how many requests happen, not when.
        min_interval=0.0,
        client=httpx.Client(transport=transport),
        **kwargs,
    )
    return client, seen


TX = {
    "hash": "0xdead",
    "from": "0xAAaa0000000000000000000000000000000000aa",
    "to": "0xBBbb0000000000000000000000000000000000bb",
    "value": "1000000000000000000",
    "timeStamp": "1700000000",
    "blockNumber": "18000000",
    "isError": "0",
}
OK = {"status": "1", "message": "OK", "result": [TX]}
EMPTY = {"status": "0", "message": "No transactions found", "result": []}

ADDR = "0xAAaa0000000000000000000000000000000000aa"


def test_repeated_query_makes_one_request():
    client, seen = make_client(OK)
    first = client.get_transactions(ADDR)
    second = client.get_transactions(ADDR)
    assert len(seen) == 1
    assert [t.hash for t in first] == [t.hash for t in second]


def test_both_directions_share_one_request():
    """A reverse trace reads the same combined list a forward trace already read.

    This is the whole reason a cache helps here: Etherscan's txlist returns both
    directions in one response, so asking for the other direction is a filter
    over data already in hand, not a second call.
    """
    client, seen = make_client(OK)
    client.get_outgoing_transactions(ADDR)
    client.get_incoming_transactions(ADDR)
    assert len(seen) == 1


def test_empty_result_is_cached_too():
    """"Nothing here" costs the same second to re-ask as a full list."""
    client, seen = make_client(EMPTY)
    assert client.get_transactions(ADDR) == []
    assert client.get_transactions(ADDR) == []
    assert len(seen) == 1


def test_different_addresses_are_cached_separately():
    client, seen = make_client(OK)
    client.get_transactions(ADDR)
    client.get_transactions("0xCCcc0000000000000000000000000000000000cc")
    assert len(seen) == 2


def test_different_chains_are_cached_separately():
    """The same address has unrelated histories on Ethereum and BSC."""
    client, seen = make_client(OK)
    client.get_transactions(ADDR)
    client.chain_id = 56
    client.get_transactions(ADDR)
    assert len(seen) == 2


def test_token_and_native_queries_are_cached_separately():
    """`tokentx` and `txlist` are different questions about the same address."""
    native, seen = make_client(OK)
    native.get_transactions(ADDR)
    assert len(seen) == 1

    token, token_seen = make_client(
        OK, contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7"
    )
    token.get_transactions(ADDR)
    assert len(token_seen) == 1


def test_clients_sharing_a_key_share_the_cache():
    """A client is built per trace, so the cache cannot live on the instance."""
    first, first_seen = make_client(OK)
    first.get_transactions(ADDR)
    second, second_seen = make_client(OK)
    second.get_transactions(ADDR)
    assert len(first_seen) == 1
    assert len(second_seen) == 0


def test_rate_limit_widens_the_shared_interval():
    """A refusal has to slow every trace on that key, not just this request."""
    payload = {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}
    client, seen = make_client(payload, max_retries=1)
    before = client._pacer.interval
    with pytest.raises(Exception):
        client.get_transactions(ADDR)
    assert client._pacer.interval > before
    assert client._pacer.stats()["rate_limit_penalties"] >= 1
