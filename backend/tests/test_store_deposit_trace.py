"""A trace, its report and its letter at a label-store exchange row (ADR-0012).

What matters here:
  * a deposit row (on OKX's own list, seen sweeping into an OKX hot wallet) is
    read as a probable deposit: the letter asks OKX to confirm the address and
    name the customer, never "the exchange's own wallet";
  * an own-wallet row is read as before (the exchange's own wallet, no KYC on
    it), and both say what they stand on: the list, and for a deposit, the sweep;
  * with EXCHEQUER_STORE_EXCHANGE_ROWS off, the store's rows change nothing:
    the trace, report and letter are byte for byte those of a trace with no
    store at all (deposit inference names the address, as it does today).
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from app import config, exchange_matcher, pipeline, provenance, request_letters
from app.etherscan_client import Transaction
from app.exchange_matcher import ExchangeMatcher, curated_sources
from app.label_store import LabelStore
from app.models import Case
from app.pipeline import TraceRequest, run_trace
from app.report import build_report, render_text_report
from conftest import addr
from scripts.add_store_exchange_rows import add
from tests.test_store_deposit_rows import write_rows
from tests.test_store_exchange_rows import empty_store

SEED, W1 = addr("5eed"), addr("a1")
DEP, OWN = addr("de90"), addr("e0e1")  # fixture addresses: a listed deposit, a listed own wallet
OKX_1 = "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b"  # "OKX 1", hot_wallet, data/exchange_labels.json
T = 1_700_000_000


def _tx(n, src, dst, value, when):
    return Transaction(hash="0x" + f"{n:064x}", from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 1e18), timestamp=when, block_number=when // 12,
                       is_error=False, asset="ETH")


SWEEPS = [_tx(3, DEP, OKX_1, 40.0, T + 30), _tx(4, DEP, OKX_1, 59.0, T + 40)]
TO_DEPOSIT = [_tx(1, SEED, W1, 99.0, T + 10), _tx(2, W1, DEP, 99.0, T + 20), *SWEEPS]
TO_OWN = [_tx(5, SEED, W1, 99.0, T + 10), _tx(6, W1, OWN, 99.0, T + 20)]


@pytest.fixture
def store(tmp_path):
    out, por = empty_store(tmp_path), tmp_path / "okx_por_ethereum.csv"
    write_rows(por, [
        {"address": DEP, "chain": "ethereum", "type": "deposit_wallet", "sweeps_to": OKX_1,
         "sweep_tx": SWEEPS[0].hash, "checked_on": "2026-11-15"},
        {"address": OWN, "chain": "ethereum"},
    ])
    assert add(out, por)["added"] == 2
    return LabelStore(out)


@pytest.fixture
def trace(monkeypatch):
    def run(history, store):
        class Fake:
            def get_outgoing_transactions(self, address, limit=None):
                return [t for t in history if t.from_address == address]

        @contextmanager
        def open_source(chain, asset):
            yield Fake()

        files, seed = curated_sources("ethereum")
        matcher = ExchangeMatcher(files, chain="ethereum", instant=seed, store=store)
        # One clock for every run, so two traces compared byte for byte differ only in what they found.
        monkeypatch.setattr(provenance, "utc_now_iso", lambda: "2026-11-15T00:00:00Z")
        monkeypatch.setattr(pipeline, "open_source", open_source)
        monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
        monkeypatch.setattr(pipeline, "get_matcher", lambda key=None: matcher)
        monkeypatch.setattr(exchange_matcher, "get_matcher", lambda chain_key=None: matcher)
        result = run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=4,
                                        follow_swaps=False))
        case = Case(id="c1", address=SEED, created_at="2026-11-15T00:00:00+00:00", result_json=json.dumps(result))
        report = render_text_report(build_report(case, generated_at="2026-11-15T00:00:00+00:00"))
        try:
            letter = request_letters.draft("c1", result, "exchange")
        except request_letters.LetterNotApplicable as exc:  # no exchange reached: that is the outcome compared
            letter = f"no letter: {exc}"
        return result, report, letter
    return run


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(config, "STORE_EXCHANGE_ROWS", True)


def _flat(text):
    return " ".join(text.split())


def test_a_deposit_row_is_a_probable_deposit_and_the_letter_asks_for_the_customer(trace, store, flag_on):
    result, report, letter = trace(TO_DEPOSIT, store)
    assert (result["exchange"], result["exchange_address"]) == ("OKX", DEP)
    assert result["attribution_inferred"] is True and result["inferred_deposits"] == []
    match = next(m for m in result["matches"] if m["address"] == DEP)
    assert match["wallet_type"] == "inferred_deposit" and match["label"] == "probable OKX deposit address (listed by OKX)"
    assert match["attribution_basis"]["deposit"] == {"sweeps_to": OKX_1, "sweeps_to_label": "OKX 1",
                                                     "sweep_tx": SWEEPS[0].hash, "checked_on": "2026-11-15"}
    assert result["attribution"]["kind"] == "deposit_inferred"
    # The trace stopped at the deposit address: the hot wallet is not a match.
    assert OKX_1 not in {m["address"] for m in result["matches"]}
    report, letter = _flat(report), _flat(letter)
    assert "Address kind : a probable deposit address (inferred: only the exchange can confirm it)" in report
    assert "the exchange's own wallet" not in report
    assert "Basis : INFERRED from the exchange's own list and a sweep into it" in report
    assert "Listed by OKX in its own published address list: por:okx:2026-11: OKX's own published" in report
    assert f"Sent funds to {OKX_1} (OKX 1), a wallet labelled as OKX's, in tx {SWEEPS[0].hash} (checked 2026-11-15)" \
        in report
    assert "suspected deposit address" in letter
    assert f"confirm whether {DEP} is a deposit address you issued" in letter
    assert "the account holder's identity and KYC documents" in letter
    assert "published 2026-11-01, retrieved 2026-11-14" in letter and SWEEPS[0].hash in letter
    assert "This request is not about the wallet" not in letter


def test_an_own_wallet_row_is_the_exchange_wallet_as_before_and_says_its_source(trace, store, flag_on):
    result, report, letter = trace(TO_OWN, store)
    assert (result["exchange"], result["exchange_address"]) == ("OKX", OWN)
    match = next(m for m in result["matches"] if m["address"] == OWN)
    assert match["wallet_type"] == "exchange_wallet" and "deposit" not in match["attribution_basis"]
    assert result["attribution_inferred"] is False and result["attribution"]["kind"] == "exchange_wallet"
    report, letter = _flat(report), _flat(letter)
    assert "Address kind : the exchange's own wallet (not one customer's account)" in report
    assert "Basis : the exchange's own published address list (PoR)" in report
    assert "Listed by OKX in its own published address list: por:okx:2026-11" in report
    assert f"This request is not about the wallet {OWN} itself" in letter
    assert "KYC documents" not in letter
    assert "Listed by OKX in its own published address list" in letter and "Sent funds to" not in letter


@pytest.mark.parametrize("history", [TO_DEPOSIT, TO_OWN], ids=["to_deposit", "to_own"])
def test_with_the_flag_off_the_store_rows_change_nothing(trace, store, history):
    assert config.STORE_EXCHANGE_ROWS is False
    with_store = trace(history, store)
    without = trace(history, None)
    assert json.dumps(with_store[0], sort_keys=True) == json.dumps(without[0], sort_keys=True)
    assert with_store[1:] == without[1:]
    assert "attribution_basis" not in json.dumps(with_store[0]) and "Listed by" not in with_store[1]


def test_with_the_flag_off_deposit_inference_names_the_address_as_today(trace, store):
    result, report, letter = trace(TO_DEPOSIT, store)
    assert (result["exchange"], result["exchange_address"]) == ("OKX", DEP)
    assert [m["address"] for m in result["inferred_deposits"]] == [DEP]
    assert "the account holder's identity and KYC documents" in _flat(letter)
