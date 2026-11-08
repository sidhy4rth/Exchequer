"""A token trace keeps only the traced token's own rows (r1-trace-engine-14).

Every client asks its provider for one contract's transfers, but none checked
what came back: a fake "USDT" -- the standard address-poisoning tool -- with a
billion units would have entered the trace as USDT if a filter were ever
ignored, and Tron stamped a row naming no contract as the traced token. Each
parser now drops a row from another contract, or from none (8 Nov check).
"""
from __future__ import annotations

import json

import httpx

from app import config
from app.etherscan_client import EtherscanClient
from app.nodereal_client import NoderealClient
from app.tron_client import TronClient

T0 = 1_700_000_000
FAKE = "0x" + "fa4e" * 10
S, X = "0x" + "5e" * 20, "0x" + "d0" * 20


def test_etherscan_drops_rows_from_another_contract_or_none():
    usdt = config.get_chain("ethereum").find_token("USDT")

    def row(n, contract, units):
        r = {"hash": f"0x{n:064x}", "from": S, "to": X, "value": str(units), "tokenDecimal": "6",
             "tokenSymbol": "USDT", "timeStamp": str(T0 + n), "blockNumber": str(18_000_000 + n)}
        if contract is not None:
            r["contractAddress"] = contract
        return r

    def handler(request):
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": [
            row(1, FAKE, 10**15), row(2, None, 10**15), row(3, usdt.address.upper().replace("0X", "0x"), 5 * 10**6)]})

    client = EtherscanClient(api_key="k", chain_id=1, min_interval=0, contract_address=usdt.address,
                             token_decimals=6, include_internal=False,
                             client=httpx.Client(transport=httpx.MockTransport(handler)))
    kept = client.get_outgoing_transactions(S)
    assert [(t.contract_address, t.value_native) for t in kept] == [(usdt.address.lower(), 5.0)]


def test_nodereal_drops_rows_from_another_contract_or_none():
    usdt = config.get_chain("bsc").find_token("USDT")

    def transfer(n, contract):
        r = {"hash": f"0x{n:064x}", "from": S, "to": X, "value": hex(10**30), "decimal": 18,
             "blockNum": hex(49_999_000 + n), "blockTimeStamp": T0 + n, "asset": "USDT", "receiptsStatus": 1}
        if contract is not None:
            r["contractAddress"] = contract
        return r

    def handler(request):
        body = json.loads(request.content)
        if body["method"] == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(50_000_000)})
        if body["method"] == "eth_getTransactionCount":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x1"})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"transfers": [
            transfer(1, FAKE), transfer(2, None), transfer(3, usdt.address)]}})

    client = NoderealClient(api_key="k", min_interval=0, contract_addresses=[usdt.address], token_decimals=18,
                            client=httpx.Client(transport=httpx.MockTransport(handler)))
    kept = client.get_outgoing_transactions(S)
    assert kept and all(t.contract_address == usdt.address.lower() for t in kept)
    assert {t.hash for t in kept} == {f"0x{3:064x}"}


def test_tron_drops_rows_from_another_contract_or_none():
    usdt = config.get_chain("tron").find_token("USDT")
    client = TronClient(api_key="k", min_interval=0, contract_address=usdt.address, token_decimals=6,
                        client=httpx.Client())

    def record(tid, info):
        r = {"transaction_id": tid * 64, "from": "T" + "A" * 33, "to": "T" + "B" * 33, "value": str(10**12),
             "block_timestamp": T0 * 1000, "type": "Transfer"}
        if info is not None:
            r["token_info"] = info
        return r

    no_address = record("a", {"symbol": "USDT", "decimals": 6})
    other = record("b", {"symbol": "USDT", "decimals": 6, "address": "TFakeFakeFakeFakeFakeFakeFakeFakeF"})
    no_info = record("c", None)
    real = record("d", {"symbol": "USDT", "decimals": 6, "address": usdt.address})
    assert [client._token_transfer(r) for r in (no_address, other, no_info)] == [None, None, None]
    kept = client._token_transfer(real)
    assert kept is not None and kept.contract_address == usdt.address and kept.value_native == 1_000_000.0
