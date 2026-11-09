"""POST /payments/search (app/payment_search.py): an officer finds the victim's
payment by its amount and time, without its hash. Only exact matches into
the one wallet come back; the wallet's other transfers never do.

A stub provider, no network, no store.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import access, config, payment_search, rate_limit
from app.api_budget import BudgetSpent, DeadlineReached
from app.etherscan_client import (AllowanceSpent, EtherscanClient, EtherscanError, EtherscanRateLimitError,
                                  ProviderQuotaError, Transaction)
from app.main import app
from app.nodereal_client import NoderealClient, NoderealQuotaError
from app.routes import cases

from conftest import addr

WALLET = addr("5ca")
VICTIM = addr("71c")
OTHER = addr("07e")
AT = 1_700_000_000  # 2023-11-14 22:13:20 UTC
WEI = 10**18


def tx(n, src, dst, wei, when):
    return Transaction(hash="0x" + f"{n:02x}" * 32, from_address=src, to_address=dst,
                       value_native=wei / WEI, value_wei=wei, timestamp=when, block_number=when // 12,
                       is_error=False, asset="ETH")


PAID = tx(1, VICTIM, WALLET, 2 * WEI, AT)


class Stub:
    """Returns every row it holds, whatever it is asked: the search must filter."""

    def __init__(self, rows, capped=False):
        self.rows, self.capped, self.asked = rows, capped, []

    def get_incoming_transactions(self, address, limit=None):
        self.asked.append((address, limit))
        return list(self.rows)

    def history_capped(self, address):
        return self.capped

    def allow_deep_search(self, address):
        self.asked.append(("deep", address))


@pytest.fixture
def chain(monkeypatch):
    holder = {"client": Stub([PAID])}

    @contextmanager
    def open_source(chain, asset):
        yield holder["client"]

    monkeypatch.setattr(payment_search, "open_source", open_source)
    return holder


def search(headers=None, **kw):
    body = {"chain": "ethereum", "asset": "ETH", "wallet": WALLET, "amount": "2",
            "from": AT - 3600, "to": AT + 3600, **kw}
    return TestClient(app).post("/payments/search", json=body, headers=headers or {})


# ---------------------------------------------------------------- matching
def test_an_exact_match_is_found(chain):
    response = search(**{"from": "2023-11-15T03:00:00+05:30", "to": "2023-11-15T04:00:00+05:30"})
    assert response.status_code == 200
    body = response.json()
    assert body["matches"] == [{"tx_hash": PAID.hash, "timestamp": AT, "amount": "2", "from": VICTIM,
                                "to": WALLET, "chain": "ethereum", "asset": "ETH",
                                "found_by": "officer_search"}]
    # The same read payment intake makes, so a trace from this hash finds it.
    assert chain["client"].asked == [("deep", WALLET), (WALLET, config.TX_INTAKE_LOOKUP_LIMIT)]


def test_a_near_miss_amount_is_not_returned(chain):
    chain["client"] = Stub([tx(2, VICTIM, WALLET, 2 * WEI + 1, AT), tx(3, VICTIM, WALLET, 2 * WEI - 1, AT),
                            tx(4, VICTIM, WALLET, 2 * WEI // 10, AT)])
    body = search().json()
    assert body["matches"] == [] and body["scanned"] == 3


def test_a_token_amount_matches_to_the_tokens_own_decimals(chain):
    usdt = tx(5, VICTIM, WALLET, 1_500_250_000, AT)  # 1,500.25 USDT: 6 decimals on Ethereum
    chain["client"] = Stub([usdt, tx(6, VICTIM, WALLET, 1_500_250_001, AT)])
    body = search(asset="usdt", amount="1500.25").json()
    assert [(m["tx_hash"], m["amount"], m["asset"]) for m in body["matches"]] == [(usdt.hash, "1500.25", "USDT")]


def test_a_transfer_outside_the_window_is_not_returned(chain):
    chain["client"] = Stub([tx(7, VICTIM, WALLET, 2 * WEI, AT - 1), tx(8, VICTIM, WALLET, 2 * WEI, AT),
                            tx(9, VICTIM, WALLET, 2 * WEI, AT + 60), tx(10, VICTIM, WALLET, 2 * WEI, AT + 61)])
    body = search(**{"from": AT, "to": AT + 60}).json()
    assert [m["timestamp"] for m in body["matches"]] == [AT, AT + 60], "both ends are in the window"


def test_other_wallets_transfers_are_never_returned(chain):
    sent = tx(11, WALLET, OTHER, 2 * WEI, AT)          # the wallet paying someone the same amount
    elsewhere = tx(12, VICTIM, OTHER, 2 * WEI, AT)     # the same amount into another wallet
    failed = replace(tx(13, VICTIM, WALLET, 2 * WEI, AT), is_error=True)
    unrelated = tx(14, OTHER, WALLET, 7 * WEI, AT)     # the wallet's other income
    chain["client"] = Stub([sent, elsewhere, failed, unrelated, PAID])
    response = search()
    body = response.json()
    assert [m["tx_hash"] for m in body["matches"]] == [PAID.hash]
    assert set(body) == {"matches", "more_matches", "scanned", "complete"}
    for row in (sent, elsewhere, failed, unrelated):
        assert row.hash not in response.text
    assert OTHER not in response.text, "not one other counterparty is named"


def test_the_limit_is_honoured(chain):
    rows = [tx(20 + i, VICTIM, WALLET, 2 * WEI, AT + 600 - i * 60) for i in range(payment_search.MAX_MATCHES + 2)]
    chain["client"] = Stub(rows)
    body = search().json()
    assert len(body["matches"]) == payment_search.MAX_MATCHES and body["more_matches"] is True
    times = [m["timestamp"] for m in body["matches"]]
    assert times == sorted(times), "oldest first"


def test_a_search_that_did_not_reach_the_window_says_so(chain):
    chain["client"] = Stub([PAID], capped=True)
    assert search().json()["complete"] is False
    chain["client"] = Stub([PAID, tx(30, OTHER, WALLET, WEI, AT - 7200)], capped=True)
    assert search().json()["complete"] is True, "a transfer from before the window was read"
    chain["client"] = Stub([PAID], capped=False)
    assert search().json()["complete"] is True, "the whole history was read"


def etherscan(signed, internal):
    """A real EtherscanClient on the native coin: each list newest first, cut at `offset` on its own."""
    def handler(request):
        q = dict(request.url.params)
        rows = sorted(internal if q["action"] == "txlistinternal" else signed, key=lambda r: -int(r["timeStamp"]))
        return httpx.Response(200, json={"status": "1" if rows else "0", "message": "OK" if rows else
                                         "No transactions found", "result": rows[:int(q["offset"])]})
    return EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, include_internal=True,
                           client=httpx.Client(transport=httpx.MockTransport(handler)))


def inflows(*times):
    return [{"hash": f"0x{t:064x}", "from": OTHER, "to": WALLET, "value": str(WEI), "timeStamp": str(t),
             "blockNumber": str(t // 12), "isError": "0"} for t in times]


RECENT = [AT + 86_400 + i for i in range(5)]  # five transfers a day after the window


@pytest.mark.parametrize("signed, internal, complete", [
    (RECENT, [AT - 20 * 86_400], False),       # the signed page is full and stops after the window
    ([AT - 7200], RECENT, False),              # the contract-moved page is full and stops after it
    (RECENT[:4] + [AT - 7200], [AT - 86_400], True),
    (RECENT[:1], [], True),                    # neither page full: the whole history
])
def test_an_etherscan_read_is_complete_only_if_both_lists_reach_the_window(chain, monkeypatch, signed, internal,
                                                                           complete):
    monkeypatch.setattr(config, "TX_INTAKE_LOOKUP_LIMIT", 5)
    chain["client"] = etherscan(inflows(*signed), inflows(*internal))
    found = payment_search.search(config.CHAINS["ethereum"], "ETH", WALLET, 2 * WEI, AT - 3600, AT + 3600)
    assert found["matches"] == [] and found["complete"] is complete


def test_a_nodereal_deep_search_is_never_complete(chain):
    """The recent blocks held nothing, so NodeReal read back from the wallet's
    last send: the victim's payment after that send, before the lookback, was
    never read, though an older inflow was."""
    head = 50_000_000
    sends = (48_400_000, 48_500_000)
    rows = [{"hash": f"0x{b:064x}", "from": VICTIM, "to": WALLET, "value": hex(2 * WEI), "decimal": 18,
             "blockNum": hex(b), "blockTimeStamp": t, "asset": "BNB", "receiptsStatus": 1}
            for b, t in ((48_450_000, AT - 10 * 86_400), (49_000_000, AT))]

    def handler(request):
        method, params = json.loads(request.content)["method"], json.loads(request.content)["params"]
        if method == "eth_blockNumber":
            result = hex(head)
        elif method == "eth_getTransactionCount":
            result = hex(sum(b <= int(params[1], 16) for b in sends))
        else:
            lo, hi = int(params[0]["fromBlock"], 16), int(params[0]["toBlock"], 16)
            result = {"transfers": [r for r in reversed(rows) if lo <= int(r["blockNum"], 16) <= hi
                                    and r["to"] == params[0].get("toAddress")]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    chain["client"] = NoderealClient(api_key="k", lookback_blocks=500_000, min_interval=0,
                                     client=httpx.Client(transport=httpx.MockTransport(handler)))
    found = payment_search.search(config.CHAINS["bsc"], "BNB", WALLET, 2 * WEI, AT - 3600, AT + 3600)
    assert chain["client"].deep_searched, "the read went deep"
    assert found["matches"] == [] and found["complete"] is False


def test_an_empty_asset_is_the_chains_own_coin(chain):
    assert [m["asset"] for m in search(asset="").json()["matches"]] == ["ETH"]


# ---------------------------------------------------------------- refusals
@pytest.mark.parametrize("change, status", [
    ({"to": AT - 3600 + 7 * 86_400 + 1}, 422),        # a window past seven days
    ({"to": AT - 3600}, 422),                          # an empty window
    ({"from": AT + 7200}, 422),                        # a window that ends before it starts
    ({"from": "2023-11-14T21:00:00"}, 422),            # a time with no zone
    ({"amount": "0"}, 422),
    ({"amount": "-2"}, 422),
    ({"amount": "NaN"}, 422),
    ({"amount": "2.0000000000000000001"}, 400),       # finer than ETH's 18 decimals
    ({"asset": "USDT", "amount": "1.0000001"}, 400),   # finer than USDT's 6
    ({"wallet": "T" + "1" * 33}, 400),                 # a Tron address on Ethereum
    ({"wallet": WALLET[:-1]}, 400),
    ({"asset": "DOGE"}, 400),
    ({"chain": "dogechain"}, 400),
])
def test_validation_errors(chain, change, status):
    response = search(**change)
    assert response.status_code == status, response.text
    assert chain["client"].asked == [], "refused before any provider read"
    assert rate_limit.traces.remaining("testclient") == rate_limit.traces.limit, "and before any charge"


class Broken(Stub):
    def __init__(self, error):
        super().__init__([])
        self.error = error

    def get_incoming_transactions(self, address, limit=None):
        raise self.error


def test_a_provider_failure_says_so_in_a_fixed_sentence(chain, monkeypatch):
    monkeypatch.setattr(config, "TRACES_RUNNING_PER_CLIENT", 1)
    chain["client"] = Broken(EtherscanError("<html>key ABC123 is over quota</html>"))
    response = search()
    assert response.status_code == 502
    assert "ABC123" not in response.text and "could not be searched" in response.json()["detail"]
    assert cases._running_by_client.get("testclient", 0) == 0
    assert search().status_code == 502, "the running slot was given back"


@pytest.mark.parametrize("error, status", [
    (EtherscanRateLimitError("slow down"), 429),
    (BudgetSpent("etherscan", scope="client"), 429),
    (ProviderQuotaError("daily limit"), 503),          # waiting seconds will not help: as POST /trace
    (NoderealQuotaError("monthly CU spent"), 503),
    (AllowanceSpent("etherscan", scope="site"), 503),
    (BudgetSpent("nodereal", scope="trace"), 503),
    (DeadlineReached(), 503),
])
def test_a_failure_gets_the_status_post_trace_gives_it(chain, error, status):
    chain["client"] = Broken(error)
    assert search().status_code == status


# ---------------------------------------------------------------- gating
def test_the_demo_code_guards_it_when_one_is_set(chain, monkeypatch):
    monkeypatch.setattr(config, "DEMO_CODE", "river-otter-42")
    monkeypatch.setattr(access, "wrong_codes", rate_limit.SlidingWindowLimiter(10, 900))
    assert access.is_guarded("POST", "/payments/search")
    assert search().status_code == 403
    assert chain["client"].asked == []
    assert search(headers={access.CODE_HEADER: "river-otter-42"}).status_code == 200


def test_it_spends_the_same_hourly_allowance_as_a_trace(chain, monkeypatch):
    monkeypatch.setattr(rate_limit, "traces", rate_limit.SlidingWindowLimiter(2, 3600))
    assert search().status_code == 200
    assert rate_limit.traces.remaining("testclient") == 1
    assert search().status_code == 200
    refused = search()
    assert refused.status_code == 429 and "This connection" in refused.json()["detail"]
    assert len(chain["client"].asked) == 4, "two searches read the wallet; the third was refused first"


def test_the_site_wide_ceiling_applies_too(chain, monkeypatch):
    monkeypatch.setattr(rate_limit, "traces_total", rate_limit.SlidingWindowLimiter(1, 3600))
    assert search().status_code == 200
    refused = search()
    assert refused.status_code == 429 and "this site" in refused.json()["detail"].lower()
    assert rate_limit.traces.remaining("testclient") == rate_limit.traces.limit - 1, "the refusal was refunded"


def test_every_search_is_audited_without_the_complaints_particulars(chain, caplog):
    with caplog.at_level(logging.INFO, logger="exchequer.audit"):
        assert search().status_code == 200
    lines = [r.getMessage() for r in caplog.records if r.name == "exchequer.audit"]
    assert len(lines) == 1 and "payment.search" in lines[0] and '"matches": 1' in lines[0]
    assert WALLET not in lines[0] and VICTIM not in lines[0] and PAID.hash not in lines[0]
