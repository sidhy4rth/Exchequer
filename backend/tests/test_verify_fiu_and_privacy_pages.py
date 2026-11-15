"""/verify on two PDFs no test ran through it before (#193 review questions).

1. EXCHEQUER_FIU_IND_NOTE on (#291, #295): the signed FINDING carries
   "FIU-IND :" and "FIU-IND source :" lines. Page 1 does not print the note
   (it is drawn from the finding's other fields); Part 2 prints it, each source
   URL whole on its line. Such a PDF must read genuine with its pages matching,
   and a PDF with an FIU-IND line put on page 1 or altered in Part 2 must not.
2. A privacy section that starts on page 2 (#288, #299): a PDF issued with an
   earlier privacy lede, for a report generated before that lede's cut-off,
   must still verify even when the lede is not on page 1.
No network: fixed results and a real trace over a fake provider.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.platypus import Paragraph

from app import config, fiu_ind_status, report_pdf
from app.main import app
from app.report import build_report, render_text_report
from app.report_pdf import PRIVACY_LEDES, render_issued, render_pdf

from test_fiu_ind_note_outputs import _report
from test_fiu_ind_status import LS_5805, PIB_DEC_2023
from test_privacy_category import trace  # noqa: F401 -- fixture used by railgun_case
from test_privacy_report import _case, flag, railgun_case  # noqa: F401 -- fixtures

client = TestClient(app)
BINANCE_ORDER = "https://fiuindia.gov.in/pdfs/judgements/Binance_Order_10_2024.pdf"
PRIVACY_HEADING = "PRIVACY PROTOCOLS ON THE PATH"


def _verify(pdf: bytes) -> dict:
    response = client.post("/verify", content=pdf, headers={"Content-Type": "application/pdf"})
    assert response.status_code == 200, response.text
    return response.json()


def _pages(pdf: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages]


# -- 1. the FIU-IND note -------------------------------------------------------------
@pytest.fixture
def on(monkeypatch):
    fiu_ind_status.clear_cache()
    monkeypatch.setattr(config, "FIU_IND_NOTE", True)
    yield
    fiu_ind_status.clear_cache()


def _issued(exchange: str) -> tuple[str, bytes]:
    report = _report(exchange)
    text = render_text_report(report)
    return text, render_pdf(report, text)


@pytest.mark.parametrize(("exchange", "urls", "said"), [
    ("Kraken", [LS_5805, PIB_DEC_2023], "Kraken was not on FIU-IND's list"),
    ("Binance", [LS_5805, PIB_DEC_2023, BINANCE_ORDER], "FIU-IND imposed a penalty of Rs 18,82,00,000"),
])
def test_a_flag_on_report_pdf_verifies_genuine_with_pages_matching(on, exchange, urls, said):
    text, pdf = _issued(exchange)
    assert "FIU-IND          : " in text and said in " ".join(text.split())
    assert fiu_ind_status.note(exchange)["sources"] == urls
    checked = _verify(pdf)
    assert checked["status"] == "genuine" and checked["pdf"]["pages_match"] is True, checked["pdf"]["problems"]


@pytest.mark.parametrize("exchange", ["Kraken", "Binance"])
def test_each_source_url_stays_whole_on_one_printed_line(on, exchange):
    _, pdf = _issued(exchange)
    pages = _pages(pdf)
    assert "FIU-IND" not in pages[0].split("Part 2 · The signed text report")[0]  # page 1 does not print it
    lines = [line for page in pages for line in page.split("\n")]
    for url in fiu_ind_status.note(exchange)["sources"]:
        assert any(line.strip() == f"FIU-IND source   : {url}" for line in lines), url


def _with_part_one(monkeypatch, line: str) -> bytes:
    original = report_pdf._part_one
    monkeypatch.setattr(report_pdf, "_part_one", lambda *a, **k: (lambda story: story[:6] + [
        Paragraph(line, report_pdf._styles()["cell"])] + story[6:])(original(*a, **k)))
    try:
        return _issued("Kraken")[1]
    finally:
        monkeypatch.setattr(report_pdf, "_part_one", original)


@pytest.mark.parametrize("line", [
    # The signed note's sense reversed, and the signed note itself: page 1 prints neither.
    "FIU-IND: Kraken was on FIU-IND's list of registered VDA service providers as of 9 Mar 2026.",
    "FIU-IND: Kraken was not on FIU-IND's list of registered VDA service providers as of 9 Mar 2026.",
], ids=["reversed", "copied"])
def test_an_fiu_ind_line_on_page_one_reads_summary_differs(on, monkeypatch, line):
    checked = _verify(_with_part_one(monkeypatch, line))
    assert checked["status"] == "summary_differs", checked
    assert "FIU-IND" in " ".join(checked["pdf"]["problems"])


@pytest.mark.parametrize(("old", "new"), [
    ("Kraken was not on FIU-IND's list", "Kraken was on FIU-IND's list"),
    (PIB_DEC_2023, PIB_DEC_2023.replace("1991372", "1991373")),
], ids=["note", "source-url"])
def test_an_fiu_ind_line_altered_in_part_two_reads_printed_copy_differs(on, monkeypatch, old, new):
    original = report_pdf._part_two
    monkeypatch.setattr(report_pdf, "_part_two", lambda text, st: original(text.replace(old, new), st))
    checked = _verify(_issued("Kraken")[1])
    assert checked["status"] == "printed_copy_differs", checked
    assert "Part 2" in " ".join(checked["pdf"]["problems"])


# -- 2. a privacy section that starts on page 2 --------------------------------------
def _long_case(result: dict, generated_at: str) -> tuple[str, str]:
    """The Railgun case with enough screening notes above the privacy section to push it onto page 2."""
    path = [step["address"] for step in result["trace_path"]]
    listed = [(0, path[0]), (1, path[1]), (3, path[3])]
    notes = [f"Phishing or scam: {address} named by {source}, {hop} hops from the reported address. A list "
             "entry is a lead for the investigating officer, not a finding that anyone at this address "
             "committed an offence."
             for source in ("HF ethereum_fraud_dataset (fesevu, CC BY 4.0)", "Etherscan address tag")
             for hop, address in listed]
    matches = [{"address": address, "category": "scam", "entity": "phishing", "label": "phishing",
                "source": "HF ethereum_fraud_dataset (fesevu, CC BY 4.0)", "origin": "label_store",
                "depth": hop} for hop, address in listed]
    result = {**result, "risk_flags": ["scam"], "risk_matches": matches, "risk_notes": notes}
    report = build_report(_case(result), generated_at=generated_at)
    return render_text_report(report), report["case"]["case_id"]


def _on_page_two(pdf: bytes, lede: str) -> None:
    pages = [" ".join(page.split()) for page in _pages(pdf)]
    assert PRIVACY_HEADING not in pages[0] and PRIVACY_HEADING in pages[1]
    assert lede in pages[1] and lede not in pages[0]


BEFORE = "2026-11-14T10:00:00+00:00"  # before both cut-offs in report_pdf.LEDE_REPLACED_AT


@pytest.mark.parametrize("lede", PRIVACY_LEDES, ids=["newest", "279", "before-279"])
def test_a_pdf_whose_privacy_lede_is_on_page_two_verifies(railgun_case, lede):  # noqa: F811 -- the imported fixture
    text, case_id = _long_case(railgun_case, BEFORE)
    pdf = render_issued(text, case_id, privacy_lede=lede)
    _on_page_two(pdf, lede)
    checked = _verify(pdf)
    assert checked["status"] == "genuine" and checked["pdf"]["pages_match"] is True, checked["pdf"]["problems"]


@pytest.mark.parametrize("lede", PRIVACY_LEDES[1:], ids=["279", "before-279"])
def test_an_earlier_lede_on_page_two_after_its_cut_off_still_reads_differs(railgun_case, lede):  # noqa: F811 -- the imported fixture
    text, case_id = _long_case(railgun_case, "2026-11-15T23:00:00+05:30")
    pdf = render_issued(text, case_id, privacy_lede=lede)
    _on_page_two(pdf, lede)
    assert _verify(pdf)["status"] == "summary_differs"


def test_an_unknown_lede_on_page_two_reads_differs(railgun_case):  # noqa: F811 -- the imported fixture
    lede = PRIVACY_LEDES[2].replace("did not stop there", "stopped there")
    text, case_id = _long_case(railgun_case, BEFORE)
    pdf = render_issued(text, case_id, privacy_lede=lede)
    _on_page_two(pdf, lede)
    assert _verify(pdf)["status"] == "summary_differs"
