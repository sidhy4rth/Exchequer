"""TronGrid answers are cached like the other providers' (r1-providers-3).

Every re-trace of a Tron address, both directions and every follow-on read
TronGrid again, at 1.2 s a request without a key. A read is now cached whole
-- every page it took, under its first request -- so a cached first page is
never followed by a live page whose fingerprint came from another read.
"""
from __future__ import annotations

import json
import time

import httpx

from app import api_budget, config
from app.tron_client import MAX_PAGE, TronClient, _slim_native, _slim_trc20

ADDRESS = "TSFFxCbDLh6nP1x4BcyqkbEFJyx3zSGY2r"
OWNER_HEX = "41" + "11" * 20
TO_HEX = "41" + "22" * 20
USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def _native(i: int, kind: str = "TransferContract") -> dict:
    return {"txID": f"tx{i}", "block_timestamp": 1_700_000_000_000 - i, "blockNumber": 60_000_000 - i,
            "ret": [{"contractRet": "SUCCESS", "fee": 1}], "raw_data_hex": "ab" * 400, "signature": ["cd" * 65],
            "raw_data": {"contract": [{"type": kind, "parameter": {"value": {
                "owner_address": OWNER_HEX, "to_address": TO_HEX, "amount": 1_000_000, "data": "ee" * 300}}}]}}


def _trc20(i: int) -> dict:
    return {"transaction_id": f"t{i}", "from": ADDRESS, "to": "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf",
            "value": "5000000", "block_timestamp": 1_700_000_000_000 - i, "type": "Transfer",
            "token_info": {"address": USDT, "decimals": 6, "symbol": "USDT", "name": "Tether USD"}}


class _Grid:
    def __init__(self, records: list[dict], page: int = MAX_PAGE) -> None:
        self.records = records
        self.page = page
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append(params)
        start = int(params.get("fingerprint") or 0)
        size = min(self.page, int(params.get("limit", MAX_PAGE)))
        rows = self.records[start:start + size]
        meta = {"fingerprint": str(start + size)} if start + size < len(self.records) else {}
        return httpx.Response(200, content=json.dumps({"data": rows, "meta": meta, "success": True}))

    def client(self, **kw) -> TronClient:
        return TronClient(api_key="k", min_interval=0,
                          client=httpx.Client(transport=httpx.MockTransport(self.handler)), **kw)


def test_a_re_read_of_the_newest_page_is_served_from_the_cache():
    grid = _Grid([_native(i) for i in range(5)])
    first = grid.client().get_outgoing_transactions(ADDRESS)
    again = grid.client()
    assert again.get_outgoing_transactions(ADDRESS) == first and len(first) == 5
    assert len(grid.requests) == 1
    assert [r.from_cache for r in again.evidence.records] == [True]


def test_a_newest_first_read_keeps_only_minutes(monkeypatch):
    monkeypatch.setattr(config, "API_CACHE_OPEN_TTL_SECONDS", 0.05)
    grid = _Grid([_native(i) for i in range(3)])
    grid.client().get_outgoing_transactions(ADDRESS)
    time.sleep(0.08)
    grid.client().get_outgoing_transactions(ADDRESS)
    assert len(grid.requests) == 2


def test_a_settled_time_range_keeps_for_the_day(monkeypatch):
    monkeypatch.setattr(config, "API_CACHE_OPEN_TTL_SECONDS", 0.01)
    grid = _Grid([_trc20(i) for i in range(3)])
    grid.client(contract_address=USDT, token_decimals=6).get_incoming_between(ADDRESS, 0, 0, 1_600_000_000, 1_700_000_000)
    time.sleep(0.03)
    grid.client(contract_address=USDT, token_decimals=6).get_incoming_between(ADDRESS, 0, 0, 1_600_000_000, 1_700_000_000)
    assert len(grid.requests) == 1


def test_a_range_reaching_the_last_minutes_is_not_kept_for_the_day(monkeypatch):
    monkeypatch.setattr(config, "API_CACHE_OPEN_TTL_SECONDS", 0.01)
    grid = _Grid([_trc20(i) for i in range(3)])
    now = int(time.time())
    for _ in range(2):
        grid.client(contract_address=USDT, token_decimals=6).get_flows_between(ADDRESS, 0, 0, now - 3600, now)
        time.sleep(0.03)
    assert len(grid.requests) == 4  # two directions, twice


def test_a_paged_read_is_replayed_whole_and_never_resumed_live():
    grid = _Grid([_native(i) for i in range(7)], page=3)
    first = grid.client().get_outgoing_transactions(ADDRESS, limit=3)  # page size 3
    assert len(grid.requests) == 1  # one page filled the cap
    again = grid.client().get_outgoing_transactions(ADDRESS, limit=3)
    assert again == first and len(grid.requests) == 1
    # A read with a larger cap is a different read: its pages are all fetched live.
    whole = grid.client().get_outgoing_transactions(ADDRESS, limit=7)
    assert len(whole) == 7 and len(grid.requests) == 4  # three pages of three
    grid.requests.clear()
    assert grid.client().get_outgoing_transactions(ADDRESS, limit=7) == whole and grid.requests == []


def test_a_multi_page_range_is_replayed_with_every_page_as_cached_evidence():
    grid = _Grid([_trc20(i) for i in range(5)], page=2)
    txs, complete = grid.client(contract_address=USDT, token_decimals=6).get_incoming_between(
        "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf", 0, 0, 1_600_000_000, 1_700_000_000)
    assert complete and len(txs) == 5 and len(grid.requests) == 3
    again = grid.client(contract_address=USDT, token_decimals=6)
    assert again.get_incoming_between("TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf", 0, 0,
                                      1_600_000_000, 1_700_000_000) == (txs, True)
    assert len(grid.requests) == 3
    assert [r.from_cache for r in again.evidence.records] == [True, True, True]
    assert len({r.request for r in again.evidence.records}) == 3  # each page's own request


def test_a_watch_read_goes_to_the_chain():
    grid = _Grid([_native(i) for i in range(3)])
    grid.client().get_outgoing_transactions(ADDRESS)
    with api_budget.fresh_reads():
        grid.client().get_outgoing_transactions(ADDRESS)
    assert len(grid.requests) == 2


def test_cached_records_keep_what_the_parser_reads_and_nothing_else():
    client = TronClient(api_key="k", min_interval=0)
    token = TronClient(api_key="k", min_interval=0, contract_address=USDT, token_decimals=6)
    natives = [_native(1), _native(2, "TriggerSmartContract"), {"raw_data": {}}, {"raw_data": {"contract": {}}},
               {**_native(3), "ret": {"x": 1}}, {**_native(4), "ret": []}, "junk", None,
               {"raw_data": {"contract": [{"type": "TransferContract", "parameter": None}]}}]
    for raw in natives:
        assert client._native_transfer(_slim_native(raw)) == client._native_transfer(raw), raw
    assert len(json.dumps(_slim_native(_native(1)))) < 400
    assert _slim_native(_native(2, "TriggerSmartContract")) == {"raw_data": {"contract": [{"type": "TriggerSmartContract"}]}}
    tokens = [_trc20(1), {**_trc20(2), "type": "Approval"}, {**_trc20(3), "token_info": "x"},
              {**_trc20(4), "token_info": {"address": USDT}}, "junk"]
    for raw in tokens:
        assert token._token_transfer(_slim_trc20(raw)) == token._token_transfer(raw), raw


def test_a_record_with_a_misshapen_result_or_contract_list_is_skipped_not_a_crash():
    client = TronClient(api_key="k", min_interval=0)
    assert client._native_transfer({**_native(1), "ret": {"x": 1}}) is None
    assert client._native_transfer({"raw_data": {"contract": {"a": 1}}}) is None
