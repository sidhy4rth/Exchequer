"""The report and the letters say how the trace started.

Before (r2-g2-frontend-intake-rendering-3-4), a trace from the victim's
verified payments and an exploratory one from the address alone produced
identical reports: the UI's "Exploratory: can include other people's money"
caveat never reached the documents police and exchanges act on, and the
letter left the victim's payments blank even when the case held them. The
NCRP number and the victim's own wallet are particulars: no export carries them.
"""
from __future__ import annotations

import io
import json

from pypdf import PdfReader

from app.report import build_report, render_text_report
from app.report_pdf import render_pdf
from app.request_letters import draft

from test_report import SEED, full_result, stored
from test_request_letters import case

PAY1, PAY2 = "0x" + "a1" * 32, "0x" + "a2" * 32
PAYMENTS = [
    {"tx_hash": PAY1, "chain": "ethereum", "asset": "ETH", "amount": 1.5, "from": "0xvictim", "to": SEED,
     "block": 100, "timestamp": 1_700_000_000, "found_by": "victim"},
    {"tx_hash": PAY2, "chain": "ethereum", "asset": "ETH", "amount": 1.0, "from": "0xvictim", "to": SEED,
     "block": 101, "timestamp": 1_700_000_100, "found_by": "officer_search"},
]
INTAKE = {"mode": "payment", "payments": PAYMENTS, "ncrp_ack": "NCRP-123456"}


def paid(result: dict) -> dict:
    return {**result, "intake": INTAKE, "reported_amount": 2.5}


def test_an_address_mode_report_says_it_is_exploratory():
    report = build_report(stored(full_result()))
    assert report["intake"]["mode"] == "address"
    text = render_text_report(report)
    started = next(line for line in text.split("\n") if line.startswith("Started from     : "))
    assert "EXPLORATORY" in started and "other people's money" in started


def test_a_payment_report_lists_the_payments_and_the_reported_amount():
    report = build_report(stored(paid(full_result())))
    assert report["intake"]["mode"] == "payment" and report["intake"]["reported_amount"] == 2.5
    assert [p["tx_hash"] for p in report["intake"]["payments"]] == [PAY1, PAY2]
    text = render_text_report(report)
    assert "Started from     : 2 victim payments, 2.5 ETH in all" in text
    assert "VICTIM'S PAYMENTS (VERIFIED ON CHAIN)" in text
    assert PAY1 in text and PAY2 in text
    flat = " ".join(" ".join(report["methodology"]).split())
    assert "from when the first of the victim's payments arrived" in flat


def test_no_export_carries_the_ncrp_number_or_the_victims_wallet():
    result = paid(full_result())
    report = build_report(stored(result))
    text = render_text_report(report)
    pdf = PdfReader(io.BytesIO(render_pdf(report, text)))
    pdf_text = "".join(page.extract_text() for page in pdf.pages)
    letters = [draft("case-1", paid(case()), "exchange"), draft("case-1", paid(case(asset="USDT")), "tether")]
    for export in (json.dumps(report), text, pdf_text, *letters):
        assert "NCRP-123456" not in export
        assert "0xvictim" not in export


def test_page_one_says_how_the_trace_started():
    for result, expected in ((full_result(), "EXPLORATORY"), (paid(full_result()), "2 victim payments")):
        report = build_report(stored(result))
        first = PdfReader(io.BytesIO(render_pdf(report, render_text_report(report)))).pages[0].extract_text()
        assert "Started from" in first and expected in first


def test_a_payment_case_letter_states_the_verified_payments():
    text = draft("case-1", paid(case()), "exchange")
    assert "as verified on chain: 2 transfers, 2.5 ETH in all" in text
    assert PAY1 in text and PAY2 in text
    assert "Reference : [____" in text  # the complaint's reference stays the officer's


def test_an_address_mode_letter_says_the_trace_followed_the_address():
    text = draft("case-1", case(), "exchange")
    assert "followed the reported address's history, not specific payments" in text
    assert "The victim's payments: [____" in text


# ---------------------------------------------------------------------------
# An exploratory case's letters say the figure is an upper bound
# (r2-g2-frontend-intake-rendering-3-4, round 2). The exchange letter's
# pro-rata figure read as the victim's money: nothing called the trace
# exploratory or the figure an upper bound.
# ---------------------------------------------------------------------------
from test_request_letters import PRORATA  # noqa: E402

USDT_TRON = {"asset": "USDT", "chain": "tron", "chain_name": "Tron"}


def _flat(letter: str) -> str:
    return " ".join(letter.split())


def test_an_exploratory_exchange_letter_calls_its_figure_an_upper_bound():
    letter = _flat(draft("case-1", case(asset="USDT", prorata=PRORATA), "exchange"))
    assert "exploratory" in letter.lower()
    assert "other people's money" in letter
    assert "upper bound" in letter
    # The amount paragraph itself says so, not only the opening.
    amount = letter[letter.index("On a pro-rata estimate"):letter.index("your own records")]
    assert "upper bound" in amount and "exploratory" in amount.lower()


def test_an_exploratory_tether_letter_says_the_amounts_are_an_upper_bound():
    letter = _flat(draft("case-1", case(**USDT_TRON, prorata=PRORATA), "tether"))
    assert "exploratory" in letter.lower()
    assert "other people's money" in letter
    assert "upper bound" in letter


def test_payment_case_letters_do_not_call_themselves_exploratory():
    for to, over in (("exchange", {"asset": "USDT"}), ("tether", USDT_TRON)):
        result = {**case(**over, prorata=PRORATA), "intake": {**INTAKE, "payments": [
            {**p, "asset": "USDT"} for p in PAYMENTS]}, "reported_amount": 2.5}
        letter = _flat(draft("case-1", result, to)).lower()
        assert "exploratory" not in letter and "upper bound" not in letter
        assert "other people's money" not in letter
