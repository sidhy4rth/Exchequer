"""Answers about the chain's tip are not served for a day (r1-providers-4).

The cache's safety argument -- history is append-only, so a cached answer can
only lag -- is exactly the harm for the questions a trace asks: the newest
page of a wallet, "no transactions found", a `latest` balance. Served for 24
hours, a re-trace after the scammer moved the money replayed "sent nothing",
and the report stated a balance that had since been swept.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

import httpx
import pytest

from app import config, pipeline
from app.api_budget import ResponseCache
from app.deposit_inference import describe
from app.etherscan_client import EtherscanClient
from app.exchange_matcher import ExchangeMatch
from app.pipeline import TraceRequest, run_trace

WALLET = "0x" + "1" * 40
EXIT = "0x" + "2" * 40


class Chain:
    """A fake Etherscan whose state can change between traces."""

    def __init__(self):
        self.rows: list[dict] = []
        self.balance = 5 * 10**18
        self.calls: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append(params)
        if params.get("action") == "balance":
            return httpx.Response(200, json={"status": "1", "message": "OK", "result": str(self.balance)})
        lo = int(params.get("startblock", 0))
        hi = int(params.get("endblock", 10**12))
        rows = [r for r in self.rows if lo <= int(r["blockNumber"]) <= hi]
        if not rows:
            return httpx.Response(200, json={"status": "0", "message": "No transactions found", "result": []})
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})

    def client(self) -> EtherscanClient:
        return EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, include_internal=False,
                               client=httpx.Client(transport=httpx.MockTransport(self.handler)))


def test_a_re_trace_after_the_money_moved_sees_the_new_outflow(monkeypatch):
    chain = Chain()

    @contextmanager
    def open_source(c, asset):
        client = chain.client()
        yield client
        client.close()
    monkeypatch.setattr(pipeline, "open_source", open_source)
    monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
    first = run_trace(TraceRequest(address=WALLET, chain="ethereum", follow_swaps=False))
    assert first["message"] and "sent no" in first["message"]
    chain.rows.append({"hash": "0xsweep", "from": WALLET, "to": EXIT, "value": str(10**18),
                       "timeStamp": "1700000000", "blockNumber": "100", "isError": "0"})
    second = run_trace(TraceRequest(address=WALLET, chain="ethereum", follow_swaps=False))
    assert EXIT in {n["id"] if isinstance(n, dict) and "id" in n else n.get("address")
                    for n in second["graph"]["nodes"]}


def test_a_balance_is_read_from_the_chain_every_time():
    chain = Chain()
    client = chain.client()
    assert client.get_balance_native(WALLET) == 5.0
    chain.balance = 0
    assert chain.client().get_balance_native(WALLET) == 0.0
    assert sum(1 for c in chain.calls if c.get("action") == "balance") == 2


def test_an_open_ended_empty_page_is_asked_again_after_minutes(monkeypatch):
    monkeypatch.setattr(config, "API_CACHE_OPEN_TTL_SECONDS", 0.05)
    chain = Chain()
    chain.client().get_transactions(WALLET)
    chain.client().get_transactions(WALLET)
    assert len(chain.calls) == 1  # still a cache within the window
    time.sleep(0.08)
    chain.client().get_transactions(WALLET)
    assert len(chain.calls) == 2


def test_a_closed_block_range_keeps_for_the_day(monkeypatch):
    monkeypatch.setattr(config, "API_CACHE_OPEN_TTL_SECONDS", 0.01)
    chain = Chain()
    chain.client().get_incoming_between(WALLET, 10, 20, 0, 0)
    time.sleep(0.03)
    chain.client().get_incoming_between(WALLET, 10, 20, 0, 0)
    assert len(chain.calls) == 1


def test_importer_reads_of_latest_state_are_never_cached():
    chain = Chain()

    def handler(request):
        chain.calls.append(dict(request.url.params))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": []})
    for _ in range(2):
        client = EtherscanClient(api_key="k", chain_id=1, min_interval=0.0,
                                 client=httpx.Client(transport=httpx.MockTransport(handler)))
        client._request({"module": "logs", "action": "getLogs", "fromBlock": 0, "toBlock": "latest"})
        client._request({"module": "proxy", "action": "eth_call", "to": WALLET, "data": "0x", "tag": "latest"})
    assert len(chain.calls) == 4


def test_a_zero_ttl_stores_nothing_and_clears_an_older_answer(tmp_path):
    cache = ResponseCache(path=tmp_path / "c.db")
    cache.put("k", 1)
    cache.put("k", 2, ttl=0)
    assert cache.get("k") == (False, None)
    assert cache.stats()["entries_on_disk"] == 0
    cache.close()


def test_a_short_ttl_survives_a_restart_as_short(tmp_path):
    path = tmp_path / "c.db"
    first = ResponseCache(ttl_seconds=3600, path=path)
    first.put("open", [1], ttl=0.05)
    first.put("closed", [2])
    first.close()
    second = ResponseCache(ttl_seconds=3600, path=path)
    time.sleep(0.08)
    assert second.get("open") == (False, None)
    assert second.get("closed") == (True, [2])
    second.close()


def test_a_cache_file_from_before_per_entry_ttls_starts_again(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE responses (key TEXT PRIMARY KEY, stored_at REAL NOT NULL, value TEXT NOT NULL, meta TEXT)")
    db.execute("INSERT INTO responses VALUES ('\"k\"', ?, '[1]', NULL)", (time.time(),))
    db.commit()
    db.close()
    cache = ResponseCache(ttl_seconds=3600, path=path)
    assert cache.get("k") == (False, None)
    cache.close()


def test_the_inference_states_when_the_balance_was_read():
    match = ExchangeMatch(address=WALLET, exchange="Binance", label="probable", wallet_type="inferred_deposit",
                          depth=1, value_received_native=1.0,
                          evidence={"current_balance_native": 0.5, "current_balance_symbol": "ETH",
                                    "current_balance_at": "2026-11-06T10:00:00Z", "sweep_count": 2})
    text = describe(match, "ETH")
    assert "balance was 0.5000 ETH when read at 2026-11-06 10:00:00 UTC" in text
    assert "current balance" not in text


def test_the_tether_log_pager_never_asks_for_the_same_page_for_ever():
    from scripts import import_tether_freezes as tether

    class Stuck:
        calls = 0

        def _request(self, params):
            Stuck.calls += 1
            if Stuck.calls > 3:  # fail, rather than hang, if the guard is ever lost
                raise AssertionError("the same page was asked for again and again")
            return [{"blockNumber": hex(params["fromBlock"]), "logIndex": hex(i), "data": "0x" + "0" * 64,
                     "transactionHash": f"0x{i:x}", "timeStamp": "0x1"} for i in range(1000)]
    with pytest.raises(RuntimeError):
        tether.eth_events(Stuck(), tether.ADDED)
