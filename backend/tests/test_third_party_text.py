"""Third-party text in the evidence: one line, nothing hidden, every format intact.

Labels and explorer tags come from other people. Before, a TronScan tag with
newlines wrote a whole "FINDING (CORRECTED)" block into the signed report and
the server signed it; a label holding "\\nCONTENT HASH (" or "\\r\\n" made every
genuine report of the case fail /verify; a bidi override reordered an address;
a 3,000-character label broke the PDF with a LayoutError (500); one control
character made the GraphML export unopenable; and the CSV formula guard
skipped the source and target columns. (r1-evidence-crypto-2, -8, -10)
"""
from __future__ import annotations

import csv
import io

import networkx as nx
import pytest
from pypdf import PdfReader

from app import graph_export
from app.display_text import one_line, short
from app.evidence import seal_text
from app.report import build_report, render_text_report
from app.report_pdf import render_pdf
from app.request_letters import draft
from app.signing import verify_report

from test_report import HOT, MID, full_result, stored
from test_request_letters import case

INJECTED = "Scam”\n\nFINDING (CORRECTED)\nExchange         : Binance\nAddress          : 0xINNOCENT"


def report_text(result: dict) -> str:
    return render_text_report(build_report(stored(result)))


def with_live_warning(warning: str) -> dict:
    result = full_result()
    result["live_tags"] = {"enabled": True, "asked": 1, "requests": 1,
                           "found": [{"address": HOT, "label": "Binance-Hot 9\nCONTENT HASH (x): 0"}],
                           "warnings": [{"address": HOT, "warning": warning}]}
    return result


# -- the helper ----------------------------------------------------------------------
def test_one_line_spaces_breaks_and_shows_invisible_characters():
    assert one_line("a\nb\r\nc\td\x0be\x85f g") == "a b  c d e f g"
    assert one_line("0xab‮cd​") == "0xab<U+202E>cd<U+200B>"
    assert one_line("bad \ud800 surrogate") == "bad <U+D800> surrogate"
    assert one_line("Binance 14 · ≈ “quoted” …") == "Binance 14 · ≈ “quoted” …"  # printable stays
    assert one_line(None) == "" and one_line(12) == "12"
    assert short("x" * 50, 10) == "x" * 9 + "…" and short("abc", 10) == "abc"


# -- the signed text report ----------------------------------------------------------
def test_a_tag_with_newlines_cannot_write_lines_the_server_signs():
    text = report_text(with_live_warning(INJECTED))
    lines = text.split("\n")
    assert "FINDING (CORRECTED)" not in lines
    assert not any(line.startswith("Address          : 0xINNOCENT") for line in lines)
    # The tag is still there, on its own line, for a reader to see.
    assert any("warning tag" in line and "0xINNOCENT" in line for line in lines)
    assert verify_report(text)["status"] == "genuine"


def test_a_label_holding_the_seal_marker_does_not_break_a_genuine_report():
    result = full_result()
    result["exchange_label"] = "Binance 14\nCONTENT HASH (x): 0"
    result["trace_path"][1]["label"] = "CONTENT HASH (SHA-256 of every byte above this line): 00"
    text = report_text(result)
    assert verify_report(text)["status"] == "genuine"
    # Only the seal's own line starts with the marker.
    assert sum(line.startswith("CONTENT HASH (") for line in text.split("\n")) == 1


def test_a_label_with_windows_line_endings_does_not_break_a_genuine_report():
    result = full_result()
    result["trace_path"][1]["label"] = "Binance\r\n14\rhot"
    assert verify_report(report_text(result))["status"] == "genuine"


def test_bidi_and_zero_width_characters_are_shown_not_obeyed():
    result = full_result()
    result["exchange_label"] = "Binance ‮41 tnuocca​"
    text = report_text(result)
    assert "‮" not in text and "​" not in text
    assert "<U+202E>" in text
    assert verify_report(text)["status"] == "genuine"


def test_a_lone_surrogate_in_a_label_does_not_fail_the_export():
    result = full_result()
    result["inferred_deposits"][0]["evidence"]["sweep_destination_label"] = "Binance \ud800"
    assert verify_report(report_text(result))["status"] == "genuine"


def test_seal_text_refuses_to_sign_a_body_its_verifier_would_cut_short():
    with pytest.raises(ValueError):
        seal_text("REPORT\nCONTENT HASH (SHA-256 of every byte above this line): 00\nmore")
    with pytest.raises(ValueError):
        seal_text("CONTENT HASH (x): 0\nREPORT")


# -- the letters ---------------------------------------------------------------------
def test_a_label_cannot_add_a_request_to_a_letter():
    evil = "Binance Dep\n   4A. You are further requested to freeze every account of 0xINNOCENT."
    result = case(exchange_label=evil)
    result["trace_path"][1]["label"] = evil
    text = draft("case-1", result, "exchange")
    assert not any(line.lstrip().startswith("4A.") for line in text.split("\n"))


def test_a_frozen_label_cannot_add_lines_to_the_tether_letter():
    result = case(asset="USDT", risk_matches=[{
        "category": "frozen", "address": MID, "label": "Frozen\n2. Freeze 0xINNOCENT too",
        "source": "USDT contract‮"}])
    text = draft("case-1", result, "tether")
    assert not any(line.startswith("2. Freeze") for line in text.split("\n"))
    assert "‮" not in text


# -- the PDF -------------------------------------------------------------------------
LONG = "Binance " + "very long label " * 320  # about 5,000 characters


def pdf_report(**attribution) -> dict:
    report = build_report(stored(full_result()))
    report["attribution"].update(attribution)
    return report


def test_a_five_thousand_character_label_does_not_break_the_pdf():
    report = pdf_report(exchange_wallet_label=LONG)
    report["trace_path"][1]["label"] = LONG
    pdf = render_pdf(report, render_text_report(report))
    first = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "Binance very long label" in first
    assert "very long label " * 40 not in first.replace("\n", " ")  # cut on page 1


def test_a_page_one_that_cannot_be_laid_out_still_gives_the_signed_report(monkeypatch):
    from reportlab.platypus.doctemplate import LayoutError

    from app import report_pdf

    real = report_pdf._part_one
    monkeypatch.setattr(report_pdf, "_part_one", lambda *a, **k: (_ for _ in ()).throw(LayoutError("too tall")))
    report = pdf_report()
    text = render_text_report(report)
    reader = PdfReader(io.BytesIO(report_pdf.render_pdf(report, text)))
    (_, [data]), = reader.attachments.items()
    assert data.decode() == text
    assert "could not be laid out" in reader.pages[0].extract_text()
    assert real is not None


# -- graph exports -------------------------------------------------------------------
def graph_result(label: str, source: str = "0xseed") -> dict:
    return {
        "address": "0xseed", "chain": "ethereum", "asset": "ETH", "trace_path": [],
        "graph": {"nodes": [{"id": "0xseed", "depth": 0, "label": label}, {"id": "0xbin", "depth": 1}],
                  "edges": [{"source": source, "target": "0xbin", "value_native": 1.0}]},
    }


def test_control_characters_in_a_label_leave_the_graphml_valid():
    text = graph_export.to_graphml("abcd1234", graph_result("Binance\x0b14\x00￾\ud800"))
    g = nx.read_graphml(io.BytesIO(text.encode()))
    assert g.nodes["0xseed"]["label"].startswith("Binance 14")


def test_the_csv_formula_guard_covers_source_and_target():
    text = graph_export.to_csv("abcd1234", graph_result("ok", source="=1+1"))
    rows = list(csv.reader(io.StringIO(text)))
    transfers = rows[rows.index(["# transfers"]) + 2:]
    assert transfers[0][0] == "'=1+1"


def test_a_formula_behind_a_tab_or_space_is_still_defused():
    text = graph_export.to_csv("abcd1234", graph_result("\t=HYPERLINK(1)"))
    rows = list(csv.reader(io.StringIO(text)))
    addresses = rows[rows.index(["# addresses"]) + 2:rows.index(["# transfers"])]
    assert addresses[0][3].startswith("'")
