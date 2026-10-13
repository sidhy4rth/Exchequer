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
    assert "Binance" in first and "0xbin" in first and "0.88 (high)" in first
    assert "Tornado Cash" in first
    everything = "".join(p.extract_text() for p in reader.pages)
    assert "Part 2" in everything and "CONTENT HASH" in everything


def test_the_attached_text_is_byte_exact_and_verifies():
    reader = PdfReader(io.BytesIO(render_pdf(REPORT, TEXT)))
    (name, [data]), = reader.attachments.items()
    assert name == "exchequer-abcd1234.txt"
    assert data.decode() == TEXT
    assert verify_report(data.decode())["signature_ok"]


def test_a_case_with_no_exchange_still_renders():
    report = {**REPORT, "attribution": {}, "confidence": {}, "trace_path": [],
              "risk_screening": {"screened": False}}
    assert render_pdf(report, TEXT)[:5] == b"%PDF-"
