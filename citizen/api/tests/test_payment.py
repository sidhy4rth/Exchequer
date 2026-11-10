"""GET /api/payment: one transaction, read from a keyless public endpoint,
confirms the citizen's own payment -- from, to, amount, token, time -- and
nothing after it. Every answer here is stubbed: no test reaches a network."""
from __future__ import annotations

import io
import json
import time
import urllib.request

import pytest
from conftest import call

from _lib import chain

TX = "ab" * 32
USDT_TRON = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_ETH = "0xdac17f958d2ee523a2206206994597c13d831ec7"
PAYER, SCAMMER, NEXT = "TPayer" + "1" * 28, "TScam" + "2" * 29, "TNext" + "3" * 29


@pytest.fixture
def answers(monkeypatch):
    """{url substring or RPC method: answer}; records every read."""
    table, seen = {}, []

    def fake(url, body=None, timeout=chain.TIMEOUT):
        seen.append((url, body))
        key = body["method"] if body else url
        for want, answer in table.items():
            if want in key:
                if isinstance(answer, Exception):
                    raise answer
                return answer(body) if callable(answer) else answer
        raise chain.CouldNotCheck("no stub")
    monkeypatch.setattr(chain, "fetch", fake)
    table["seen"] = seen
    return table


def ask(network="tron", digest=TX, client="203.0.113.7"):
    return call("payment", method="GET", query=f"network={network}&hash={digest}", client=client)


def test_a_tron_usdt_payment_shows_only_the_payment(db, answers):
    answers["transaction-info"] = {
        "hash": TX, "contractRet": "SUCCESS", "timestamp": 1_762_076_700_000, "ownerAddress": PAYER,
        "contractType": 31, "toAddress": USDT_TRON,
        "trc20TransferInfo": [
            {"contract_address": USDT_TRON, "from_address": PAYER, "to_address": SCAMMER, "amount_str": "9890500000",
             "decimals": 6, "symbol": "USDT"},
            {"contract_address": USDT_TRON, "from_address": SCAMMER, "to_address": NEXT, "amount_str": "1",
             "decimals": 6, "symbol": "USDT"}],
        "tokenTransferInfo": {"to_address": NEXT}, "contract_map": {SCAMMER: False}, "riskTransaction": False,
    }
    res = ask()
    assert res.status == 200
    assert res.body == {"payment": {"network": "Tron", "hash": TX, "from": PAYER, "to": SCAMMER,
                                    "amount": "9890.5", "token": "USDT", "time": "2025-11-02T09:45:00Z",
                                    "succeeded": True}}
    assert NEXT not in json.dumps(res.body)
    url, _ = answers["seen"][0]
    assert url.startswith("https://apilist.tronscanapi.com/") and "apikey" not in url.lower()


def test_a_plain_trx_payment(db, answers):
    answers["transaction-info"] = {"hash": TX, "contractRet": "SUCCESS", "timestamp": 1_762_076_700_000,
                                   "contractType": 1, "contractData": {"amount": 2_500_000,
                                                                       "owner_address": PAYER, "to_address": SCAMMER}}
    assert ask().body["payment"] | {} == {"network": "Tron", "hash": TX, "from": PAYER, "to": SCAMMER,
                                          "amount": "2.5", "token": "TRX", "time": "2025-11-02T09:45:00Z",
                                          "succeeded": True}


def test_an_ethereum_usdt_payment_reads_the_transfer_event(db, answers):
    payer, scammer = "0x" + "1" * 40, "0x" + "2" * 40
    pad = lambda a: "0x" + "0" * 24 + a[2:]  # noqa: E731
    answers["eth_getTransactionByHash"] = {"result": {"hash": "0x" + TX, "from": payer, "to": USDT_ETH,
                                                      "value": "0x0", "blockNumber": "0x10"}}
    answers["eth_getTransactionReceipt"] = {"result": {"status": "0x1", "logs": [
        {"address": USDT_ETH, "topics": [chain.TRANSFER, pad(payer), pad(scammer)], "data": hex(5_000_000)},
        {"address": USDT_ETH, "topics": [chain.TRANSFER, pad(scammer), pad("0x" + "3" * 40)], "data": "0x1"}]}}
    answers["eth_getBlockByNumber"] = {"result": {"timestamp": hex(1_762_076_700)}}
    res = ask("ethereum", "0x" + TX)
    assert res.body["payment"] == {"network": "Ethereum", "hash": "0x" + TX, "from": payer, "to": scammer,
                                   "amount": "5", "token": "USDT", "time": "2025-11-02T09:45:00Z",
                                   "succeeded": True}
    assert "0x" + "3" * 40 not in json.dumps(res.body)


def test_a_native_coin_payment_on_bnb_chain(db, answers):
    answers["eth_getTransactionByHash"] = {"result": {"hash": "0x" + TX, "from": "0x" + "1" * 40,
                                                      "to": "0x" + "2" * 40, "value": hex(10**18 // 4),
                                                      "blockNumber": "0x10"}}
    answers["eth_getTransactionReceipt"] = {"result": {"status": "0x0", "logs": []}}
    answers["eth_getBlockByNumber"] = {"result": {"timestamp": hex(1_762_076_700)}}
    payment = ask("bsc", TX).body["payment"]
    assert payment["token"] == "BNB" and payment["amount"] == "0.25" and payment["succeeded"] is False


def test_no_such_transaction_says_so(db, answers):
    answers["transaction-info"] = {}
    res = ask()
    assert res.status == 404 and "No payment" in res.body["error"]
    answers["eth_getTransactionByHash"] = {"result": None}
    assert ask("polygon").status == 404


def test_a_failed_read_says_it_could_not_check_right_now(db, answers):
    answers["transaction-info"] = chain.CouldNotCheck("timed out")
    res = ask()
    assert res.status == 503 and res.body == {"error": "We could not check this payment right now. "
                                                       "Please try again later."}
    answers["transaction-info"] = {"Error": "rate limited"}
    assert ask().status == 503
    answers["eth_getTransactionByHash"] = {"error": {"message": "limit"}}
    assert ask("arbitrum").status == 503


def test_an_unexpected_shape_is_a_failed_read_not_a_crash(db, answers):
    answers["transaction-info"] = {"hash": TX, "contractRet": "SUCCESS", "timestamp": "soon",
                                   "trc20TransferInfo": "nope", "contractType": 1, "contractData": []}
    assert ask().status == 503


def test_the_network_and_hash_are_checked_first(db, answers):
    for network, digest in [("dogecoin", TX), ("tron", "abc"), ("tron", "T" + "a" * 33), ("tron", "zz" * 32),
                            ("", TX)]:
        assert ask(network, digest).status == 400
    assert answers["seen"] == []


def test_lookups_are_rate_limited_per_connection(db, answers):
    answers["transaction-info"] = {}
    statuses = [ask().status for _ in range(21)]
    assert statuses[:20] == [404] * 20 and statuses[20] == 429
    assert ask(client="198.51.100.4").status == 404


def test_fetch_uses_a_timeout_and_caps_the_answer(monkeypatch):
    got = {}

    class Answer(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(request, timeout=None):
        got["timeout"], got["url"] = timeout, request.full_url
        return Answer(b'{"ok": 1}')
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert chain.fetch("https://example.invalid/x") == {"ok": 1}
    assert 0 < got["timeout"] <= 8
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout=None: Answer(b" " * (chain.MAX_BYTES + 1)))
    with pytest.raises(chain.CouldNotCheck):
        chain.fetch("https://example.invalid/x")
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout=None: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(chain.CouldNotCheck):
        chain.fetch("https://example.invalid/x")


def test_every_endpoint_is_public_and_keyless():
    for url in chain.endpoints():
        assert url.startswith("https://") and "key" not in url.lower()


def test_a_stalled_node_cannot_run_the_lookup_past_its_deadline(db, answers, monkeypatch):
    monkeypatch.setattr(chain, "DEADLINE", 0.4)
    timeouts = []

    def stall(body):
        time.sleep(0.25)
        return {"result": {"hash": "0x" + TX, "from": "0x" + "1" * 40, "to": "0x" + "2" * 40, "value": "0x1",
                           "blockNumber": "0x10"}}
    answers["eth_"] = stall
    real = chain.fetch
    monkeypatch.setattr(chain, "fetch", lambda url, body=None, timeout=chain.TIMEOUT: (
        timeouts.append(timeout), real(url, body, timeout))[1])
    started = time.monotonic()
    res = ask("ethereum")
    assert time.monotonic() - started < 0.4 + 0.2
    assert res.status == 503 and res.body["error"].startswith("We could not check this payment right now")
    assert timeouts and all(0 < t <= chain.DEADLINE for t in timeouts)  # each read gets only the time left


def test_the_deadline_fits_inside_the_functions_time_limit():
    vercel = json.loads((chain_dir() / "vercel.json").read_text())
    limit = vercel["functions"]["api/*.py"]["maxDuration"]
    assert chain.DEADLINE + 5 < limit  # 5 s: the database's connect timeout, before the lookup starts


def chain_dir():
    from conftest import API
    return API.parent
