"""Reads rest on confirmed blocks only (r2-g2-watchlist-alerts-0-10).

Etherscan reads ran to the newest indexed block and TronGrid could return
records from blocks not yet solidified. A watch alerted on such a transfer and
moved its cursor past it; if a reorg dropped it and a replacement landed at the
same or a lower block, the alert named a transaction that never settled and
the replacement was never alerted. Every EVM read now drops rows above the
head less the chain's confirmation depth; Tron asks for confirmed records; and
NodeReal never asks past its indexed head (the tip less 32).
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import httpx
import pytest
from sqlalchemy import create_engine

from app import config, etherscan_client, models, ownership, pipeline, watchlist
from app.chain_data import open_source
from app.etherscan_client import ENDBLOCK_LATEST, EtherscanClient
from app.nodereal_client import NoderealClient
from app.pipeline import TraceRequest, run_trace
from app.tron_client import TronClient

WALLET = "0x" + "1" * 40
EXIT = "0x" + "2" * 40
TRON = "TSFFxCbDLh6nP1x4BcyqkbEFJyx3zSGY2r"


@pytest.fixture(autouse=True)
def _no_head_memo():
    etherscan_client._confirmed_heads.clear()
    yield
    etherscan_client._confirmed_heads.clear()


def _row(block: int, sender: str = WALLET, to: str = EXIT) -> dict:
    return {"hash": f"0x{block:064x}", "from": sender, "to": to, "value": str(10**18),
            "timeStamp": str(1_700_000_000 + block), "blockNumber": str(block), "isError": "0"}


class Chain:
    def __init__(self, head: int, rows: list[dict]) -> None:
        self.head = head
        self.rows = rows
        self.calls: list[dict] = []
        self.head_fails = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append(params)
        if params.get("action") == "eth_blockNumber":
            if self.head_fails:
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"message": "busy"}})
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(self.head)})
        lo, hi = int(params.get("startblock", 0)), int(params.get("endblock", 10**12))
        rows = [r for r in self.rows if lo <= int(r["blockNumber"]) <= hi]
        if not rows:
            return httpx.Response(200, json={"status": "0", "message": "No transactions found", "result": []})
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})

    def client(self, confirmations: int | None = 12) -> EtherscanClient:
        return EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, include_internal=False,
                               confirmations=confirmations,
                               client=httpx.Client(transport=httpx.MockTransport(self.handler)))


def test_rows_above_head_minus_confirmations_are_dropped():
    chain = Chain(100, [_row(95), _row(88), _row(87, sender=EXIT, to=WALLET)])
    client = chain.client()
    assert [t.block_number for t in client.get_outgoing_transactions(WALLET)] == [88]
    assert [t.block_number for t in client.get_outgoing_transactions_since(WALLET, 1)] == [88]
    incoming, outgoing, _ = client.get_flows_between(WALLET, 1, 200, 0, 0)
    assert [t.block_number for t in outgoing] == [88] and [t.block_number for t in incoming] == [87]
    assert client.confirmed_bound_applied is True
    # One head read for the client, however many reads use it.
    assert sum(1 for c in chain.calls if c.get("action") == "eth_blockNumber") == 1


def test_a_client_without_a_depth_reads_to_the_tip():
    chain = Chain(100, [_row(95), _row(88)])
    assert [t.block_number for t in chain.client(None).get_outgoing_transactions(WALLET)] == [95, 88]
    assert not any(c.get("action") == "eth_blockNumber" for c in chain.calls)


def test_the_head_is_read_fresh_not_from_the_cache(monkeypatch):
    chain = Chain(100, [_row(95)])
    chain.client().get_outgoing_transactions(WALLET)
    chain.client().get_outgoing_transactions(WALLET)  # inside the memo: shared
    assert sum(1 for c in chain.calls if c.get("action") == "eth_blockNumber") == 1
    monkeypatch.setattr(etherscan_client, "HEAD_MEMO_SECONDS", 0.0)
    chain.head = 120
    later = chain.client()
    assert [t.block_number for t in later.get_outgoing_transactions(WALLET)] == [95]
    assert sum(1 for c in chain.calls if c.get("action") == "eth_blockNumber") == 2


def test_a_failed_head_read_keeps_rows_and_says_so(monkeypatch):
    chain = Chain(100, [_row(95), _row(88)])
    chain.head_fails = True
    client = chain.client()
    assert [t.block_number for t in client.get_outgoing_transactions(WALLET)] == [95, 88]
    assert client.confirmed_bound_applied is False

    @contextmanager
    def source(c, asset):
        yield chain.client()
    monkeypatch.setattr(pipeline, "open_source", source)
    monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
    result = run_trace(TraceRequest(address=WALLET, chain="ethereum", follow_swaps=False, max_depth=1))
    assert any("unconfirmed" in w for w in result["warnings"])


def test_the_endblock_in_the_request_does_not_move():
    chain = Chain(100, [_row(95)])
    chain.client().get_transactions(WALLET)
    chain.head = 200
    etherscan_client._confirmed_heads.clear()
    chain.client().get_transactions(WALLET)
    lists = [c for c in chain.calls if c.get("action") == "txlist"]
    assert lists[0]["endblock"] == str(ENDBLOCK_LATEST)
    assert len(lists) == 1  # the same request, so the second read was the cache's


def test_each_chain_is_opened_with_its_depth(monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", "k")
    depths = {}
    for key in ("ethereum", "polygon", "arbitrum"):
        with open_source(config.get_chain(key), None) as client:
            depths[key] = client.confirmations
    assert depths == {"ethereum": 12, "polygon": 64, "arbitrum": 20}
    assert config.get_chain("bsc").confirmations == 32  # NodeReal's indexed head lag


def test_nodereal_never_reads_past_tip_minus_32():
    tip = 50_000_000
    asked = []

    def handler(request):
        body = json.loads(request.content)
        if body["method"] == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(tip)})
        asked.append(int(body["params"][0]["toBlock"], 16))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"transfers": []}})
    client = NoderealClient(api_key="k", min_interval=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.get_outgoing_transactions(WALLET)
    client.get_incoming_transactions(WALLET)
    assert asked and max(asked) <= tip - config.get_chain("bsc").confirmations


def test_every_trongrid_read_asks_for_confirmed_rows_on_every_page():
    seen = []

    def handler(request):
        params = dict(request.url.params)
        seen.append(params)
        start = int(params.get("fingerprint") or 0)
        meta = {"fingerprint": str(start + 1)} if start < 2 else {}
        row = {"txID": f"t{start}", "block_timestamp": 1_700_000_000_000, "raw_data": {"contract": [
            {"type": "TriggerSmartContract", "parameter": {"value": {}}}]}}
        return httpx.Response(200, content=json.dumps({"data": [row], "meta": meta}))
    tron = TronClient(api_key="k", min_interval=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    tron.get_outgoing_transactions(TRON)
    tron.get_outgoing_transactions_since_time(TRON, 1_600_000_000)
    tron.get_flows_between(TRON, 0, 0, 1_600_000_000, 1_650_000_000)
    assert any("fingerprint" in p for p in seen)
    assert len(seen) >= 12 and all(p.get("only_confirmed") == "true" for p in seen)


def test_an_unconfirmed_transfer_is_alerted_only_once_confirmed(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'w.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    monkeypatch.setattr(etherscan_client, "HEAD_MEMO_SECONDS", 0.0)
    chain = Chain(100, [_row(50)])

    @contextmanager
    def source(c, asset):
        client = chain.client()
        yield client
        client.close()
    watch = watchlist.create_watch(ownership.owner_hash("a" * 32), WALLET, "ethereum", "ETH")
    assert watchlist.check_watch(watch.id, source=source) == []  # the baseline, at block 50
    chain.rows.append(_row(95))  # mined, but 5 deep of the 12 asked for
    assert watchlist.check_watch(watch.id, source=source) == []
    with models.session() as s:
        assert s.get(models.Watch, watch.id).last_seen_block <= 88
    chain.head = 110
    alerts = watchlist.check_watch(watch.id, source=source)
    assert len(alerts) == 1 and alerts[0]["tx_hash"] == f"0x{95:064x}"


def test_a_watch_whose_head_read_fails_neither_alerts_nor_moves(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'w.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    monkeypatch.setattr(etherscan_client, "HEAD_MEMO_SECONDS", 0.0)
    chain = Chain(100, [_row(50)])

    @contextmanager
    def source(c, asset):
        client = chain.client()
        yield client
        client.close()
    watch = watchlist.create_watch(ownership.owner_hash("b" * 32), WALLET, "ethereum", "ETH")
    assert watchlist.check_watch(watch.id, source=source) == []  # the baseline, at block 50
    chain.rows.append(_row(99))  # one block deep
    chain.head_fails = True
    assert watchlist.check_watch(watch.id, source=source) == []
    with models.session() as s:
        stored = s.get(models.Watch, watch.id)
        assert stored.last_seen_block == 50 and "newest block" in (stored.last_error or "")
    chain.head_fails = False
    chain.head = 111
    alerts = watchlist.check_watch(watch.id, source=source)
    assert len(alerts) == 1 and alerts[0]["tx_hash"] == f"0x{99:064x}"
