"""One letter per kind of attribution.

What the tool knows differs by kind, so what a letter may ask differs too. A KYC
request about an exchange's own hot wallet asks for something that does not exist
and tells its compliance team the sender misunderstood the trace. A demand for
customer data on the strength of an explorer's tag may reveal an investigation to
the wrong company. Real recorded demos are used where one exists; no demo reaches
a labelled deposit address, so that kind uses the placeholder fixture.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from app import config
from app.report import build_report, render_text_report
from app.report_pdf import render_pdf
from app.request_letters import attribution_kind, available, draft

from test_report import full_result, stored
from test_request_letters import DEPOSIT, SEED, TX, case

DEMOS = {d["demo"]: d["result"] for d in json.loads(
    (Path(config.DATA_DIR) / "recorded_demos.json").read_text(encoding="utf-8"))}
HOT_WALLET, EXPLORER_TAG, INFERRED = DEMOS[9], DEMOS[12], DEMOS[6]


def labelled(wallet_type: str = "deposit_wallet", **over) -> dict:
    return case(matches=[{"address": DEPOSIT, "wallet_type": wallet_type}], **over)


# -- which kind ----------------------------------------------------------------------
@pytest.mark.parametrize("result, kind", [
    (labelled(), "labelled_deposit"),
    (HOT_WALLET, "exchange_wallet"),
    (EXPLORER_TAG, "explorer_tag"),
    (INFERRED, "inferred_deposit"),
    (labelled("hot_wallet"), "exchange_wallet"),
    (labelled("cold_wallet"), "exchange_wallet"),
    (labelled("contract_wallet"), "exchange_wallet"),
    (labelled("exchange_wallet"), "exchange_wallet"),
    (case(), "exchange_wallet"),  # an older case that does not say: never assume one customer
])
def test_the_kind_comes_from_the_data_not_the_label_text(result, kind):
    assert attribution_kind(result) == kind


def test_a_tag_saying_deposit_is_still_only_a_tag():
    result = labelled(live_tags={"found": [{"address": DEPOSIT, "label": "X Deposit (TronScan tag, read live)"}]})
    assert attribution_kind(result) == "explorer_tag"


# -- labelled deposit ---------------------------------------------------------------
def test_a_labelled_deposit_asks_about_the_customer_behind_it():
    text = draft("case-1", labelled(), "exchange")
    assert f"deposit address {DEPOSIT}" in text
    assert "the account holder's identity and KYC documents" in text
    assert "any other deposit addresses issued to the same account" in text
    assert "last checked" in text  # says where the label came from and when


def test_a_deployer_label_is_not_called_a_deposit_address():
    """'Dep' in 'Binance: Deployer 3' used to make it one."""
    text = draft("case-1", labelled("exchange_wallet", exchange_label="Binance: Deployer 3"), "exchange")
    subject = next(line for line in text.splitlines() if line.startswith("Subject"))
    assert "deposit" not in subject.lower()
    assert "KYC" not in text


# -- inferred deposit ---------------------------------------------------------------
def test_an_inferred_deposit_asks_for_confirmation_before_anything_else():
    text = draft("demo-6", INFERRED, "exchange")
    assert f"to confirm whether {INFERRED['exchange_address']} is a deposit address" in text
    assert "only Bybit can confirm" in text or "only Binance can confirm" in text
    assert "labelled wallet" in text


# -- an exchange's own wallet --------------------------------------------------------
def test_a_hot_wallet_letter_asks_about_the_transactions_never_kyc_on_the_wallet():
    text = draft("demo-9", HOT_WALLET, "exchange")
    assert "identify the customer account or accounts behind each transaction" in text
    assert "KYC" not in text
    assert "restricting withdrawals from it" not in text
    assert "not about the wallet" in text


def test_a_hot_wallet_letter_lists_every_transaction_with_its_amount():
    text = draft("demo-9", HOT_WALLET, "exchange")
    into = [t for t in HOT_WALLET["transfers"] if t["to"] == HOT_WALLET["exchange_address"]]
    assert len(into) == 20
    for transfer in into:
        assert transfer["hash"] in text
    assert "first 10 of" not in text
    assert f"{into[0]['value_native']:,.6f} USDT" in text


def test_an_older_case_without_transfers_still_lists_every_hash_it_has():
    hashes = [f"0x{i:064x}" for i in range(1, 16)]
    path = [{"address": SEED, "depth": 0}, {"address": DEPOSIT, "depth": 1, "value_native": 2.5, "tx_count": 15,
                                            "first_seen": 1_758_000_000, "last_seen": 1_758_000_000,
                                            "tx_hashes": hashes}]
    text = draft("case-1", case(trace_path=path), "exchange")
    assert all(h in text for h in hashes)


# -- a live explorer tag -------------------------------------------------------------
def test_a_tag_letter_asks_first_whether_the_address_is_theirs():
    text = draft("demo-12", EXPLORER_TAG, "exchange")
    assert f"to confirm whether {EXPLORER_TAG['exchange_address']} is controlled by Flipster" in text
    assert "TronScan" in text and "has not confirmed" in text
    assert "KYC" not in text
    assert "UPI" not in text


def test_a_tag_letter_does_not_repeat_the_tools_own_wording():
    assert "read live" not in draft("demo-12", EXPLORER_TAG, "exchange")


# -- every kind -----------------------------------------------------------------------
@pytest.mark.parametrize("result", [labelled(), HOT_WALLET, EXPLORER_TAG, INFERRED])
def test_no_letter_claims_funds_nobody_reported_or_a_channel_nobody_checked(result):
    text = draft("case-1", result, "exchange")
    assert "reported funds" not in text
    assert "victim reported" not in text
    assert "published law-enforcement channel" not in text
    assert "The victim's payments: [____" in text
    assert "officer to state" in text


@pytest.mark.parametrize("result", [labelled(), HOT_WALLET, EXPLORER_TAG, INFERRED])
def test_every_letter_stays_a_draft_with_the_legal_basis_left_to_the_officer(result):
    text = draft("case-1", result, "exchange")
    assert text.startswith("DRAFT")
    assert "In exercise of the powers under [____" in text and "officer to confirm" in text
    assert "This request identifies an address, not a person." in text


def test_the_tether_letter_no_longer_says_who_reported_what():
    text = draft("case-1", case(chain="tron", chain_name="Tron", asset="USDT"), "tether")
    assert "victim reported" not in text
    assert "The victim's payments: [____" in text
    assert TX in text


def test_reports_do_not_claim_funds_nobody_reported_either():
    prorata = {"status": "estimated", "estimated": 9.5, "sent": 10.0, "arrived_total": 12.0,
               "hops": [{"address": "0xhop", "victim_share": 0.8, "received_in_window": 12.0}]}
    report = build_report(stored({**full_result(), "prorata": prorata}))
    text = render_text_report(report)
    assert "about 9.5 of 10.0 ETH sent from the reported address" in " ".join(text.split())
    assert "eported funds" not in text
    assert "eported funds" not in "".join(p.extract_text() for p in PdfReader(io.BytesIO(render_pdf(report, text))).pages)


def test_the_letters_offered_are_unchanged():
    assert available(labelled()) == [{"to": "exchange", "title": "Request to Binance"}]
