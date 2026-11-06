"""The PDF report (app/report_pdf.py): a summary page, the signed text, the exact file attached."""
from __future__ import annotations

import io

from pypdf import PdfReader

from app.evidence import seal_text
from app.report_pdf import render_pdf
from app.signing import verify_report

REPORT = {
    "case": {"case_id": "abcd1234-0000-0000-0000-000000000000", "reported_address": "0xseed",
             "traced_at": "2026-10-13T07:21:28+00:00", "chain": "Ethereum Mainnet", "asset": "ETH",
             "direction": "outgoing"},
    "summary": "The ETH sent out of 0xseed reached Binance.",
    "attribution": {"exchange": "Binance", "exchange_address": "0xbin", "hop_count": 2,
                    "exchange_wallet_label": "Binance 14", "value_currency": "ETH",
                    "prorata": {"status": "estimated", "estimated": 9.5, "sent": 10}},
    "confidence": {"score": 0.875, "band": "high", "summary": "High confidence."},
    "risk_screening": {"screened": True, "matches": [
        {"category": "mixer", "address": "0xtornado", "entity": "Tornado Cash"}]},
    "trace_path": [{"address": "0xseed", "depth": 0}, {"address": "0xbin", "depth": 1, "value_native": 9.5}],
    "limitations": ["One", "Two", "Three", "Four"],
}
TEXT = seal_text("EXCHEQUER - CRYPTOCURRENCY TRACE REPORT\nCase ID : abcd1234\n" + "x" * 200)


def test_pdf_has_summary_and_signed_text():
    pdf = render_pdf(REPORT, TEXT)
    reader = PdfReader(io.BytesIO(pdf))
    first = reader.pages[0].extract_text()
    assert "Binance" in first and "0xbin" in first
    # R10: the summary page shows the band, never the decimal.
    assert "High (a rule of three inputs, not a probability)" in first and "0.88" not in first
    assert "Tornado Cash" in first
    everything = "".join(p.extract_text() for p in reader.pages)
    assert "Part 2" in everything and "CONTENT HASH" in everything


def test_the_attached_text_is_byte_exact_and_verifies():
    reader = PdfReader(io.BytesIO(render_pdf(REPORT, TEXT)))
    (name, [data]), = reader.attachments.items()
    assert name == "exchequer-abcd1234.txt"
    assert data.decode() == TEXT
    assert verify_report(data.decode())["signature_ok"]


LISTS = {"as_of": "2026-10-13", "stale_after_days": 7, "not_held": [], "warning": None, "lists": [
    {"name": "OFAC SDN list", "file": "risk_labels.json", "checked": "2026-10-12", "published": "2026-10-10",
     "state": "current", "note": ""}]}
RED_INK = b".701961 .14902 .117647"  # report_pdf.RED, as the page's drawing commands write it


def first_page(report: dict) -> tuple[str, bytes]:
    page = PdfReader(io.BytesIO(render_pdf(report, TEXT))).pages[0]
    return page.extract_text(), page.get_contents().get_data()


def test_page_one_prints_the_list_dates_and_no_red_when_they_are_fresh():
    report = {**REPORT, "screening_lists": LISTS, "risk_screening": {"screened": True, "matches": []}}
    text, drawing = first_page(report)
    assert "OFAC SDN list" in text and "2026-10-12" in text
    assert "WARNING" not in text
    assert RED_INK not in drawing


def test_an_old_list_puts_a_red_warning_on_page_one():
    warning = "Screening may have missed addresses listed recently."
    report = {**REPORT, "screening_lists": {**LISTS, "warning": warning},
              "risk_screening": {"screened": True, "matches": []}}
    text, drawing = first_page(report)
    assert "WARNING" in text and "may have missed" in text
    assert RED_INK in drawing


def test_a_case_with_no_exchange_still_renders():
    report = {**REPORT, "attribution": {}, "confidence": {}, "trace_path": [],
              "risk_screening": {"screened": False}}
    assert render_pdf(report, TEXT)[:5] == b"%PDF-"


def test_page_one_says_when_pro_rata_was_not_estimated():
    # Audit r2-g2-documented-claims-vs-code-7-2: the limitation was only in the text.
    report = {**REPORT, "attribution": {**REPORT["attribution"], "prorata": {
        "status": "unknown", "reason": "0xmid received too many transfers in the window to read in full"}}}
    text, _ = first_page(report)
    assert "not estimated" in text and "too many transfers" in " ".join(text.split())
