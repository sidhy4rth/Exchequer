"""Only TRC-20 records that moved the traced token are transfers.

TronGrid's /v1/accounts/{a}/transactions/trc20 returns transfer records AND
approval records, told apart only by `type`. An approval moves nothing: it
lets a spender move up to `value` later, and the usual value is 2**256-1. The
parser used to read every row as a transfer, so one approve() call became an
edge of ~1.16e71 USDT to the spender -- an "exchange attribution" with high
confidence and a letter asking to freeze an impossible amount. A row for a
different token (should the server ever ignore the contract filter) must not
count either.
"""
from __future__ import annotations

import json

import httpx

from app.tron_client import TronClient

USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
FAKE = "TXYZfakeTokenContractAddr00000000"
WALLET = "TSFFxCbDLh6nP1x4BcyqkbEFJyx3zSGY2r"
SPENDER = "TQrY8tryqsYVCYS3MFbtffiPp2ccyn4STm"
FRIEND = "TD5gsCnXYaDzd6CwT1aT6XsPX5q8tBfTbY"


def row(tx: str, kind: str, to: str, value: int, contract: str = USDT, frm: str = WALLET) -> dict:
    return {"transaction_id": tx, "type": kind, "from": frm, "to": to, "value": str(value),
            "block_timestamp": 1_700_000_000_000,
            "token_info": {"symbol": "USDT", "address": contract, "decimals": 6, "name": "Tether USD"}}


ROWS = [
    row("approve", "Approval", SPENDER, 2**256 - 1),
    row("real", "Transfer", FRIEND, 100_000_000),
    row("fake", "Transfer", SPENDER, 5_000_000_000, contract=FAKE),
]


def client(rows: list[dict]) -> TronClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"data": rows, "meta": {}}))
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return TronClient(api_key="k", client=http, min_interval=0, contract_address=USDT, asset_symbol="USDT")


def test_an_approval_is_not_a_transfer():
    txs = client(ROWS).get_outgoing_transactions(WALLET)
    assert [t.hash for t in txs] == ["real"]
    assert txs[0].value_native == 100.0


def test_window_reads_skip_approvals_and_other_tokens_too():
    incoming = [row("approve-in", "Approval", WALLET, 2**256 - 1, frm=SPENDER),
                row("real-in", "Transfer", WALLET, 7_000_000, frm=FRIEND),
                row("fake-in", "Transfer", WALLET, 9_000_000, contract=FAKE, frm=SPENDER)]
    txs, _complete = client(incoming).get_incoming_between(WALLET, 0, 0, 1_600_000_000, 1_800_000_000)
    assert [t.hash for t in txs] == ["real-in"]


def test_a_row_without_a_type_is_still_read_as_a_transfer():
    # Older responses may omit `type`; only rows that say they are something
    # else are dropped.
    untyped = row("old", "Transfer", FRIEND, 1_000_000)
    del untyped["type"]
    assert [t.hash for t in client([untyped]).get_outgoing_transactions(WALLET)] == ["old"]


def test_only_confirmed_records_are_asked_for():
    # Without it TronGrid also returns unconfirmed records, which may never
    # make it into a block; evidence must rest on confirmed transfers only.
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, content=json.dumps({"data": [], "meta": {}}))
    http = httpx.Client(transport=httpx.MockTransport(handler))
    tron = TronClient(api_key="k", client=http, min_interval=0, contract_address=USDT, asset_symbol="USDT")
    tron.get_outgoing_transactions(WALLET)
    tron.get_incoming_between(WALLET, 0, 0, 1_600_000_000, 1_800_000_000)
    native = TronClient(api_key="k", client=http, min_interval=0)
    native.get_outgoing_transactions(WALLET)
    assert seen and all(p.get("only_confirmed") == "true" for p in seen)
