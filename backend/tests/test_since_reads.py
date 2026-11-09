"""The forward read a watch uses (read_outgoing_since), per provider.

Ascending from the cursor, every record read counting toward `through`
whatever its direction or value, and never the trace's nonce search
(r2-g2-watchlist-alerts-0-0). The real clients over httpx.MockTransport.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.etherscan_client import EtherscanClient, split_page
from app.nodereal_client import NoderealClient, NoderealError
from app.tron_client import TronClient

W = "0x" + "7" * 40
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"


def test_a_page_split_keeps_its_last_block_for_the_next_read():
    assert split_page([5, 6, 7], after=4, full=False) == (7, True)
    assert split_page([], after=4, full=False) == (4, True)
    assert split_page([5, 6, 7], after=4, full=True) == (6, False)
    assert split_page([9, 9, 9], after=4, full=True) == (9, False)  # one block: never stall


def test_a_contract_wallets_internal_sends_are_read_forward_too():
    seen = []

    def handler(request):
        q = dict(request.url.params)
        seen.append(q)
        if q["action"] == "txlistinternal":
            row = {"blockNumber": "120", "timeStamp": "1800000120", "from": W, "to": BINANCE_14,
                   "value": str(10**18), "isError": "0", "hash": "0xint"}
            return httpx.Response(200, json={"status": "1", "message": "OK", "result": [row]})
        return httpx.Response(200, json={"status": "0", "message": "No transactions found", "result": []})
    client = EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, include_internal=True,
                             client=httpx.Client(transport=httpx.MockTransport(handler)))
    read = client.read_outgoing_since(W, after=100, limit=50)
    assert [t.hash for t in read.transfers] == ["0xint"] and read.through == 120 and read.complete
    assert [q["action"] for q in seen] == ["txlist", "txlistinternal"]
    assert all(q["sort"] == "asc" and q["startblock"] == "101" for q in seen)


class NodeRpc:
    """nr_getAssetTransfers over `records`, paged by pageKey as NodeReal does.
    Blocks above `indexed` are "not reached"; `answer` replaces every result."""

    def __init__(self, records, head=1_000_000, indexed=None, answer=...):
        self.records, self.methods, self.params, self.head = records, [], [], head
        self.indexed, self.answer = indexed, answer

    def handler(self, request):
        body = json.loads(request.content)
        self.methods.append(body["method"])
        if body["method"] == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(self.head + 32)})
        p = body["params"][0]
        self.params.append(p)
        if self.answer is not ...:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": self.answer})
        lo, hi = int(p["fromBlock"], 16), int(p["toBlock"], 16)
        if self.indexed is not None and hi > self.indexed:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                             "error": {"code": -32000, "message": "toBlock not reached"}})
        rows = [r for r in self.records if lo <= int(r["blockNum"], 16) <= hi]
        start, n = int(p.get("pageKey") or 0), int(p["maxCount"], 16)
        result = {"transfers": rows[start:start + n]}
        if start + n < len(rows):
            result["pageKey"] = str(start + n)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def nr_record(tx_hash, to, value, block):
    return {"hash": tx_hash, "from": W, "to": to, "value": hex(value), "decimal": 18, "blockNum": hex(block),
            "blockTimeStamp": 1_800_000_000, "asset": "BNB", "receiptsStatus": 1}


def nodereal(rpc):
    return NoderealClient(api_key="k", client=httpx.Client(transport=httpx.MockTransport(rpc.handler)),
                          min_interval=0, max_retries=0)


def test_a_nodereal_watch_read_walks_forward_and_never_searches_nonces():
    sent = {"hash": "0x1", "from": W, "to": BINANCE_14, "value": hex(10**18), "decimal": 18,
            "blockNum": hex(950_000), "blockTimeStamp": 1_800_000_000, "asset": "BNB", "receiptsStatus": 1}
    rpc = NodeRpc([sent])
    client = NoderealClient(api_key="k", client=httpx.Client(transport=httpx.MockTransport(rpc.handler)),
                            min_interval=0)
    read = client.read_outgoing_since(W, after=900_000, limit=50)
    assert [t.hash for t in read.transfers] == ["0x1"] and read.complete and read.through == 1_000_000
    assert "eth_getTransactionCount" not in rpc.methods
    assert rpc.params[0]["order"] == "asc" and int(rpc.params[0]["fromBlock"], 16) == 900_001


def test_a_nodereal_read_far_behind_stops_after_its_windows_and_says_so():
    rpc = NodeRpc([], head=5_000_000)
    client = NoderealClient(api_key="k", client=httpx.Client(transport=httpx.MockTransport(rpc.handler)),
                            min_interval=0)
    read = client.read_outgoing_since(W, after=0, limit=50)
    assert not read.complete and read.through == 1_000_000 and len(rpc.params) == 10


def test_a_tron_watch_read_asks_for_confirmed_records_from_the_cursor_up():
    tron_w = "TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G"
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        row = {"transaction_id": "ab" * 32, "from": tron_w, "to": "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7",
               "value": "5000000", "block_timestamp": 1_800_000_500_000, "type": "Transfer",
               "token_info": {"address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "decimals": 6, "symbol": "USDT"}}
        return httpx.Response(200, content=json.dumps({"data": [row], "meta": {}}))
    client = TronClient(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)),
                        min_interval=0, contract_address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", asset_symbol="USDT")
    read = client.read_outgoing_since(tron_w, after=1_800_000_000, limit=50)
    assert len(read.transfers) == 1 and read.through == 1_800_000_500 and read.complete
    q = seen[0]
    assert q["only_confirmed"] == "true" and q["order_by"] == "block_timestamp,asc"
    assert q["min_timestamp"] == str(1_800_000_001 * 1000) and q["only_from"] == "true"


def test_a_nodereal_block_that_fills_a_page_on_its_own_is_read_whole():
    # Fifty zero-value sends and the cash-out in one block: the first page is
    # that block alone, and the cash-out is on the next page of it.
    dust = [nr_record(f"0x{i:064x}", "0x" + "9" * 40, 0, 950_000) for i in range(50)]
    rpc = NodeRpc([*dust, nr_record("0xcash", BINANCE_14, 10**18, 950_000)])
    read = nodereal(rpc).read_outgoing_since(W, after=900_000, limit=50)
    assert [t.hash for t in read.transfers] == ["0xcash"]
    assert read.through == 950_000 and not read.complete


def test_a_nodereal_answer_without_a_transfer_list_is_a_failed_read_not_an_empty_one():
    # A null result read as "nothing in these 100k blocks" moved the cursor
    # over them; the cursor must stay where it was, so the read fails.
    rpc = NodeRpc([], answer=None)
    with pytest.raises(NoderealError):
        nodereal(rpc).read_outgoing_since(W, after=900_000, limit=50)


def test_a_nodereal_index_further_behind_than_its_margin_steps_back_instead_of_failing():
    rpc = NodeRpc([nr_record("0x1", BINANCE_14, 10**18, 999_000)], indexed=999_800)
    read = nodereal(rpc).read_outgoing_since(W, after=990_000, limit=50)
    assert [t.hash for t in read.transfers] == ["0x1"]
    assert 999_000 <= read.through <= 999_800


def test_a_tron_second_that_fills_the_read_on_its_own_is_read_whole():
    # Fifty dust sends and the cash-out in one block (one second): the read
    # used to stop at fifty sends and count that second as read.
    tron_w = "TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G"
    usdt = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

    def row(n, value):
        return {"transaction_id": f"{n:064x}", "from": tron_w, "to": "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7",
                "value": str(value), "block_timestamp": 1_800_000_500_000, "type": "Transfer",
                "token_info": {"address": usdt, "decimals": 6, "symbol": "USDT"}}
    rows = [row(n, 1) for n in range(50)] + [row(99, 25_000 * 10**6)]

    def handler(request):
        q = dict(request.url.params)
        start, n = int(q.get("fingerprint") or 0), int(q["limit"])
        meta = {"fingerprint": str(start + n)} if start + n < len(rows) else {}
        return httpx.Response(200, content=json.dumps({"data": rows[start:start + n], "meta": meta}))
    client = TronClient(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)),
                        min_interval=0, contract_address=usdt, asset_symbol="USDT")
    read = client.read_outgoing_since(tron_w, after=1_800_000_000, limit=50)
    assert f"{99:064x}" in [t.hash for t in read.transfers] and len(read.transfers) == 51
    assert read.through == 1_800_000_500


def test_a_nodereal_page_that_offers_more_but_holds_nothing_is_a_failed_read():
    # Read as "this window is done" it moved the cursor over 100k blocks.
    rpc = NodeRpc([], answer={"transfers": [], "pageKey": "next"})
    with pytest.raises(NoderealError):
        nodereal(rpc).read_outgoing_since(W, after=900_000, limit=50)


def test_a_nodereal_block_too_full_to_read_whole_is_reported_cut(monkeypatch):
    from app import nodereal_client
    monkeypatch.setattr(nodereal_client, "MAX_PAGES_PER_WINDOW", 1)
    monkeypatch.setattr(nodereal_client, "MAX_COUNT", 60)
    rpc = NodeRpc([nr_record(f"0x{i:064x}", "0x" + "9" * 40, 1, 950_000) for i in range(130)])
    read = nodereal(rpc).read_outgoing_since(W, after=900_000, limit=50)
    assert read.through == 950_000 and read.cut == 950_000 and not read.complete


def test_a_tron_second_too_full_to_read_whole_is_reported_cut(monkeypatch):
    from app import tron_client
    monkeypatch.setattr(tron_client, "MAX_SCAN", 100)
    tron_w = "TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G"
    usdt = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    rows = [{"transaction_id": f"{n:064x}", "from": tron_w, "to": "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7",
             "value": "0", "block_timestamp": 1_800_000_500_000, "type": "Transfer",
             "token_info": {"address": usdt, "decimals": 6, "symbol": "USDT"}} for n in range(150)]

    def handler(request):
        q = dict(request.url.params)
        start, n = int(q.get("fingerprint") or 0), int(q["limit"])
        meta = {"fingerprint": str(start + n)} if start + n < len(rows) else {}
        return httpx.Response(200, content=json.dumps({"data": rows[start:start + n], "meta": meta}))
    client = TronClient(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)),
                        min_interval=0, contract_address=usdt, asset_symbol="USDT")
    read = client.read_outgoing_since(tron_w, after=1_800_000_000, limit=50)
    assert read.through == 1_800_000_500 and read.cut == 1_800_000_500
