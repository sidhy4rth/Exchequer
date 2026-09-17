"""TronGrid pagination has to stop on its own.

The native endpoint returns every transaction an account signed, and on a
busy wallet almost none of them are TRX transfers. If the loop only counted
the records it kept, it would page through the whole history looking for
enough of them -- which is exactly what happened on the hosted demo with a
high-volume wallet. So the loop is bounded by records *read*, not records
kept, and a short history is still returned in full.
"""

import json

import httpx

from app.tron_client import MAX_PAGE, MAX_SCAN, TronClient

OWNER_HEX = "41" + "11" * 20
TO_HEX = "41" + "22" * 20
ADDRESS = "TSFFxCbDLh6nP1x4BcyqkbEFJyx3zSGY2r"


def _trigger_record(i: int) -> dict:
    """A smart-contract call: signed by the account, moves no TRX."""
    return {
        "txID": f"call{i}",
        "block_timestamp": 1_700_000_000_000 - i,
        "ret": [{"contractRet": "SUCCESS"}],
        "raw_data": {"contract": [{"type": "TriggerSmartContract",
                                   "parameter": {"value": {"owner_address": OWNER_HEX}}}]},
    }


def _transfer_record(i: int) -> dict:
    return {
        "txID": f"tx{i}",
        "block_timestamp": 1_700_000_000_000 - i,
        "ret": [{"contractRet": "SUCCESS"}],
        "raw_data": {"contract": [{"type": "TransferContract",
                                   "parameter": {"value": {"owner_address": OWNER_HEX,
                                                           "to_address": TO_HEX,
                                                           "amount": 1_000_000}}}]},
    }


class _Pages:
    """Serves pages of `records` and counts how many were asked for."""

    def __init__(self, records: list[dict], endless: bool) -> None:
        self.records = records
        self.endless = endless
        self.requests = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        limit = int(request.url.params.get("limit", MAX_PAGE))
        fingerprint = request.url.params.get("fingerprint")
        start = int(fingerprint or 0)
        page = self.records[start:start + limit]
        meta = {}
        if page and (self.endless or start + limit < len(self.records)):
            meta["fingerprint"] = str(start + limit)
        return httpx.Response(200, content=json.dumps({"data": page, "meta": meta}))


def _client(pages: _Pages) -> TronClient:
    http = httpx.Client(transport=httpx.MockTransport(pages.handler))
    return TronClient(api_key="k", client=http, min_interval=0)


def test_busy_wallet_with_no_trx_transfers_stops_after_max_scan():
    # More contract calls than the scan ceiling, and TronGrid always offers
    # another page. Before the fix this never returned.
    pages = _Pages([_trigger_record(i) for i in range(MAX_SCAN * 3)], endless=True)
    txs = _client(pages).get_outgoing_transactions(ADDRESS)
    assert txs == []
    assert pages.requests == MAX_SCAN // MAX_PAGE


def test_short_history_is_returned_whole():
    # The ceiling must not clip a wallet that simply has few transfers.
    records = [_trigger_record(i) for i in range(50)] + [_transfer_record(i) for i in range(7)]
    pages = _Pages(records, endless=False)
    txs = _client(pages).get_outgoing_transactions(ADDRESS)
    assert [t.hash for t in txs] == [f"tx{i}" for i in range(7)]
    assert pages.requests == 1


def test_cap_still_wins_when_transfers_are_plentiful():
    pages = _Pages([_transfer_record(i) for i in range(MAX_PAGE * 4)], endless=True)
    txs = _client(pages).get_outgoing_transactions(ADDRESS, limit=300)
    assert len(txs) == 300
    assert pages.requests == 2
