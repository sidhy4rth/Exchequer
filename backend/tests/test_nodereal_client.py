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

    def __init__(self, records: list[dict], endless: bool, sends_at: tuple[int, ...] = ()) -> None:
        self.records = records
        self.endless = endless
        self.transfer_calls = 0
        self.sends_at = sends_at  # blocks at which the wallet sent (its nonce history)

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(HEAD)})
        if body["method"] == "eth_getTransactionCount":
            block = int(body["params"][1], 16)
            nonce = sum(1 for b in self.sends_at if b <= block)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(nonce)})
        if body["method"] == "eth_getBlockByNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"timestamp": hex(1_700_000_000)}})
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


def test_a_wallet_quiet_for_longer_than_the_lookback_is_found_by_its_nonce():
    """BSC blocks are ~0.45 s, so the default lookback is under three days. A
    wallet whose last send was a month earlier must still be found."""
    old = HEAD - 5_000_000
    record = {**_record(0, hex(10**18)), "blockNum": hex(old)}
    rpc = _Rpc([record], endless=False, sends_at=(old - 300_000, old))
    client = _client(rpc)
    client.allow_deep_search(ADDRESS)  # the reported address (pipeline.run_trace)
    txs = client.get_outgoing_transactions(ADDRESS)
    assert [t.block_number for t in txs] == [old]
    assert client.deep_searched[ADDRESS][1] == old


def test_a_wallet_that_never_sent_costs_no_deep_search():
    client = _client(_Rpc([], endless=False))
    client.allow_deep_search(ADDRESS)
    assert client.get_outgoing_transactions(ADDRESS) == []
    assert client.deep_searched == {} and ADDRESS in client.searched_from


def test_only_one_deep_search_per_trace():
    old = HEAD - 5_000_000
    rpc = _Rpc([], endless=False, sends_at=(old,))
    client = _client(rpc)
    client.allow_deep_search(ADDRESS)
    client.get_outgoing_transactions(ADDRESS)
    client.get_outgoing_transactions(OTHER)
    assert list(client._send_ranges) == [ADDRESS]


def test_a_hop_is_searched_forward_from_when_the_funds_arrived():
    """The reported wallet paid OTHER a month ago; OTHER's onward transfer, days
    later, is outside the recent search but must still be found."""
    paid_at = HEAD - 5_000_000
    third = "0x" + "ef" * 20
    pay = {**_record(0, hex(10**18)), "blockNum": hex(paid_at)}
    onward = {**_record(1, hex(10**18)), "from": OTHER, "to": third, "blockNum": hex(paid_at + 150_000)}

    class Directional(_Rpc):
        def handler(self, request):
            body = json.loads(request.content)
            if body["method"] == "nr_getAssetTransfers":
                sender = body["params"][0].get("fromAddress")
                self.records = [r for r in (pay, onward) if r["from"] == sender]
            return super().handler(request)

    client = _client(Directional([], endless=False, sends_at=(paid_at,)))
    client.allow_deep_search(ADDRESS)  # the reported wallet; OTHER is found from the arrival
    assert len(client.get_outgoing_transactions(ADDRESS)) == 1
    assert [t.to_address for t in client.get_outgoing_transactions(OTHER)] == [third]


# -- r1-trace-engine-6: deep search is for the reported address alone ---------
# The budget used to be a count checked before the slot was recorded, and a
# level is fetched on several threads sharing one client: every quiet wallet
# in the level passed the check and ran its ~27-51-call nonce search, and
# which ones did depended on timing.
def _quiet_level_rpc(jitter: bool):
    import random
    import threading
    import time

    seed = "0x" + "5e" * 20
    quiet = ["0x" + f"{i:02x}" * 20 for i in range(1, 7)]
    old = HEAD - 5_000_000
    pays = [{**_record(i, hex(10**18)), "from": seed, "to": q, "blockNum": hex(HEAD - 100 - i)}
            for i, q in enumerate(quiet)]
    lock = threading.Lock()
    calls: list[str] = []

    class Rpc(_Rpc):
        def handler(self, request):
            body = json.loads(request.content)
            if jitter:
                time.sleep(random.uniform(0, 0.005))
            if body["method"] == "nr_getAssetTransfers":
                sender = body["params"][0].get("fromAddress")
                self.records = [r for r in pays if r["from"] == sender]
                with lock:
                    calls.append(json.dumps(body["params"], sort_keys=True))
            elif body["method"] == "eth_getTransactionCount":
                with lock:
                    calls.append("nonce " + json.dumps(body["params"]))
            return super().handler(request)

    # Every quiet wallet last sent long before the lookback.
    return seed, quiet, Rpc([], endless=False, sends_at=(old,)), calls


def test_a_concurrent_level_never_deep_searches_a_hop():
    from app.graph_builder import TraceConfig, build_trace_graph

    runs = []
    for _ in range(3):
        seed, quiet, rpc, calls = _quiet_level_rpc(jitter=True)
        http = httpx.Client(transport=httpx.MockTransport(rpc.handler))
        client = NoderealClient(api_key="k", client=http, min_interval=0.01)
        client.allow_deep_search(seed)
        build_trace_graph(seed, client, cfg=TraceConfig(max_depth=2, max_concurrent_fetches=6))
        assert client.deep_searched == {} and client._send_ranges == {}
        assert not any(c.startswith("nonce") for c in calls)
        assert set(client.searched_from) == set(quiet)
        runs.append(sorted(calls))
    assert runs[0] == runs[1] == runs[2]  # the same requests whatever the thread order


def test_a_client_never_told_deep_searches_nothing():
    old = HEAD - 5_000_000
    rpc = _Rpc([], endless=False, sends_at=(old,))
    calls = []
    original = rpc.handler

    def counting(request):
        calls.append(json.loads(request.content)["method"])
        return original(request)
    client = NoderealClient(api_key="k", client=httpx.Client(transport=httpx.MockTransport(counting)),
                            min_interval=0)
    assert client.get_outgoing_transactions(ADDRESS) == []
    assert "eth_getTransactionCount" not in calls


def test_the_lookback_is_inclusive_so_a_quiet_wallet_costs_exactly_its_windows():
    rpc = _Rpc([], endless=False)
    client = NoderealClient(api_key="k", client=httpx.Client(transport=httpx.MockTransport(rpc.handler)),
                            min_interval=0, lookback_blocks=500_000)
    client.get_outgoing_transactions(ADDRESS)
    assert rpc.transfer_calls == 5


def test_a_hop_whose_funds_arrived_in_the_recent_window_is_not_deep_searched():
    paid = {**_record(0, hex(10**18)), "to": OTHER, "blockNum": hex(HEAD - 50)}
    rpc = _Rpc([], endless=False, sends_at=(HEAD - 5_000_000,))

    class Rpc(_Rpc):
        def handler(self, request):
            body = json.loads(request.content)
            if body["method"] == "nr_getAssetTransfers":
                self.records = [paid] if body["params"][0].get("fromAddress") == ADDRESS else []
            return super().handler(request)
    rpc = Rpc([], endless=False, sends_at=(HEAD - 5_000_000,))
    client = _client(rpc)
    client.allow_deep_search(ADDRESS)
    client.allow_deep_search(OTHER)
    client.get_outgoing_transactions(ADDRESS)  # sees OTHER receive at HEAD - 50
    client.get_outgoing_transactions(OTHER)
    assert OTHER not in client._send_ranges


def test_a_trace_allows_the_deep_search_for_its_reported_address_only(monkeypatch):
    from contextlib import contextmanager

    from app import pipeline
    from app.pipeline import TraceRequest, run_trace

    allowed = []

    class Source:
        def allow_deep_search(self, address):
            allowed.append(address)

        def get_outgoing_transactions(self, address, limit=None):
            return []

    @contextmanager
    def open_source(chain, asset):
        yield Source()
    monkeypatch.setattr(pipeline, "open_source", open_source)
    run_trace(TraceRequest(address=ADDRESS, chain="bsc", follow_swaps=False))
    assert allowed == [ADDRESS]
