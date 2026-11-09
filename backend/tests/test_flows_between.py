"""get_flows_between on each chain client (R4): both directions, and honest when cut short.

FIFO and LIBR need the order of everything a wallet did in the window, so each
client returns (transfers in, transfers out, complete). A read cut short says
so, and tracing_methods then reports "unknown" rather than a number.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import httpx
import pytest

from app import config, pipeline
from app.contracts import read_case
from app.etherscan_client import EtherscanClient, Transaction
from app.exchange_matcher import ExchangeMatcher
from app.nodereal_client import MAX_SCAN as NR_MAX_SCAN, NoderealClient
from app.pipeline import TraceRequest
from app.tron_client import TronClient

from conftest import addr

WALLET = "0x" + "ab" * 20
OTHER = "0x" + "cd" * 20


# ---------------------------------------------------------------------------
# Etherscan: one request, split by direction
# ---------------------------------------------------------------------------
def _eth_record(i, src, dst, value_wei, error="0"):
    return {"hash": f"0x{i:064x}", "from": src, "to": dst, "value": str(value_wei),
            "timeStamp": str(1_700_000_000 + i), "blockNumber": str(100 + i), "isError": error}


def _etherscan(records, calls):
    client = EtherscanClient(api_key="k", chain_id=1, min_interval=0.0)

    def request(params):
        calls.append(params)
        return records
    client._request = request
    return client


def test_etherscan_splits_one_read_into_in_and_out():
    calls = []
    records = [_eth_record(1, OTHER, WALLET, 10**18), _eth_record(2, WALLET, OTHER, 5 * 10**17),
               _eth_record(3, WALLET, OTHER, 10**18, error="1"),  # reverted: moved nothing
               _eth_record(4, OTHER, WALLET, 0)]                   # zero value: moved nothing
    client = _etherscan(records, calls)
    incoming, outgoing, complete = client.get_flows_between(WALLET, 100, 200, 0, 0)
    client.close()
    assert [t.value_native for t in incoming] == [1.0]
    assert [t.value_native for t in outgoing] == [0.5]
    assert complete is True
    assert len(calls) == 1 and (calls[0]["startblock"], calls[0]["endblock"]) == (100, 200)


def test_etherscan_a_full_page_is_incomplete():
    records = [_eth_record(i, OTHER, WALLET, 10**18) for i in range(1000)]
    client = _etherscan(records, [])
    _, _, complete = client.get_flows_between(WALLET, 100, 2000, 0, 0)
    client.close()
    assert complete is False


# ---------------------------------------------------------------------------
# TronGrid: one read per direction, by time
# ---------------------------------------------------------------------------
TRON_WALLET = "TSFFxCbDLh6nP1x4BcyqkbEFJyx3zSGY2r"
WALLET_HEX, OTHER_HEX = "41" + "11" * 20, "41" + "22" * 20


def _tron_transfer(i, owner_hex, to_hex):
    return {"txID": f"tx{i}", "block_timestamp": 1_700_000_000_000 + i, "ret": [{"contractRet": "SUCCESS"}],
            "raw_data": {"contract": [{"type": "TransferContract", "parameter": {"value": {
                "owner_address": owner_hex, "to_address": to_hex, "amount": 2_000_000}}}]}}


def test_tron_reads_each_direction_once_in_the_window():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        incoming = "only_to" in params
        record = _tron_transfer(1, OTHER_HEX, WALLET_HEX) if incoming else _tron_transfer(2, WALLET_HEX, OTHER_HEX)
        return httpx.Response(200, content=json.dumps({"data": [record], "meta": {}}))

    client = TronClient(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0)
    wallet = client._native_transfer(_tron_transfer(0, WALLET_HEX, OTHER_HEX)).from_address
    incoming, outgoing, complete = client.get_flows_between(wallet, 0, 0, 1_700_000_000, 1_700_000_100)
    assert complete is True
    assert [t.to_address for t in incoming] == [wallet] and [t.from_address for t in outgoing] == [wallet]
    assert {"only_to", "only_from"} == {k for p in seen for k in p if k in ("only_to", "only_from")}
    assert all(p.get("only_confirmed") == "true" for p in seen)  # never unconfirmed records
    assert all(p["min_timestamp"] == str(1_700_000_000_000) for p in seen)


# ---------------------------------------------------------------------------
# NodeReal: one scan per direction; a capped scan is incomplete
# ---------------------------------------------------------------------------
HEAD = 50_000_000


def _nr_record(i, src, dst):
    return {"hash": f"0x{i:x}", "from": src, "to": dst, "value": hex(10**18), "decimal": 18,
            "blockNum": hex(HEAD - 10 - i), "blockTimeStamp": 1_700_000_000, "asset": "BNB", "receiptsStatus": 1}


def _nodereal(endless_from=False):
    directions = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(HEAD)})
        params = body["params"][0]
        direction = "toAddress" if "toAddress" in params else "fromAddress"
        directions.append(direction)
        if direction == "toAddress":
            result = {"transfers": [_nr_record(1, OTHER, WALLET)]}
        elif endless_from:
            result = {"transfers": [_nr_record(i, WALLET, OTHER) for i in range(1000)], "pageKey": "more"}
        else:
            result = {"transfers": [_nr_record(2, WALLET, OTHER)]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    client = NoderealClient(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)),
                            min_interval=0)
    return client, directions


def test_nodereal_scans_both_directions():
    client, directions = _nodereal()
    incoming, outgoing, complete = client.get_flows_between(WALLET, HEAD - 100, HEAD - 1, 0, 0)
    assert complete is True and len(incoming) == 1 and len(outgoing) == 1
    assert directions == ["toAddress", "fromAddress"]


def test_nodereal_a_capped_outgoing_scan_makes_the_read_incomplete():
    assert NR_MAX_SCAN > 0
    client, _ = _nodereal(endless_from=True)
    _, _, complete = client.get_flows_between(WALLET, HEAD - 100, HEAD - 1, 0, 0)
    assert complete is False


# ---------------------------------------------------------------------------
# The flag, and a whole trace with it on
# ---------------------------------------------------------------------------
def test_the_tracing_methods_flag_is_off_by_default_and_listed():
    assert config.FLAGS["EXCHEQUER_TRACING_METHODS"]["on"] is False
    assert config.FLAGS["EXCHEQUER_TRACING_METHODS"]["about"].startswith("Lane A, R4")


SEED, MID, HOT, ELSEWHERE = addr("5eed"), addr("a1d"), addr("b1a"), addr("0e5e")


def _tx(n, src, dst, value, block):
    return Transaction(hash=f"0x{n:064x}", from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 1e18), timestamp=1_700_000_000 + block * 12,
                       block_number=block, is_error=False, asset="ETH")


# The module docstring's example as a whole trace: 40 of the victim's reach
# MID, then 60 from elsewhere, then MID sends 50 to the exchange.
HISTORY = [_tx(1, SEED, MID, 40.0, 10), _tx(2, ELSEWHERE, MID, 60.0, 11), _tx(3, MID, HOT, 50.0, 12)]


class _Chain:
    def __init__(self):
        self.flow_reads = []

    def get_outgoing_transactions(self, address, limit=None):
        return [t for t in HISTORY if t.from_address == address]

    def get_incoming_between(self, address, *window):
        return [t for t in HISTORY if t.to_address == address], True

    def get_flows_between(self, address, *window):
        self.flow_reads.append(address)
        return ([t for t in HISTORY if t.to_address == address],
                [t for t in HISTORY if t.from_address == address], True)


@pytest.fixture
def traced(monkeypatch):
    chain = _Chain()

    @contextmanager
    def open_source(_chain, _asset):
        yield chain

    labels = {HOT: {"exchange": "Binance", "label": "Binance 14", "type": "hot_wallet"}}
    monkeypatch.setattr(pipeline, "open_source", open_source)
    monkeypatch.setattr(pipeline, "get_matcher", lambda key: ExchangeMatcher(labels, chain="ethereum"))
    monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])

    def run(on):
        monkeypatch.setattr(config, "TRACING_METHODS", on)
        return pipeline.run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=3)), chain
    return run


def test_with_the_flag_on_the_case_carries_all_three_figures(traced):
    result, chain = traced(True)
    case = read_case(result)
    assert (case.estimates.fifo, case.estimates.prorata, case.estimates.libr) == (40.0, 20.0, 0.0)
    assert case.estimates.conservative == 0.0
    assert result["tracing_methods"]["conservative_method"] == "libr"
    assert chain.flow_reads == [MID]


def test_with_the_flag_off_nothing_changes_and_nothing_extra_is_read(traced):
    # Pro-rata reads each hop wallet's flows once (it nets out coins the wallet
    # got back from wallets it paid), the same one read R4 shares when on.
    result, chain = traced(False)
    case = read_case(result)
    assert result["tracing_methods"] is None
    assert (case.estimates.fifo, case.estimates.libr) == (None, None)
    assert case.estimates.prorata == case.estimates.conservative == 20.0
    assert chain.flow_reads == [MID]
