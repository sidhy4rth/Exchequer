"""/verify takes the PDF itself, and says when its pages differ from the signed record.

Before (r1-evidence-crypto-6, round 2): only the attached text is signed, and
/verify took only text. The verifier took page 1 from a render naming another
address, kept the genuine PDF's other pages and attachment, extracted the
attachment, and /verify said "genuine": a doctored summary page was caught
only by a reader who compared it by hand with what /verify printed.

The owner chose (8 Nov) not to sign the PDF itself (no new crypto
dependency). So page 1 stays unsigned and says so, and /verify now reads an
uploaded PDF: it checks the attached text as before, then compares what the
pages show (case, exchange, address, amount, the NOT SIGNED notice, every
address and amount on page 1, the footers and the printed copy) with that
signed text, and names what differs.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app import report_pdf
from app.main import app
from app.models import Case
from app.report import build_report, render_text_report
from app.report_pdf import render_pdf

from test_attribution_by_share import trace  # noqa: F401 -- the fixture: a real run_trace over a fake provider
from test_report import MID, full_result, stored

client = TestClient(app)
OTHER = "0x" + "9" * 40
PRORATA = {"status": "estimated", "estimated": 2.0, "sent": 10.0, "arrived_total": 9.5, "hops": []}


def _result(**over) -> dict:
    result = full_result()
    result["prorata"] = dict(PRORATA)
    result.update(over)
    return result


def _render(result: dict, case_id: str = "case-1") -> bytes:
    case = stored(result)
    case.id = case_id
    report = build_report(case)
    return render_pdf(report, render_text_report(report))


def _naming(address: str) -> dict:
    result = _result(exchange_address=address)
    result["trace_path"][1]["address"] = address
    result["inferred_deposits"][0]["address"] = address
    return result


def _splice(pages_from: bytes, n_first: int, rest_from: bytes, attachment_from: bytes) -> bytes:
    """The first `n_first` pages of one PDF, the rest of another, and a third's attachment."""
    first, rest, attached = (PdfReader(io.BytesIO(b)) for b in (pages_from, rest_from, attachment_from))
    writer = PdfWriter()
    for page in first.pages[:n_first]:
        writer.add_page(page)
    for page in rest.pages[n_first:]:
        writer.add_page(page)
    for name, datas in attached.attachments.items():
        for data in datas:
            writer.add_attachment(name, data)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _verify(pdf: bytes) -> dict:
    response = client.post("/verify", content=pdf, headers={"Content-Type": "application/pdf"})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def genuine() -> bytes:
    return _render(_result())


def test_a_genuine_pdf_is_genuine_and_its_pages_match(genuine):
    result = _verify(genuine)
    assert result["status"] == "genuine" and result["genuine"] is True
    assert result["pdf"]["pages_match"] is True and result["pdf"]["problems"] == []
    assert result["finding"]["address"] == MID
    assert "match" in result["detail"]


def test_the_verifiers_probe_a_swapped_page_one_is_caught(genuine):
    # Page 1 from a render naming 0x9999…, the genuine PDF's other pages and attachment.
    doctored = _splice(_render(_naming(OTHER)), 1, genuine, genuine)
    result = _verify(doctored)
    assert result["status"] == "summary_differs"
    assert result["genuine"] is False
    assert result["signature_ok"] is True  # the attachment itself is genuine...
    assert result["finding"]["address"] == MID  # ...and says what the signed record states
    problems = " ".join(result["pdf"]["problems"])
    assert MID in problems and OTHER in problems
    assert "page 1" in result["detail"].lower()


def test_a_page_one_stating_another_amount_is_caught(genuine):
    doctored = _splice(_render(_result(prorata={**PRORATA, "estimated": 7.0})), 1, genuine, genuine)
    result = _verify(doctored)
    assert result["status"] == "summary_differs"
    assert "about 2.0 of the 10.0 ETH this wallet sent on this route" in " ".join(result["pdf"]["problems"])


def test_a_page_one_naming_another_exchange_is_caught(genuine):
    other = _result(exchange="Kraken")
    other["inferred_deposits"][0]["exchange"] = "Kraken"
    result = _verify(_splice(_render(other), 1, genuine, genuine))
    assert result["status"] == "summary_differs"
    assert "Binance" in " ".join(result["pdf"]["problems"])


def test_a_page_one_from_another_case_is_caught(genuine):
    result = _verify(_splice(_render(_result(), case_id="case-2"), 1, genuine, genuine))
    assert result["status"] == "summary_differs"
    assert "case-1" in " ".join(result["pdf"]["problems"])


def _with_part_one(monkeypatch, change) -> bytes:
    original = report_pdf._part_one
    monkeypatch.setattr(report_pdf, "_part_one", lambda *a, **k: change(original(*a, **k)))
    try:
        return _render(_result())
    finally:
        monkeypatch.setattr(report_pdf, "_part_one", original)


def test_a_page_one_without_the_not_signed_notice_is_caught(monkeypatch):
    pdf = _with_part_one(monkeypatch, lambda story: [f for f in story if "NOT SIGNED" not in getattr(f, "text", "")])
    result = _verify(pdf)
    assert result["status"] == "summary_differs"
    assert "NOT SIGNED" in " ".join(result["pdf"]["problems"])


def test_an_address_added_beside_the_genuine_one_is_caught(monkeypatch):
    # The genuine address is still on the page; the extra one is what a reader would act on.
    from reportlab.platypus import Paragraph

    pdf = _with_part_one(monkeypatch, lambda story: story[:6] + [
        Paragraph(f"Ask instead about {OTHER}", report_pdf._styles()["cell"])] + story[6:])
    result = _verify(pdf)
    assert result["status"] == "summary_differs"
    assert OTHER in " ".join(result["pdf"]["problems"])


def test_an_amount_added_to_page_one_is_caught(monkeypatch):
    from reportlab.platypus import Paragraph

    pdf = _with_part_one(monkeypatch, lambda story: story[:6] + [
        Paragraph("Freeze 4,321.75 ETH", report_pdf._styles()["cell"])] + story[6:])
    result = _verify(pdf)
    assert result["status"] == "summary_differs"
    assert "4,321.75" in " ".join(result["pdf"]["problems"])


def test_an_image_on_page_one_is_caught(monkeypatch, tmp_path):
    # Text drawn as a picture cannot be read and compared; a genuine summary has none.
    from PIL import Image as Picture
    from reportlab.platypus import Image

    png = tmp_path / "dot.png"
    Picture.new("RGB", (4, 4), "white").save(png)
    pdf = _with_part_one(monkeypatch, lambda story: story[:6] + [Image(str(png), 20, 20)] + story[6:])
    result = _verify(pdf)
    assert result["status"] == "summary_differs"
    assert "image" in " ".join(result["pdf"]["problems"])


def test_an_edited_printed_copy_is_caught(monkeypatch):
    original = report_pdf._part_two
    monkeypatch.setattr(report_pdf, "_part_two", lambda text, st: original(text.replace(MID, OTHER), st))
    result = _verify(_render(_result()))
    assert result["status"] == "printed_copy_differs"
    assert result["genuine"] is False
    assert "Part 2" in " ".join(result["pdf"]["problems"])


def test_a_changed_attachment_is_judged_on_the_attachment(genuine):
    reader = PdfReader(io.BytesIO(genuine))
    (name, [data]), = reader.attachments.items()
    rebuilt = PdfWriter()
    for page in reader.pages:
        rebuilt.add_page(page)
    rebuilt.add_attachment(name, data.replace(MID.encode(), OTHER.encode()))
    out = io.BytesIO()
    rebuilt.write(out)
    result = _verify(out.getvalue())
    assert result["status"] == "changed"
    assert result["pdf"]["pages_match"] is None  # not compared: the record itself fails


def test_a_pdf_with_no_attachment_or_two_is_not_a_report(genuine):
    reader = PdfReader(io.BytesIO(genuine))
    (name, [data]), = reader.attachments.items()
    for extra in ([], [(name, data), ("exchequer-other.txt", data)]):
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        for n, d in extra:
            writer.add_attachment(n, d)
        out = io.BytesIO()
        writer.write(out)
        result = _verify(out.getvalue())
        assert result["status"] == "pdf_no_report" and result["genuine"] is False


def test_a_damaged_pdf_is_unreadable_not_a_crash():
    result = _verify(b"%PDF-1.7\n" + b"\x00garbage" * 100)
    assert result["status"] == "pdf_unreadable" and result["genuine"] is False


def test_a_label_the_fonts_cannot_draw_still_matches():
    # A glyph missing from IBM Plex reads back from the PDF as a NUL: it is not an edit.
    weird = "币安 Binance ✓ “quoted” 🚀 café"
    result = _result(exchange_label=weird)
    result["trace_path"][1]["label"] = weird
    checked = _verify(_render(result))
    assert checked["status"] == "genuine", checked["pdf"]["problems"]


def test_a_summary_that_could_not_be_laid_out_still_verifies(monkeypatch):
    from reportlab.platypus.doctemplate import LayoutError

    original, calls = report_pdf._build, []

    def build(story, *a):
        calls.append(1)
        if len(calls) == 1:
            raise LayoutError("too tall")
        return original(story, *a)

    monkeypatch.setattr(report_pdf, "_build", build)
    checked = _verify(_render(_result()))
    assert checked["status"] == "genuine", checked["pdf"]["problems"]


def test_text_is_still_checked_as_text():
    text = render_text_report(build_report(stored(_result())))
    result = client.post("/verify", content=text.encode()).json()
    assert result["status"] == "genuine" and "pdf" not in result


def test_a_pdf_over_the_size_limit_is_refused():
    response = client.post("/verify", content=b"%PDF-1.7\n" + b"0" * 2_100_001,
                           headers={"Content-Type": "application/pdf"})
    assert response.status_code == 413


def test_a_payment_case_pdf_is_compared_too():
    from test_report_intake import paid

    checked = _verify(_render(paid(_result())))
    assert checked["status"] == "genuine" and checked["pdf"]["pages_match"] is True


def test_only_a_few_pdfs_are_read_at_once(monkeypatch, genuine):
    import threading

    from app import pdf_verify

    monkeypatch.setattr(pdf_verify, "READERS", threading.BoundedSemaphore(1))
    pdf_verify.READERS.acquire()
    response = client.post("/verify", content=genuine, headers={"Content-Type": "application/pdf"})
    assert response.status_code == 503 and "Try again" in response.json()["detail"]


def test_an_attachment_that_inflates_past_the_limit_is_refused_quickly():
    # 50 MB of one letter, compressed to about 50 KB: never inflated in full.
    import time
    import zlib

    from pypdf.generic import NameObject, StreamObject

    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.add_attachment("exchequer-bomb.txt", b"x")
    embedded = next(o for o in writer._objects
                    if isinstance(o, StreamObject) and o.get("/Type") == "/EmbeddedFile")
    embedded._data = zlib.compress(b"A" * 50_000_000, 9)
    embedded[NameObject("/Filter")] = NameObject("/FlateDecode")
    out = io.BytesIO()
    writer.write(out)
    started = time.monotonic()
    result = _verify(out.getvalue())
    assert result["status"] == "pdf_unreadable"
    assert time.monotonic() - started < 5


# -- page 1 must hold only what the renderer prints for the signed report (8 Nov check) ----
# The checker's V1 and V2: prose added to page 1, naming only an address the
# signed report already holds, or no address at all, passed every named check.

def _add_paragraph(text: str):
    from reportlab.platypus import Paragraph

    return lambda story: story[:3] + [Paragraph(text, report_pdf._styles()["cell"])] + story[3:]


def test_prose_naming_an_address_in_the_report_is_caught(monkeypatch):
    in_report = full_result()["trace_path"][0]["address"]  # the reported address: signed, and on page 1
    pdf = _with_part_one(monkeypatch, _add_paragraph(
        "ADDENDUM (supplementary trace, same case): the exchange has since confirmed the account holder; "
        f"also freeze every account holding {in_report} immediately and release no funds."))
    result = _verify(pdf)
    assert result["status"] == "summary_differs" and result["genuine"] is False
    assert "what Exchequer would print for the signed report" in " ".join(result["pdf"]["problems"])


def test_prose_naming_nothing_is_caught(monkeypatch):
    pdf = _with_part_one(monkeypatch, _add_paragraph(
        "ADDENDUM: Correction - the address below is superseded. Freeze all accounts of the holder "
        "and disclose KYC to the caller by phone."))
    result = _verify(pdf)
    assert result["status"] == "summary_differs"


def test_a_word_changed_on_page_one_is_caught(monkeypatch):
    # Only words: "Read with these limitations" becomes an instruction.
    from reportlab.platypus import Paragraph

    def change(story):
        return [Paragraph("FREEZE THE ACCOUNT NOW", report_pdf._styles()["micro"])
                if getattr(f, "text", "") == "READ WITH THESE LIMITATIONS" else f for f in story]

    result = _verify(_with_part_one(monkeypatch, change))
    assert result["status"] == "summary_differs"


def test_a_line_dropped_from_page_one_is_caught(monkeypatch):
    # A limitation left out is a page that says less than the signed report.
    result = _verify(_with_part_one(monkeypatch, lambda story: [
        f for f in story if not getattr(f, "text", "").startswith("•")]))
    assert result["status"] == "summary_differs"


def _with_annotation(pdf: bytes, annotation: dict, page: int = 0) -> bytes:
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject

    writer = PdfWriter(clone_from=io.BytesIO(pdf))
    annot = DictionaryObject({NameObject("/Type"): NameObject("/Annot"),
                              NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (50, 50, 300, 90)]),
                              **annotation})
    writer.pages[page][NameObject("/Annots")] = ArrayObject([writer._add_object(annot)])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _file_spec(writer_pdf: bytes):
    """A FileAttachment annotation's entries, carrying a second 'report'."""
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, TextStringObject

    def build(writer):
        stream = DecodedStreamObject()
        stream.set_data(b"FORGED CORRECTED REPORT\nfreeze 0xINNOCENT\n")
        stream.update({NameObject("/Type"): NameObject("/EmbeddedFile")})
        spec = DictionaryObject({NameObject("/Type"): NameObject("/Filespec"),
                                 NameObject("/F"): TextStringObject("corrected-report.txt"),
                                 NameObject("/EF"): DictionaryObject({NameObject("/F"): writer._add_object(stream)})})
        return {NameObject("/Subtype"): NameObject("/FileAttachment"), NameObject("/FS"): writer._add_object(spec),
                NameObject("/Contents"): TextStringObject("Corrected report")}
    return build


def test_a_second_file_attached_to_a_page_is_counted(genuine):
    # The checker's V4: the names tree held one file, page 1 a second.
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject

    for page in (0, -1):
        writer = PdfWriter(clone_from=io.BytesIO(genuine))
        annot = DictionaryObject({NameObject("/Type"): NameObject("/Annot"),
                                  NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (50, 50, 70, 70)]),
                                  **_file_spec(genuine)(writer)})
        writer.pages[page][NameObject("/Annots")] = ArrayObject([writer._add_object(annot)])
        out = io.BytesIO()
        writer.write(out)
        result = _verify(out.getvalue())
        assert result["status"] == "pdf_no_report" and result["genuine"] is False, page
        assert "2 attached files" in result["detail"]


def test_an_embedded_file_kept_outside_the_attachments_list_is_counted(genuine):
    # A file stream only some viewers list (here, a page's associated file):
    # every embedded file in the PDF counts.
    from pypdf.generic import ArrayObject, NameObject

    writer = PdfWriter(clone_from=io.BytesIO(genuine))
    spec = _file_spec(genuine)(writer)[NameObject("/FS")]
    writer.pages[0][NameObject("/AF")] = ArrayObject([spec])
    out = io.BytesIO()
    writer.write(out)
    result = _verify(out.getvalue())
    assert result["status"] == "pdf_no_report"


def test_text_added_as_an_annotation_is_caught(genuine):
    # A note or stamp drawn over page 1 is not in its text layer, so it could
    # never be compared: Exchequer adds none, and a PDF with one does not match.
    from pypdf.generic import NameObject, TextStringObject

    pdf = _with_annotation(genuine, {NameObject("/Subtype"): NameObject("/FreeText"),
                                     NameObject("/Contents"): TextStringObject("ADDENDUM: freeze every account"),
                                     NameObject("/DA"): TextStringObject("/Helv 12 Tf 0 g")})
    result = _verify(pdf)
    assert result["status"] == "summary_differs" and result["genuine"] is False
    assert "annotation" in " ".join(result["pdf"]["problems"])


def test_every_kind_of_genuine_page_one_matches():
    # Page 1 is re-rendered from the signed text, so every shape of case must
    # come out the same: no exchange, a capped figure, pro-rata not estimated,
    # a screening match, an old list, a payment case, an explorer tag.
    from test_letter_kinds import EXPLORER_TAG, HOT_WALLET, INFERRED
    from test_report_intake import paid

    no_exchange = _result(exchange=None, exchange_address=None, exchange_label=None, trace_path=[])
    capped = _result(prorata={**PRORATA, "seed_cap": {"amount": 2.0, "basis": "reported_amount", "applied": True}})
    unknown = _result(prorata={"status": "unknown", "reason": "0xmid received too many transfers"})
    for result in (no_exchange, capped, unknown, paid(_result()), EXPLORER_TAG, HOT_WALLET, INFERRED):
        checked = _verify(_render(result))
        assert checked["status"] == "genuine", checked["pdf"]["problems"]


def test_every_demo_pdf_matches():
    from test_letter_kinds import DEMOS

    for number, result in DEMOS.items():
        case = Case(id=f"demo-{number}", address=result["address"], created_at=result["created_at"],
                    result_json=json.dumps(result))
        report = build_report(case)
        checked = _verify(render_pdf(report, render_text_report(report)))
        assert checked["status"] == "genuine", (number, checked["pdf"]["problems"])


# -- the attribution facts on page 1 come from the signed text too ------------------------
ABCC, ALLBIT = "0x05f51aab068caa6ab7eeb672f88c180f67f17ec7", "0xdc1882f350b42ac9a23508996254b1915c78b204"


def _traced_pdf(trace, history) -> tuple[dict, bytes]:  # noqa: F811 -- the imported fixture
    result = trace(history)
    case = Case(id="c-share", address=result["address"], created_at="2026-11-08T00:00:00+00:00",
                result_json=json.dumps(result))
    report = build_report(case)
    return report, render_pdf(report, render_text_report(report))


def test_a_case_whose_funds_also_reached_other_exchanges_verifies_and_page_one_counts_them(trace):  # noqa: F811 -- the imported fixture
    from test_attribution_by_share import BASE, KRAKEN_1, T, W1, W2, _tx
    report, pdf = _traced_pdf(trace, BASE + [_tx(W1, KRAKEN_1, 100.0, T + 25), _tx(W1, ABCC, 100.0, T + 26),
                                             _tx(W2, ALLBIT, 100.0, T + 27)])
    others = report["attribution"]["also_reached"]
    assert len(others) >= 2, others
    checked = _verify(pdf)
    assert checked["status"] == "genuine" and checked["pdf"]["pages_match"] is True, checked["pdf"]["problems"]
    page = " ".join(PdfReader(io.BytesIO(pdf)).pages[0].extract_text().split())
    assert "Material funds also reached" in page and f"(and {len(others) - 1} more; see the signed report)" in page


def test_a_capped_share_case_verifies_and_page_one_gives_the_whole(trace):  # noqa: F811 -- the imported fixture
    from conftest import addr
    from test_attribution_by_share import BINANCE_14, SEED, T, _tx

    report, pdf = _traced_pdf(trace, [_tx(SEED, addr("ee11"), 10000.0, T + 10), _tx(SEED, BINANCE_14, 5.0, T + 20)])
    checked = _verify(pdf)
    assert checked["status"] == "genuine" and checked["pdf"]["pages_match"] is True, checked["pdf"]["problems"]
    page = " ".join(PdfReader(io.BytesIO(pdf)).pages[0].extract_text().split())
    assert "Share of the traced funds" in page and "of the 10,005 ETH" in page
    assert "Likely arrived, of what this wallet sent on this route (pro-rata)" in page


def test_an_also_reached_count_added_to_page_one_is_caught(trace, monkeypatch):  # noqa: F811 -- the imported fixture
    # The "(and N more)" count is read from the signed text; one written in from elsewhere differs.
    from reportlab.platypus import Paragraph
    from test_attribution_by_share import BASE, KRAKEN_1, W1, T, _tx

    original = report_pdf._part_one
    monkeypatch.setattr(report_pdf, "_part_one", lambda *a, **k: original(*a, **k) + [
        Paragraph("(and 3 more; see the signed report)", report_pdf._styles()["cell"])])
    _, pdf = _traced_pdf(trace, BASE + [_tx(W1, KRAKEN_1, 100.0, T + 25)])
    monkeypatch.setattr(report_pdf, "_part_one", original)
    assert _verify(pdf)["status"] == "summary_differs"
