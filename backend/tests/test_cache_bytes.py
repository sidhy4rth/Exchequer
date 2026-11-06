"""Provider bodies and the response cache are bounded in bytes (r1-providers-1).

The cache kept every field of every record (calldata included), counted only
entries (2,048 of them, ~0.7 GB on a 512 MB instance), and no client capped a
response: one 200-record page with large calldata was 52 MB, held for a day.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time

import httpx
import pytest

from app.api_budget import ResponseCache, read_capped
from app.etherscan_client import EtherscanClient, EtherscanError
from app.nodereal_client import NoderealClient, NoderealError
from app.tron_client import TronClient, TronError
from app.tron_tags import TronScanTags

WALLET = "0x" + "1" * 40


def _page(records: int, input_chars: int) -> bytes:
    rows = [{"blockNumber": str(100 + i), "timeStamp": "1700000000", "hash": f"0x{i:064x}",
             "nonce": "1", "blockHash": "0x" + "b" * 64, "transactionIndex": "1", "from": WALLET,
             "to": "0x" + "2" * 40, "value": "1000", "gas": "21000", "gasPrice": "1", "isError": "0",
             "txreceipt_status": "1", "input": "0x" + "ab" * (input_chars // 2), "contractAddress": "",
             "cumulativeGasUsed": "1", "gasUsed": "1", "confirmations": "1", "methodId": "0x",
             "functionName": ""} for i in range(records)]
    return json.dumps({"status": "1", "message": "OK", "result": rows}).encode()


def _etherscan(handler) -> EtherscanClient:
    return EtherscanClient(api_key="k", chain_id=137, min_interval=0.0, include_internal=False,
                           client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_a_page_with_heavy_calldata_is_cached_as_the_fields_the_parsers_read():
    body = _page(200, 30_000)  # 6 MB, under the 8 MB cap
    client = _etherscan(lambda r: httpx.Response(200, content=body))
    txs = client.get_transactions(WALLET)
    assert len(txs) == 200
    cache = client._cache
    assert cache.stats()["bytes"] < 100_000  # a 6 MB page, cached as ~40 kB
    record = client.evidence.records[0]
    assert record.sha256 == hashlib.sha256(body).hexdigest() and record.bytes == len(body)
    hit, cached = cache.get(next(iter(cache._entries)))
    assert hit and "input" not in cached[0] and set(cached[0]) <= {
        "hash", "from", "to", "value", "timeStamp", "blockNumber", "isError", "contractAddress",
        "tokenDecimal", "tokenSymbol"}


@pytest.mark.parametrize("stated", [True, False])
def test_an_oversized_etherscan_body_is_refused_and_not_cached(monkeypatch, stated):
    from app import config
    monkeypatch.setattr(config, "PROVIDER_MAX_RESPONSE_BYTES", 1_000_000)
    body = _page(200, 9_000)  # ~2 MB

    def handler(request):
        if stated:
            return httpx.Response(200, content=body)
        return httpx.Response(200, content=iter([body[i:i + 65536] for i in range(0, len(body), 65536)]))
    client = _etherscan(handler)
    with pytest.raises(EtherscanError):
        client.get_transactions(WALLET)
    assert client._cache.stats()["entries"] == 0


def test_oversized_bodies_are_refused_by_every_client(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "PROVIDER_MAX_RESPONSE_BYTES", 10_000)
    big = httpx.MockTransport(lambda r: httpx.Response(200, content=b"[" + b"0," * 20_000 + b"0]"))
    with pytest.raises(NoderealError):
        NoderealClient(api_key="k", min_interval=0, max_retries=0, client=httpx.Client(transport=big)).head_block()
    with pytest.raises(TronError):
        TronClient(api_key="k", min_interval=0, max_retries=0,
                   client=httpx.Client(transport=big)).get_outgoing_transactions("TSFFxCbDLh6nP1x4BcyqkbEFJyx3zSGY2r")
    tags = TronScanTags("k", client=httpx.Client(transport=big), min_interval=0)
    assert tags.account("TSFFxCbDLh6nP1x4BcyqkbEFJyx3zSGY2r") is None and tags.failures == 1


def test_a_capped_read_still_reads_json_and_text():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"a": 1})))
    response = read_capped(client, "GET", "https://example.test/x", max_bytes=100)
    assert response.json() == {"a": 1} and response.status_code == 200 and response.text == '{"a":1}'


def test_the_memory_layer_never_exceeds_its_byte_budget():
    cache = ResponseCache(max_bytes=1_000_000, max_entries=10_000)
    blob = "x" * 100_000
    for i in range(50):
        cache.put(i, blob)
        assert cache.stats()["bytes"] <= 1_000_000
    assert cache.get(0) == (False, None)  # the oldest went first
    assert cache.get(49) == (True, blob)


def test_the_disk_layer_never_exceeds_its_byte_budget(tmp_path):
    import sqlite3

    path = tmp_path / "cache.db"
    cache = ResponseCache(path=path, max_bytes=10_000_000, max_disk_bytes=1_000_000)
    for i in range(30):
        cache.put(("k", i), "y" * 100_000)
    total = sqlite3.connect(path).execute("SELECT SUM(LENGTH(value)) FROM responses").fetchone()[0]
    assert total <= 1_000_000
    assert cache.get(("k", 29))[0] is True
    cache.close()


def test_a_slow_disk_write_does_not_stall_other_lookups(tmp_path):
    cache = ResponseCache(path=tmp_path / "cache.db")
    cache.put("warm", 1)
    real = cache._db

    class Slow:
        def __getattr__(self, name):
            return getattr(real, name)

        def commit(self):
            time.sleep(0.4)
            real.commit()
    cache._db = Slow()
    writer = threading.Thread(target=cache.put, args=("big", "z" * 1_000_000))
    writer.start()
    time.sleep(0.05)
    start = time.monotonic()
    assert cache.get("warm") == (True, 1)
    assert time.monotonic() - start < 0.05
    writer.join()
    cache._db = real
    cache.close()


def test_a_cached_value_cannot_be_changed_by_the_caller_who_read_it():
    cache = ResponseCache()
    cache.put("k", [{"a": 1}])
    cache.get("k")[1][0]["a"] = 2
    assert cache.get("k") == (True, [{"a": 1}])
