"""Provider clients fail fast where waiting cannot help.

- Every retry loop slept after its final attempt too (8 s wasted on Etherscan).
- A spent daily (Etherscan) or monthly (NodeReal) quota was retried as if it
  were a momentary rate limit -- five more refused calls, each also slowing
  the shared pacer for every other trace -- and reached the officer as "rate
  limit, try again in a few seconds".
- NodeReal's paged scan ended only when a page came back without a pageKey,
  so a provider answering empty pages that still carry one looped for ever.
- A follow-on trace that failed with anything but an HTTP error threw away
  the finished trace that found it.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app import etherscan_client, nodereal_client, tron_client
from app.etherscan_client import EtherscanClient, ProviderQuotaError
from app.nodereal_client import NoderealClient
from app.tron_client import TronClient

ADDRESS = "0x" + "1" * 40


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    for module in (etherscan_client, nodereal_client, tron_client):
        monkeypatch.setattr(module.time, "sleep", lambda s, calls=calls: calls.append(s))
    return calls


def test_no_sleep_after_the_last_etherscan_attempt(sleeps):
    client = EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, max_retries=4,
                             client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    with pytest.raises(etherscan_client.EtherscanError):
        client.get_outgoing_transactions(ADDRESS)
    assert len(sleeps) == 4  # 5 attempts, 4 waits between them


def test_no_sleep_after_the_last_trongrid_attempt(sleeps):
    client = TronClient(api_key="k", min_interval=0, max_retries=3,
                        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    with pytest.raises(tron_client.TronError):
        client.get_outgoing_transactions("TSFFxCbDLh6nP1x4BcyqkbEFJyx3zSGY2r")
    assert len(sleeps) == 3


def test_a_spent_etherscan_daily_quota_is_not_retried(sleeps, monkeypatch):
    calls = []

    def daily(request):
        calls.append(request)
        return httpx.Response(200, json={"status": "0", "message": "NOTOK",
                                         "result": "Max daily rate limit reached. 110000 (100000 + 10%) calls per day"})
    client = EtherscanClient(api_key="k", chain_id=1, min_interval=0.0,
                             client=httpx.Client(transport=httpx.MockTransport(daily)))
    penalties = []
    monkeypatch.setattr(client._pacer, "penalize", lambda *a, **k: penalties.append(1))
    with pytest.raises(ProviderQuotaError):
        client.get_outgoing_transactions(ADDRESS)
    assert len(calls) == 1 and sleeps == [] and penalties == []


def test_a_spent_nodereal_monthly_quota_is_not_retried(sleeps):
    calls = []

    def monthly(request):
        body = json.loads(request.content)
        if body["method"] == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(40_000_000)})
        calls.append(body["method"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                         "error": {"code": -32005, "message": "monthly CU limit exceeded"}})
    client = NoderealClient(api_key="k", min_interval=0,
                            client=httpx.Client(transport=httpx.MockTransport(monthly)))
    with pytest.raises(ProviderQuotaError):
        client.get_outgoing_transactions(ADDRESS)
    assert len(calls) == 1 and sleeps == []


def _paging(pages):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        if body["method"] == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(40_000_000)})
        calls.append(body["params"][0].get("pageKey"))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": pages(len(calls))})
    return NoderealClient(api_key="k", min_interval=0, client=httpx.Client(transport=httpx.MockTransport(handler))), calls


def test_an_empty_page_that_still_offers_more_ends_the_window():
    client, calls = _paging(lambda n: {"transfers": [], "pageKey": f"k{n}"})
    out, capped = client._scan(ADDRESS, "fromAddress", cap=50, top=40_000_000, floor=40_000_000 - 100)
    assert out == [] and len(calls) <= 2
    assert capped is True  # never read as "sent nothing"


def test_a_repeated_page_key_ends_the_window():
    record = {"hash": "0x1", "from": ADDRESS, "to": "0x" + "2" * 40, "value": hex(10**18), "decimal": 18,
              "blockNum": hex(40_000_000 - 5), "blockTimeStamp": 1_700_000_000, "asset": "BNB", "receiptsStatus": 1}
    client, calls = _paging(lambda n: {"transfers": [dict(record, hash=f"0x{n:x}")], "pageKey": "same"})
    _, capped = client._scan(ADDRESS, "fromAddress", cap=500, top=40_000_000, floor=40_000_000 - 100)
    assert len(calls) <= 3
    assert capped is True
