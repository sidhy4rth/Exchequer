"""NodeReal pagination is bounded by records read, not records kept.

Same failure class as the Tron client: a wallet whose recent history is all
zero-value or reverted transfers would otherwise be paged through in full,
because only kept transfers count against the cap.
"""

import json

import httpx

from app import config
from app.nodereal_client import MAX_COUNT, MAX_SCAN, NoderealClient

ADDRESS = "0x" + "ab" * 20
OTHER = "0x" + "cd" * 20
HEAD = 50_000_000


def _record(i: int, value_hex: str) -> dict:
    return {"hash": f"0x{i:x}", "from": ADDRESS, "to": OTHER, "value": value_hex,
            "decimal": 18, "blockNum": hex(HEAD - i), "blockTimeStamp": 1_700_000_000,
            "asset": "BNB", "receiptsStatus": 1}


class _Rpc:
    """Answers eth_blockNumber and serves `records` in pages of maxCount."""

    def __init__(self, records: list[dict], endless: bool) -> None:
        self.records = records
        self.endless = endless
        self.transfer_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(HEAD)})
        self.transfer_calls += 1
        params = body["params"][0]
        lo, hi = int(params["fromBlock"], 16), int(params["toBlock"], 16)
        in_window = [r for r in self.records if lo <= int(r["blockNum"], 16) <= hi]
        count = int(params["maxCount"], 16)
        start = int(params.get("pageKey") or 0)
        page = in_window[start:start + count]
        result = {"transfers": page}
        if page and (self.endless or start + count < len(in_window)):
            result["pageKey"] = str(start + count)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def _client(rpc: _Rpc) -> NoderealClient:
    http = httpx.Client(transport=httpx.MockTransport(rpc.handler))
    return NoderealClient(api_key="k", client=http, min_interval=0)


def test_zero_value_spam_stops_after_max_scan():
    rpc = _Rpc([_record(i, "0x0") for i in range(MAX_SCAN * 3)], endless=True)
    txs = _client(rpc).get_outgoing_transactions(ADDRESS)
    assert txs == []
    page = min(MAX_COUNT, config.TRACE_MAX_TXS_PER_ADDRESS)
    assert rpc.transfer_calls == -(-MAX_SCAN // page)


def test_short_history_is_returned_whole():
    records = [_record(i, "0x0") for i in range(30)] + [_record(100 + i, "0xde0b6b3a7640000") for i in range(5)]
    rpc = _Rpc(records, endless=False)
    txs = _client(rpc).get_outgoing_transactions(ADDRESS)
    assert len(txs) == 5
    assert all(t.value_wei > 0 for t in txs)
