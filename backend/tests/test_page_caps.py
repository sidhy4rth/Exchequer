"""A read that stops at its record limit is a truncation, never "sent nothing" (r1-attribution-integrity-3).

Every provider read is capped by records (Etherscan's newest 200 of both
directions, a 1,000-record scan on Tron and NodeReal), and zero-value or dust
transfers count toward the cap before they are filtered out. Anyone can emit
them for gas alone, so 200 spam records into the reported wallet pushed its
real cash-out off the page, and the trace said the wallet "sent no USDT" with
no truncation note. A capped read is now flagged on the node and stated.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import httpx

from app import pipeline
from app.etherscan_client import EtherscanClient, Transaction
from app.graph_builder import TraceConfig, build_trace_graph
from app.nodereal_client import MAX_SCAN, NoderealClient
from app.pipeline import TraceRequest, run_trace
from app.tron_client import TronClient
from conftest import addr

SEED, HOP, EXCH, SPAMMER = addr("5eed"), addr("a1"), addr("e8c4"), addr("bad")
T0 = 1_700_000_000


def _row(n: int, src: str, dst: str, wei: int, ts: int) -> dict:
    return {"hash": f"0x{n:064x}", "from": src, "to": dst, "value": str(wei), "timeStamp": str(ts),
            "blockNumber": str(18_000_000 + n), "isError": "0"}


def _spammed_seed(monkeypatch, spam: int):
    """The seed sent 10 ETH out, then took `spam` zero-value records in."""
    rows = [_row(1, SEED, HOP, 10 * 10**18, T0)] + [_row(10 + i, SPAMMER, SEED, 0, T0 + 100 + i)
                                                   for i in range(spam)]

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params
        if q.get("address") != SEED:
            return httpx.Response(200, json={"status": "0", "message": "No transactions found", "result": []})
        newest = sorted(rows, key=lambda r: int(r["timeStamp"]), reverse=True)[: int(q.get("offset"))]
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": newest})

    @contextmanager
    def open_source(chain, asset):
        yield EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, include_internal=False,
                              client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(pipeline, "open_source", open_source)


def test_a_seed_page_full_of_zero_value_spam_is_a_truncation(monkeypatch):
    _spammed_seed(monkeypatch, spam=200)
    r = run_trace(TraceRequest(address=SEED, chain="ethereum", follow_swaps=False))
    assert r["truncated"] is True
    assert any(t.startswith(f"history read limit at {SEED[:10]}") and "older transfers" in t
               for t in r["truncation_reasons"])
    assert "cannot say it sent nothing" in r["message"]
    assert "sent no ETH" not in r["message"]
    seed = next(n for n in r["graph"]["nodes"] if n["address"] == SEED)
    assert seed["history_capped"] is True


def test_a_quiet_wallet_adds_no_truncation(monkeypatch):
    _spammed_seed(monkeypatch, spam=20)
    r = run_trace(TraceRequest(address=SEED, chain="ethereum", max_depth=1, follow_swaps=False))
    assert not any("history read limit" in t for t in r["truncation_reasons"])
    assert r["graph"]["edges"]  # the real outflow is on the page


class _Hop:
    """SEED paid HOP; HOP's newest page and its read from the arrival are both all dust."""

    def __init__(self, limit: int):
        self.limit = limit

    def get_outgoing_transactions(self, address, limit=None):
        if address == SEED:
            return [Transaction(hash="0x1", from_address=SEED, to_address=HOP, value_native=10.0,
                                value_wei=10**19, timestamp=T0, block_number=100, is_error=False)]
        if address == HOP:
            return [Transaction(hash=f"0x{2000 + i:x}", from_address=HOP, to_address=addr(f"d{i:x}"),
                                value_native=1e-9, value_wei=10**9, timestamp=T0 + 10_000 + i,
                                block_number=10_000 + i, is_error=False) for i in range(limit)]
        return []

    def get_outgoing_transactions_since(self, address, start_block, limit=None):
        return [Transaction(hash=f"0x{3000 + i:x}", from_address=HOP, to_address=addr(f"d{i:x}"),
                            value_native=1e-9, value_wei=10**9, timestamp=T0 + 1 + i,
                            block_number=101 + i, is_error=False) for i in range(limit)]


def test_a_full_read_from_arrival_page_is_a_truncation():
    result = build_trace_graph(SEED, _Hop(5), TraceConfig(max_depth=2, max_txs_per_address=5),
                               is_terminal=lambda a: a == EXCH)
    assert result.read_from_arrival == [HOP]
    assert any(t.startswith(f"history read limit at {HOP[:10]}") and "later transfers" in t
               for t in result.truncation_reasons)
    assert result.graph.nodes[HOP]["history_capped"] is True


def test_nodereal_capped_flag_is_per_address():
    spam, quiet = "0x" + "ab" * 20, "0x" + "cd" * 20
    head = 50_000_000

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(head)})
        params = body["params"][0]
        who = params["fromAddress"]
        start = int(params.get("pageKey") or 0)
        count = int(params["maxCount"], 16)
        rows = ([{"hash": f"0x{i:x}", "from": who, "to": quiet, "value": "0x0", "decimal": 18,
                  "blockNum": hex(head - 100 - i), "blockTimeStamp": T0, "asset": "BNB", "receiptsStatus": 1}
                 for i in range(start, start + count)] if who == spam else [])
        result = {"transfers": rows, **({"pageKey": str(start + count)} if rows else {})}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})
    client = NoderealClient(api_key="k", min_interval=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.get_outgoing_transactions(spam) == []  # MAX_SCAN zero-value records, nothing kept
    client.get_outgoing_transactions(quiet)
    assert client.history_capped(spam) is True
    assert client.history_capped(quiet) is False
    assert MAX_SCAN >= 1000


def test_tron_scan_budget_exhaustion_is_reported():
    from test_tron_client import ADDRESS, _Pages, _trigger_record

    pages = _Pages([_trigger_record(i) for i in range(5000)], endless=True)
    client = TronClient(min_interval=0, client=httpx.Client(transport=httpx.MockTransport(pages.handler)))
    assert client.get_outgoing_transactions(ADDRESS) == []
    assert client.history_capped(ADDRESS) is True


def test_the_read_in_full_caveat_is_withheld_when_a_read_was_capped():
    from app.scoring import score_case
    from conftest import make_graph

    graph = make_graph([(SEED, HOP, 1.0)], seed=SEED)
    clause = "signed transfers were read in full"
    assert clause in " ".join(score_case(graph, SEED, None, internal_transfers_read=True).caveats)
    graph.nodes[HOP]["history_capped"] = True
    assert clause not in " ".join(score_case(graph, SEED, None, internal_transfers_read=True).caveats)


def test_a_matched_case_with_no_capped_read_says_it_was_read_in_full():
    # 8 Nov check (r1-attribution-integrity-3): the band cap reused the name of
    # the "some read was capped" flag, so every matched case with a material
    # share said a read had hit its record limit when none had.
    from app.exchange_matcher import ExchangeMatch
    from app.scoring import score_case
    from conftest import make_graph

    exchange = addr("e1")
    graph = make_graph([(SEED, HOP, 10.0), (HOP, exchange, 9.0)], seed=SEED)
    match = ExchangeMatch(address=exchange, exchange="Binance", label="Binance 14", wallet_type="hot_wallet",
                          depth=2, value_received_native=9.0)
    materiality = {"primary_share": 0.9, "threshold": 0.1, "majority": 0.5, "primary_reach": 9, "denominator": 10}
    full = "signed transfers were read in full"
    capped = "which some reads reached"
    caveats = " ".join(score_case(graph, SEED, match, internal_transfers_read=True, materiality=materiality).caveats)
    assert full in caveats and capped not in caveats
    # A small share caps the band; the read is still complete.
    small = {**materiality, "primary_share": 0.05}
    caveats = " ".join(score_case(graph, SEED, match, internal_transfers_read=True, materiality=small).caveats)
    assert full in caveats and capped not in caveats
    graph.nodes[HOP]["history_capped"] = True
    caveats = " ".join(score_case(graph, SEED, match, internal_transfers_read=True, materiality=materiality).caveats)
    assert capped in caveats and full not in caveats
