"""NodeReal, TronGrid and TronScan share one pacer per credential (r1-providers-3).

Each client paced only itself and one is built per trace, so four concurrent
traces sent four times the rate the provider allows for the key; none of them
slowed down when refused; and NodeReal was spaced at 0.12 s whatever a call
cost, ~2,000 compute units a second against a free plan of 150-300.
"""
from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from app import config
from app.api_budget import budget_stats
from app.nodereal_client import NoderealClient, NoderealError
from app.tron_client import TronClient, TronError
from app.tron_tags import TronScanTags

EVM = "0x" + "1" * 40
TRON = "TSFFxCbDLh6nP1x4BcyqkbEFJyx3zSGY2r"
KEY = "SECRETKEYQWERTYUIOPASDFGHJKLZXCVBN"


def _rpc(answer=None):
    def handler(request):
        body = json.loads(request.content)
        if answer is not None:
            return httpx.Response(200, json=answer)
        if body["method"] == "nr_getAssetTransfers":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"transfers": []}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x10"})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _transfers(client):
    client._rpc("nr_getAssetTransfers", [{"fromBlock": "0x1", "toBlock": "0x2"}])


def test_two_nodereal_clients_on_one_key_share_the_compute_unit_spacing(monkeypatch):
    monkeypatch.setattr(config, "NODEREAL_CUPS_FLOOR", 5000)  # 0.05 s per 250-CU call
    monkeypatch.setattr(config, "NODEREAL_CUPS", 5000)
    clients = [NoderealClient(api_key=KEY, client=_rpc()) for _ in range(2)]

    def work(client):
        for _ in range(3):
            _transfers(client)
    threads = [threading.Thread(target=work, args=(c,)) for c in clients for _ in range(2)]
    start = time.monotonic()
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert time.monotonic() - start >= 0.05 * 11 * 0.95  # 12 calls in single file


def test_a_cheap_call_waits_less_than_a_transfer_read(monkeypatch):
    monkeypatch.setattr(config, "NODEREAL_CUPS_FLOOR", 2500)  # 0.1 s per transfer read
    monkeypatch.setattr(config, "NODEREAL_CUPS", 2500)
    client = NoderealClient(api_key=KEY, client=_rpc())
    start = time.monotonic()
    for _ in range(10):
        client._rpc("eth_blockNumber", [])  # 5 CU each
    assert time.monotonic() - start < 0.2  # 10 transfer reads would take ~0.9 s


def test_the_default_nodereal_pace_respects_the_free_plan():
    client = NoderealClient(api_key=KEY, client=_rpc())
    interval = client._pacer.interval
    assert interval == pytest.approx(250 / config.NODEREAL_CUPS_FLOOR)
    assert 250 / interval <= 300  # never more than the plan's compute units per second


def test_a_nodereal_rate_limit_slows_every_trace_on_the_key(monkeypatch):
    monkeypatch.setattr("app.nodereal_client.time.sleep", lambda s: None)
    client = NoderealClient(api_key=KEY, min_interval=0.01, max_retries=1, client=_rpc(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "too many requests"}}))
    other = NoderealClient(api_key=KEY, min_interval=0.01, client=_rpc())
    before = other._pacer.interval
    with pytest.raises(NoderealError):
        client._rpc("eth_blockNumber", [])
    assert other._pacer.interval > before


def test_keyless_tron_clients_share_one_pace():
    def handler(request):
        return httpx.Response(200, json={"data": [], "meta": {}})
    clients = [TronClient(api_key="", min_interval=0.05, client=httpx.Client(transport=httpx.MockTransport(handler)))
               for _ in range(4)]
    threads = [threading.Thread(target=c.get_outgoing_transactions, args=(TRON,)) for c in clients for _ in range(2)]
    start = time.monotonic()
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert time.monotonic() - start >= 0.05 * 7 * 0.95


def test_a_trongrid_refusal_widens_the_shared_pace(monkeypatch):
    monkeypatch.setattr("app.tron_client.time.sleep", lambda s: None)
    client = TronClient(api_key=KEY, min_interval=0.01, max_retries=1,
                        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))))
    before = client._pacer.interval
    with pytest.raises(TronError):
        client.get_outgoing_transactions(TRON)
    assert client._pacer.interval > before


def test_tronscan_tag_readers_share_one_pace():
    a = TronScanTags(KEY, client=_rpc(), min_interval=0.05)
    b = TronScanTags(KEY, client=_rpc(), min_interval=0.05)
    assert a._pacer is b._pacer


def test_the_shared_scopes_are_listed_without_the_key():
    NoderealClient(api_key=KEY, client=_rpc())
    TronClient(api_key=KEY, client=_rpc())
    TronClient(api_key="", client=_rpc())
    TronScanTags(KEY, client=_rpc())
    names = list(budget_stats()["pacers"])
    for prefix in ("nodereal:", "trongrid:", "trongrid:anon", "tronscan:"):
        assert any(n.startswith(prefix) for n in names), prefix
    joined = " ".join(names)
    for start in range(len(KEY) - 3):
        assert KEY[start:start + 4] not in joined
