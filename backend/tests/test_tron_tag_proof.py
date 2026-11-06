"""A TronScan tag names an exchange only when the tag and the address both hold up.

- The deny-list had no fake/fraud/drainer/lookalike words, so "Binance (Fake)"
  and "Bybit_Drainer" were attributed to the real exchange, and a TronScan
  warning and an exchange wallet sat on the same address (r1-providers-5).
- A live tag was accepted on its text alone: "OKX-DEX Router" or "Binance-Pool"
  named the exchange with no check that the address is an account and not a
  contract, which is what ADR-0006 asks of every label (r2-g2-documented-
  claims-vs-code-7-8).
- A zero-width or soft-hyphen character inside a deny word hid it from every
  rule, while the letters-only head still matched the exchange
  (r2-g2-frontend-intake-rendering-3-3).
"""
from __future__ import annotations

import io
import json
from contextlib import contextmanager

import httpx
import pytest

from app import config
from app import pipeline as main
from app.etherscan_client import Transaction
from app.pipeline import TraceRequest, run_trace
from app.tron_client import TronClient
from app.tron_tags import LiveTronExchanges, clean_tag, exchange_for_tag, tag_from_response, warning_from_response

SEED = "TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts"
HOP = "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU"
EXCH = "TMuA6YqfCeX8EhbfYEg5y7S4DqzSJireY9"

NOT_AN_EXCHANGE_WALLET = [
    "Binance (Fake)", "Binance_Fake", "Binance-Fraud", "Bybit_Drainer", "OKX (Impersonator)",
    "Binance:Lookalike", "Binance-Poisoning", "Binance (Victim)", "Binance-Honeypot",
    "OKX-DEX Router", "Binance: DEX Router", "OKX: Swap Router", "Binance-Pool", "Bybit: Router",
    "Binance (Swap)", "HTX-Router", "Binance (Clone)",
    # Invisible characters inside a deny word, and a bidi override.
    "Binance-Treas​ury", "Binance-Sc⁠am", "Binance-Ex­ploiter", "Binance-De‍ployer",
    "Binance-‮yrusaerT",
]


@pytest.mark.parametrize("tag", NOT_AN_EXCHANGE_WALLET)
def test_a_tag_that_only_borrows_an_exchange_s_name_is_not_an_exchange(tag):
    assert exchange_for_tag(tag) is None


@pytest.mark.parametrize("tag", ["Binance-Sc⁠am", "Binance-Ex­ploiter", "Fake_Phi​shing1"])
def test_an_invisible_character_cannot_hide_a_warning(tag):
    assert warning_from_response({"addressTag": tag}) is not None


def test_every_shipped_tron_exchange_label_still_reads_as_its_exchange():
    labels = json.loads(config.CHAINS["tron"].labels_path.read_text())["labels"]
    assert labels
    for meta in labels.values():
        assert exchange_for_tag(meta["label"]) == meta["exchange"], meta["label"]


def test_clean_tag_leaves_plain_text_and_removes_what_cannot_be_seen():
    assert clean_tag("Binance-Hot 7") == "Binance-Hot 7"
    assert clean_tag("  OKX​  Hot\nWallet\t3 ") == "OKX Hot Wallet 3"
    assert clean_tag("Ｂinance") == "Binance"  # NFKC: full-width letters
    assert clean_tag(None) == "" and len(clean_tag("x" * 1000)) == 200
    assert tag_from_response({"addressTag": "​⁠"}) is None


class FakeTags:
    enabled = True
    lookups = failures = 0

    def __init__(self, accounts):
        self.accounts = accounts

    def account(self, address):
        return self.accounts.get(address)


def _live(accounts, is_contract):
    return LiveTronExchanges(FakeTags(accounts), lambda a: False, is_contract=is_contract)


def test_an_exchange_tag_with_a_warning_on_the_same_address_is_not_an_exchange():
    live = _live({EXCH: {"tag": "Binance-Hot 9", "warning": "Suspicious"}}, lambda a: False)
    assert live.is_exchange(EXCH) is False
    assert live.warnings == {EXCH: "Suspicious"} and EXCH in live.rejected


@pytest.mark.parametrize("code, accepted", [(False, True), (True, False), (None, False)])
def test_an_exchange_tag_needs_an_account_not_a_contract(code, accepted):
    live = _live({EXCH: {"tag": "OKX Hot Wallet 8", "warning": None}}, lambda a: code)
    assert live.is_exchange(EXCH) is accepted
    assert (EXCH in live.found) is accepted
    assert (EXCH in live.rejected) is (not accepted)
    assert live.summary()["rejected_tags"] == ([] if accepted else [{"address": EXCH, "tag": live.rejected[EXCH]}])


def test_tron_client_reads_whether_an_address_is_a_contract():
    answers = {EXCH: {}, HOP: {"bytecode": "6080", "contract_address": HOP}}
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((request.method, request.url.path, body))
        if body["value"] == SEED:
            return httpx.Response(503)
        return httpx.Response(200, json=answers[body["value"]])
    client = TronClient(api_key="k", min_interval=0, max_retries=0,
                        client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.is_contract(EXCH) is False
    assert client.is_contract(HOP) is True
    assert client.is_contract(SEED) is None  # TronGrid failing: unknown, never "an account"
    assert seen[0] == ("POST", "/wallet/getcontract", {"value": EXCH, "visible": True})
    assert any("getcontract" in r.request for r in client.evidence.records)


def tx(src, dst, value, when):
    return Transaction(hash=f"{abs(hash((src, dst, when))):064x}", from_address=src, to_address=dst,
                       value_native=value, value_wei=int(value * 1e6), timestamp=when,
                       block_number=0, is_error=False, asset="USDT")


@pytest.fixture
def tron_trace(monkeypatch):
    """SEED -> HOP -> EXCH, where HOP sweeps twice into EXCH (a deposit-address shape)."""
    history = [tx(SEED, HOP, 100.0, 1_700_000_000), tx(HOP, EXCH, 60.0, 1_700_000_100),
               tx(HOP, EXCH, 39.0, 1_700_000_200)]
    contracts: dict[str, bool] = {}

    class Source:
        def get_outgoing_transactions(self, address, limit=None):
            return [t for t in history if t.from_address == address]

        def is_contract(self, address):
            return contracts.get(address, False)

    @contextmanager
    def open_source(chain, asset):
        yield Source()
    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(main.config, "TRONSCAN_API_KEY", "test-key")
    monkeypatch.setattr(main.TronScanTags, "account",
                        lambda self, a: {EXCH: {"tag": "Binance-Hot 9", "warning": None}}.get(a))
    return contracts


def test_a_trace_names_the_exchange_for_an_account(tron_trace):
    result = run_trace(TraceRequest(address=SEED, chain="tron", asset="USDT", max_depth=3))
    assert result["exchange"] == "Binance" and result["exchange_address"] == EXCH


def test_a_trace_never_names_an_exchange_for_a_contract(tron_trace):
    tron_trace[EXCH] = True
    result = run_trace(TraceRequest(address=SEED, chain="tron", asset="USDT", max_depth=3))
    assert result["exchange"] is None
    assert result["live_tags"]["rejected_tags"][0]["address"] == EXCH


def test_a_live_tag_is_never_a_sweep_destination_for_deposit_inference(tron_trace):
    result = run_trace(TraceRequest(address=SEED, chain="tron", asset="USDT", max_depth=3))
    assert result["exchange_address"] == EXCH  # the tagged wallet itself, labelled as a live tag
    assert result["inferred_deposits"] == [] and result["attribution_inferred"] is False


def test_the_eth_importer_reads_tags_as_plain_text(monkeypatch):
    from scripts import import_eth_labels as eth

    csv_text = ("address,chainId,label,nameTag\n"
                f"{'0x' + '1' * 40},1,binance,Binance: Treas​ury\n"
                f"{'0x' + '2' * 40},1,binance,Binance: Hot Wallet 3\n")

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(eth.urllib.request, "urlopen", lambda *a, **k: Response(csv_text.encode()))
    out = eth.candidates_by_chain()["ethereum"]
    assert list(out) == ["0x" + "2" * 40]
