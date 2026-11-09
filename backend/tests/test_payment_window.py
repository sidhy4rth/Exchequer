"""A payment trace reads the reported wallet from the payment's block (5-0).

The payment intake reads the newest TX_INTAKE_LOOKUP_LIMIT incoming
transfers, but the walk read the reported wallet only from its newest
TRACE_MAX_TXS_PER_ADDRESS records. A busy wallet's payment was found and the
transfers that moved it on were never read. On BSC the intake's incoming scan
anchored the wallet at the oldest inflow it read, not at the payment. These
pin the read from the payment's block, the NodeReal anchor, and the note when
neither can reach back.
"""
from __future__ import annotations

from contextlib import contextmanager

import httpx
import pytest

from app import api_budget, config
from app import pipeline as main
from app.etherscan_client import EtherscanClient, Transaction
from app.graph_builder import OUTGOING, TraceConfig, build_trace_graph
from app.payment_intake import window_anchor, window_start
from app.pipeline import TraceRequest, run_trace

from conftest import addr

SEED, VICTIM, EXCH, NOISE = addr("5eed"), addr("71c"), addr("e8c4"), addr("0e5e")
T0, BLOCK0 = 1_700_000_000, 18_000_000
CFG = TraceConfig(max_depth=2, max_txs_per_address=5)


def tx(src, dst, value, ts, block, n=0):
    return Transaction(hash=f"0x{abs(hash((src, dst, ts, n))):064x}"[:66], from_address=src, to_address=dst,
                       value_native=value, value_wei=int(value * 1e18), timestamp=ts, block_number=block,
                       is_error=False, asset="ETH")


class BusySeed:
    """The victim paid SEED at T0, SEED sent the money to EXCH one block later,
    then made `later` small sends, so its newest page of 5 misses the exit."""

    def __init__(self, later: int, with_since: bool = True):
        self.paid = tx(VICTIM, SEED, 10.0, T0, BLOCK0)
        self.sends = ([tx(SEED, EXCH, 9.9, T0 + 12, BLOCK0 + 1)]
                      + [tx(SEED, NOISE, 0.5, T0 + 1000 + i, BLOCK0 + 100 + i, i) for i in range(later)])
        self.since_calls: list[tuple[str, int]] = []
        if not with_since:
            self.get_outgoing_transactions_since = None

    def get_outgoing_transactions(self, address, limit=None):
        newest = sorted((t for t in self.sends if t.from_address == address), key=lambda t: t.timestamp,
                        reverse=True)
        return newest[:limit] if limit else newest

    def get_incoming_transactions(self, address, limit=None):
        return [self.paid] if address == SEED else []

    def get_outgoing_transactions_since(self, address, start_block, limit=None):
        self.since_calls.append((address, start_block))
        oldest = sorted((t for t in self.sends if t.from_address == address and t.block_number >= start_block),
                        key=lambda t: t.timestamp)
        return oldest[:limit] if limit else oldest


def test_a_payment_trace_reads_a_busy_seed_from_the_payment_block():
    client = BusySeed(later=8)
    result = build_trace_graph(SEED, client, cfg=CFG, is_terminal=lambda a: a == EXCH, direction=OUTGOING,
                               seed_window=T0, seed_window_block=BLOCK0)
    assert client.since_calls == [(SEED, BLOCK0)]
    assert result.graph.has_edge(SEED, EXCH)
    assert SEED in result.read_from_arrival


def test_a_quiet_payment_wallet_costs_no_extra_request():
    client = BusySeed(later=2)  # 3 sends, under the page size of 5
    result = build_trace_graph(SEED, client, cfg=CFG, is_terminal=lambda a: a == EXCH, direction=OUTGOING,
                               seed_window=T0, seed_window_block=BLOCK0)
    assert result.graph.has_edge(SEED, EXCH) and client.since_calls == []
    assert not any("history read limit" in r for r in result.truncation_reasons)


def test_a_windowed_page_that_does_not_reach_the_window_is_a_truncation():
    client = BusySeed(later=8, with_since=False)  # a provider with no forward read
    result = build_trace_graph(SEED, client, cfg=CFG, is_terminal=lambda a: a == EXCH, direction=OUTGOING,
                               seed_window=T0, seed_window_block=BLOCK0)
    assert not result.graph.has_edge(SEED, EXCH)
    (note,) = [r for r in result.truncation_reasons if "history read limit" in r]
    assert note.startswith(f"history read limit at {SEED[:10]}...")
    assert "were not read" in note and result.truncated


def test_the_window_anchor_is_the_earliest_payment():
    first = {"timestamp": T0, "block": BLOCK0, "tx_hash": "0xa"}
    later = {"timestamp": T0 + 60, "block": BLOCK0 + 5, "tx_hash": "0xb"}
    assert window_anchor([later, first]) == (T0, BLOCK0)
    assert window_start([later, first]) == T0
    # Tron TRC-20 rows carry no block: the read is then by time.
    assert window_anchor([{**first, "block": 0}]) == (T0, None)


# ---------------------------------------------------------------- through run_trace
@pytest.fixture
def intake_on(monkeypatch):
    monkeypatch.setattr(config, "TX_INTAKE", True)
    monkeypatch.setattr(main, "detect_swaps", lambda *a, **k: [])


def test_run_trace_passes_the_payment_block(intake_on, monkeypatch):
    client = BusySeed(later=2)

    @contextmanager
    def open_source(chain, asset):
        yield client

    seen = {}
    real = main.build_trace_graph

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)

    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(main, "build_trace_graph", spy)
    run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=2,
                           payments=[{"tx_hash": client.paid.hash}]))
    assert seen["seed_window"] == T0 and seen["seed_window_block"] == BLOCK0


def test_an_address_trace_passes_no_seed_block(intake_on, monkeypatch):
    @contextmanager
    def open_source(chain, asset):
        yield BusySeed(later=2)

    seen = {}
    real = main.build_trace_graph
    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(main, "build_trace_graph", lambda *a, **k: seen.update(k) or real(*a, **k))
    run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=2))
    assert seen["seed_window"] is None and seen["seed_window_block"] is None


def _etherscan_wallet():
    """The verifier's shape: the victim pays 10 ETH, a 9.99 ETH cash-out follows
    one block later, then 300 inflows, then an unrelated 50 ETH outflow."""
    scam, victim, cashout, other = addr("5ca"), addr("71c"), addr("ca50"), addr("07e5")
    records = []

    def rec(frm, to, eth, i):
        records.append({"hash": "0x%064x" % (len(records) + 1), "from": frm, "to": to,
                        "value": str(int(eth * 10**18)), "timeStamp": str(T0 + i * 12),
                        "blockNumber": str(BLOCK0 + i), "isError": "0", "txreceipt_status": "1", "input": "0x"})

    rec(victim, scam, 10.0, 0)
    rec(scam, cashout, 9.99, 1)
    for i in range(300):
        rec(addr("%x" % (0x1000 + i)), scam, 0.5, 100 + i)
    rec(scam, other, 50.0, 1000)
    return scam, cashout, other, records


def test_a_payment_trace_finds_the_cash_out_on_etherscan(intake_on, monkeypatch):
    scam, cashout, other, records = _etherscan_wallet()
    calls = []

    def handler(request):
        p = dict(request.url.params)
        if p.get("action") == "balance":
            return httpx.Response(200, json={"status": "1", "message": "OK", "result": "0"})
        if p.get("action") != "txlist":
            return httpx.Response(200, json={"status": "0", "message": "No transactions found", "result": []})
        calls.append(p)
        who, start, offset = p["address"].lower(), int(p.get("startblock", 0)), int(p["offset"])
        rows = [r for r in records if who in (r["from"], r["to"]) and int(r["blockNumber"]) >= start]
        rows.sort(key=lambda r: int(r["blockNumber"]), reverse=p.get("sort") == "desc")
        rows = rows[:offset]
        if not rows:
            return httpx.Response(200, json={"status": "0", "message": "No transactions found", "result": []})
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})

    @contextmanager
    def open_source(chain, asset):
        yield EtherscanClient(api_key="k-window", chain_id=1, min_interval=0.0, include_internal=False,
                              client=httpx.Client(transport=httpx.MockTransport(handler)))

    api_budget.reset()
    monkeypatch.setattr(main, "open_source", open_source)
    result = run_trace(TraceRequest(address=scam, chain="ethereum", asset="ETH", max_depth=2,
                                    payments=[{"tx_hash": records[0]["hash"]}]))
    api_budget.reset()
    targets = {e["target"] for e in result["graph"]["edges"]}
    assert cashout in targets, "the transfer that moved the victim's money on is read"
    assert any(c["address"].lower() == scam and c.get("startblock") == str(BLOCK0) and c.get("sort") == "asc"
               for c in calls)
    assert scam in result["read_from_arrival"]


# ---------------------------------------------------------------- NodeReal (BSC)
def test_nodereal_seed_is_anchored_at_the_payment_block(intake_on, monkeypatch):
    from app.exchange_matcher import ExchangeMatcher
    from app.nodereal_client import NoderealClient

    scam, victim, earlier, binance_dep, moved = addr("5ca"), addr("71c"), addr("07e"), addr("b1"), addr("1ee")
    tip = 10_000_032
    stamp = lambda b: 1_600_000_000 + b // 2  # noqa: E731
    rows = [
        ("0x" + "01" * 32, earlier, scam, 3.0, 7_000_000),     # someone else's money, before the victim's
        ("0x" + "02" * 32, scam, moved, 2.9, 7_000_500),       # moved on before the victim paid
        ("0x" + "03" * 32, victim, scam, 10.0, 7_800_000),     # the victim's payment
        ("0x" + "04" * 32, scam, binance_dep, 9.9, 7_800_100),  # the victim's money, to Binance
    ]
    sends = []

    class FakeNodereal(NoderealClient):
        def _rpc(self, method, params):
            if method == "eth_blockNumber":
                return hex(tip)
            if method == "eth_getTransactionCount":
                who, block = params[0], int(params[1], 16)
                return hex(sum(1 for r in rows if r[1] == who and r[4] <= block))
            if method == "eth_getBlockByNumber":
                return {"timestamp": hex(stamp(int(params[0], 16)))}
            assert method == "nr_getAssetTransfers"
            q = params[0]
            lo, hi = int(q["fromBlock"], 16), int(q["toBlock"], 16)
            if "fromAddress" in q:
                sends.append((q["fromAddress"], lo, hi))
            found = [r for r in rows if lo <= r[4] <= hi and (q.get("fromAddress") == r[1] or q.get("toAddress") == r[2])]
            found.sort(key=lambda r: r[4], reverse=True)
            return {"transfers": [{"hash": r[0], "from": r[1], "to": r[2], "value": hex(int(r[3] * 1e18)),
                                   "blockNum": hex(r[4]), "blockTimeStamp": stamp(r[4]), "receiptsStatus": 1}
                                  for r in found][: int(q["maxCount"], 16)]}

    @contextmanager
    def open_source(chain, asset):
        yield FakeNodereal(api_key="fake", min_interval=0.0)

    labels = {binance_dep: {"exchange": "Binance", "label": "Binance deposit", "type": "deposit_wallet"}}
    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(main, "get_matcher", lambda key: ExchangeMatcher(labels, chain=key))
    result = run_trace(TraceRequest(address=scam, chain="bsc", asset="BNB", max_depth=2, follow_swaps=False,
                                    payments=[{"tx_hash": rows[2][0]}]))
    # The arrival-first scan walks down to its anchor: the payment's block, not
    # the older inflow the intake's incoming read saw (7,000,000).
    assert min(lo for who, lo, _ in sends if who == scam) == 7_800_000
    assert result["exchange"] == "Binance"
    assert "sent no BNB" not in (result["message"] or "")
