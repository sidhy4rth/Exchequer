"""Etherscan reads reach blocks above any chain's height.

Every newest-first and read-from-arrival request sent endblock=99999999.
Arbitrum One passed block 99,999,999 in 2023, so on Etherscan's documented
semantics ("ending block number to search to") an Arbitrum trace or watch
saw nothing after early 2023, and a read from an arrival above that block
was an inverted range that could only come back empty
(r2-g2-watchlist-alerts-0-5).

The value is the one Etherscan's V2 txlist reference shows, 999,999,999: it
fits a signed 32-bit integer (a 10-digit endblock does not, and a server that
parses it as one would refuse every read) and is far above Arbitrum One's
head, the highest of our Etherscan chains (522,711,376 on 9 Nov 2026).
"""
from __future__ import annotations

import httpx
import pytest

from app.etherscan_client import ENDBLOCK_LATEST, SINCE_ENDBLOCK, EtherscanClient

ARBITRUM_HEAD_NOV_2026 = 522_711_376
INT32_MAX = 2**31 - 1

WALLET = "0x" + "1" * 40
CASHOUT = "0x" + "3" * 40
OLD_PAYEE = "0x" + "4" * 40
ROWS = [
    {"hash": "0xold", "from": WALLET, "to": OLD_PAYEE, "value": "10", "timeStamp": "1650000000",
     "blockNumber": "50000000", "isError": "0"},
    {"hash": "0xnew", "from": WALLET, "to": CASHOUT, "value": "10", "timeStamp": "1780000000",
     "blockNumber": "380000000", "isError": "0"},
]


def _client(seen: list[dict]) -> EtherscanClient:
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        lo, hi = int(params.get("startblock", 0)), int(params.get("endblock", 0))
        # Applies endblock literally, as Etherscan documents it.
        rows = [r for r in ROWS if lo <= int(r["blockNumber"]) <= hi]
        if params.get("sort") == "desc":
            rows = rows[::-1]
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})
    return EtherscanClient(api_key="k", chain_id=42161, min_interval=0.0, include_internal=False,
                           client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("read", [
    lambda c: c.get_transactions(WALLET),
    lambda c: c.get_outgoing_transactions(WALLET),
    lambda c: c.get_incoming_transactions(WALLET),
    lambda c: c.get_outgoing_transactions_since(WALLET, 400_000_000),
])
def test_reads_ask_for_blocks_above_any_chain_height(read):
    seen: list[dict] = []
    read(_client(seen))
    assert seen and all(ARBITRUM_HEAD_NOV_2026 < int(p["endblock"]) <= INT32_MAX for p in seen)


def test_the_open_endblock_is_etherscans_documented_value():
    assert ENDBLOCK_LATEST == SINCE_ENDBLOCK == 999_999_999


def test_a_read_from_an_arbitrum_arrival_is_not_an_inverted_range():
    seen: list[dict] = []
    _client(seen).get_outgoing_transactions_since(WALLET, 300_000_000)
    assert int(seen[0]["startblock"]) <= int(seen[0]["endblock"])


def test_an_arbitrum_transfer_above_block_1e8_is_returned():
    seen: list[dict] = []
    client = _client(seen)
    assert "0xnew" in [t.hash for t in client.get_outgoing_transactions(WALLET)]
    assert [t.hash for t in client.get_outgoing_transactions_since(WALLET, 300_000_000)] == ["0xnew"]
