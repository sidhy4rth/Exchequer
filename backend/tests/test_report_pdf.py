"""The PDF report (app/report_pdf.py): a summary page, the signed text, the exact file attached."""
from __future__ import annotations

import io

from pypdf import PdfReader

from app.evidence import seal_text
from app.report import build_report, render_text_report
from app.report_pdf import render_pdf
from app.signing import verify_report

from test_report import MID, full_result, stored

CASE_ID = "abcd1234-0000-0000-0000-000000000000"
MIXER = "0x" + "70" * 20
MIXER_NOTE = (f"Mixer: {MIXER} is Tornado Cash, per OFAC SDN list. It received 1.0000 ETH within this "
              "trace, 1 hop from the reported address. The trace stops here.")


def _report(result: dict | None = None, **over) -> dict:
    """A real report: page 1 is drawn from its signed text alone (r1-evidence-crypto-6),
    so a test changes the report and renders the text from it."""
    case = stored(result or full_result())
    case.id = CASE_ID
    report = build_report(case)
    report["case"]["traced_at"] = "2026-10-13T07:21:28+00:00"
    report["risk_screening"] = {"screened": True, "categories": ["mixer"], "notes": [MIXER_NOTE],
                                "matches": [{"category": "mixer", "address": MIXER, "entity": "Tornado Cash"}]}
    report.update(over)
    return report


def _pdf(report: dict) -> bytes:
    return render_pdf(report, render_text_report(report))


REPORT = _report()


def test_pdf_has_summary_and_signed_text():
    result = full_result()
    result["confidence_detail"]["summary"] = "High confidence that funds reached Binance."
    reader = PdfReader(io.BytesIO(_pdf(_report(result))))
    first = reader.pages[0].extract_text()
    assert "Binance" in first and MID in first
    # R10: the summary page shows the band, never the decimal.
    assert "High (a rule of three inputs, not a probability)" in first and "0.88" not in first
    assert "Tornado Cash" in first and MIXER in first
    everything = "".join(p.extract_text() for p in reader.pages)
    assert "Part 2" in everything and "CONTENT HASH" in everything


def test_the_attached_text_is_byte_exact_and_verifies():
    text = render_text_report(REPORT)
    reader = PdfReader(io.BytesIO(render_pdf(REPORT, text)))
    (name, [data]), = reader.attachments.items()
    assert name == "exchequer-abcd1234.txt"
    assert data.decode() == text
    assert verify_report(data.decode())["signature_ok"]


def test_a_text_this_version_cannot_read_gets_a_short_page_one():
    # Nothing but the signed text reaches page 1: a stand-in text gives the short page.
    text = seal_text("EXCHEQUER - CRYPTOCURRENCY TRACE REPORT\nCase ID : abcd1234\n" + "x" * 200)
    first = PdfReader(io.BytesIO(render_pdf(REPORT, text))).pages[0].extract_text()
    assert "could not be drawn from the signed report" in " ".join(first.split())
    assert "Binance" not in first


LISTS = {"as_of": "2026-10-13", "stale_after_days": 7, "not_held": [], "warning": None, "lists": [
    {"name": "OFAC SDN list", "file": "risk_labels.json", "checked": "2026-10-12", "published": "2026-10-10",
     "state": "current", "note": ""}]}
RED_INK = b".701961 .14902 .117647"  # report_pdf.RED, as the page's drawing commands write it
NO_MATCHES = {"screened": True, "categories": [], "matches": [], "notes": []}


def first_page(report: dict) -> tuple[str, bytes]:
    page = PdfReader(io.BytesIO(_pdf(report))).pages[0]
    return page.extract_text(), page.get_contents().get_data()


def test_page_one_prints_the_list_dates_and_no_red_when_they_are_fresh():
    report = _report(screening_lists=LISTS, risk_screening=NO_MATCHES)
    text, drawing = first_page(report)
    assert "OFAC SDN list" in text and "2026-10-12" in text
    assert "WARNING" not in text
    assert RED_INK not in drawing


def test_page_one_names_what_was_not_screened():
    """A summary that names only what was held reads as if nothing was left out (r1-labels-data-9)."""
    report = _report(screening_lists={**LISTS, "not_held": ["Flagged-address label store"]},
                     risk_screening=NO_MATCHES)
    text = " ".join(first_page(report)[0].split())
    assert "so not screened: Flagged-address label store" in text


def test_an_old_list_puts_a_red_warning_on_page_one():
    warning = "Screening may have missed addresses listed recently."
    report = _report(screening_lists={**LISTS, "warning": warning}, risk_screening=NO_MATCHES)
    text, drawing = first_page(report)
    assert "WARNING" in text and "may have missed" in text
    assert RED_INK in drawing


def test_a_case_with_no_exchange_still_renders():
    result = full_result()
    result.update(exchange=None, exchange_address=None, exchange_label=None, attribution_inferred=False,
                  trace_path=[], confidence=None)
    pdf = _pdf(_report(result, risk_screening=NO_MATCHES))
    assert pdf[:5] == b"%PDF-"
    assert "No exchange reached" in PdfReader(io.BytesIO(pdf)).pages[0].extract_text()


def test_page_one_says_when_pro_rata_was_not_estimated():
    # Audit r2-g2-documented-claims-vs-code-7-2: the limitation was only in the text.
    report = _report()
    report["attribution"]["prorata"] = {
        "status": "unknown", "reason": "0xmid received too many transfers in the window to read in full"}
    text, _ = first_page(report)
    assert "not estimated" in text and "too many transfers" in " ".join(text.split())


def test_page_one_states_a_capped_figure_as_capped():
    # Audit r1-attribution-integrity-7: never "sent from the reported address" for the victim's share.
    report = build_report(stored(full_result()))
    prorata = {**(report["attribution"].get("prorata") or {}), "status": "estimated", "estimated": 2.0,
               "sent": 50.0, "arrived_total": 40.0, "hops": [],
               "seed_cap": {"amount": 2.0, "basis": "reported_amount", "applied": True}}
    report = {**report, "attribution": {**report["attribution"], "prorata": prorata}}
    page = PdfReader(io.BytesIO(render_pdf(report, render_text_report(report)))).pages[0]
    text = " ".join(page.extract_text().split())
    assert "at most what the victim reported paying" in text and "about 2.0 of the 2.0" in text
    assert "sent from the reported address (pro-rata)" not in text


# -- page 1 is a reading aid, and says so (r1-evidence-crypto-6) ----------------------
def _real_report() -> tuple[dict, str]:
    report = build_report(stored(full_result()))
    return report, render_text_report(report)


def test_page_one_says_it_is_not_signed():
    report, text = _real_report()
    first = " ".join(PdfReader(io.BytesIO(render_pdf(report, text))).pages[0].extract_text().split())
    assert "NOT SIGNED" in first
    assert "not covered by the signature" in first
    assert "any edit breaks the signature" not in first


def test_page_one_prints_the_signed_finding_not_a_different_one():
    report, text = _real_report()
    genuine = report["attribution"]["exchange_address"]
    forged = {**report, "attribution": {**report["attribution"], "exchange": "Kraken",
                                        "exchange_address": "0x" + "f0" * 20}}
    first = PdfReader(io.BytesIO(render_pdf(forged, text))).pages[0].extract_text()
    assert genuine in first and "0x" + "f0" * 20 not in first
    assert "Binance" in first and "Kraken" not in first
