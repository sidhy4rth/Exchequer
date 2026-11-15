"""Privacy protocols in the signed report, and not in the letters (#189).

With the flag EXCHEQUER_PRIVACY_CATEGORY on, a trace that passed through a
privacy protocol's contract (Railgun, Aztec, Hinkal, Privacy Pools) says so in
a section of its own in the signed text report, with the screen's wording: a
note, not an accusation. With the flag off, or with no match, the report is
byte for byte what it was before, because signed reports and recorded demos
must not change. The letters to exchanges and to Tether never mention them:
they are requests to a third party, kept to the facts the request needs.
Real traces over a fake provider; no network.
"""
from __future__ import annotations

import io
import json
from dataclasses import replace

import networkx as nx

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import config, request_letters
from app.main import app
from app.models import Case
from app.report import PRIVACY_TITLE, build_report, render_text_report
from app.report_pdf import render_pdf
from app.risk_matcher import clear_label_caches, get_risk_matcher
from app.routes import demos
from app.signing import verify_report

from test_privacy_category import BINANCE_14, ENTRY, POOL, RAILGUN, SEED, W1, _route, _tx, trace  # noqa: F401 -- fixture
from test_report import full_result, stored

WHEN = "2026-11-14T10:00:00+00:00"
PRIVACY_KEYS = ("privacy_matches", "privacy_notes")


@pytest.fixture
def flag(monkeypatch):
    def set_to(on: bool) -> None:
        monkeypatch.setattr(config, "PRIVACY_CATEGORY", on)
        clear_label_caches()
    yield set_to
    monkeypatch.setattr(config, "PRIVACY_CATEGORY", False)
    clear_label_caches()


def _case(result: dict) -> Case:
    return Case(id="case-privacy", address=result["address"], created_at=WHEN, result_json=json.dumps(result))


def _text(result: dict) -> str:
    return render_text_report(build_report(_case(result), generated_at=WHEN))


def _without(result: dict) -> dict:
    return {k: v for k, v in result.items() if k not in PRIVACY_KEYS}


@pytest.fixture
def railgun_case(trace, flag):  # noqa: F811 -- the imported fixture
    """A trace with the flag on whose route passes Railgun on its way to Binance."""
    flag(True)
    result = trace(_route(RAILGUN))
    assert [m["entity"] for m in result["privacy_matches"]] == ["Railgun"]
    return result


# --- the section ----------------------------------------------------------------

def test_flag_on_with_a_match_the_report_lists_it_with_the_screens_wording(railgun_case):
    report = build_report(_case(railgun_case), generated_at=WHEN)
    [entry] = report["privacy_protocols"]["matches"]
    assert entry["address"] == RAILGUN and entry["entity"] == "Railgun" and entry["depth"] == 2
    assert entry["source"].startswith("Railgun shared-models network-config.ts")
    text = render_text_report(report)
    flat = " ".join(text.split())
    assert PRIVACY_TITLE in text
    assert "lose their visible link" in flat and "This is not an accusation" in flat
    assert f"Privacy protocol: {RAILGUN} is" in flat and "(Railgun)" in flat
    assert "2 hops from the reported address" in flat and "Railgun shared-models network-config.ts" in flat
    # A note beside the screening, never in it: the screening section still finds nothing.
    screening = text.split("SANCTIONS, MIXER, FREEZE AND STOLEN-FUNDS SCREENING", 1)[1].split(PRIVACY_TITLE, 1)[0]
    assert "No address in this trace appeared on the screened lists." in screening
    assert RAILGUN not in screening


def test_the_section_is_signed_and_the_report_verifies(railgun_case):
    text = _text(railgun_case)
    checked = verify_report(text)
    assert checked["status"] == "genuine" and checked["signature_ok"] is True
    # An edit to the section breaks the signature like an edit anywhere else.
    edited = text.replace("This is not an accusation", "This is an accusation", 1)
    assert edited != text and verify_report(edited)["genuine"] is False


def test_flag_on_the_section_carries_the_whole_note_only_once_per_match(railgun_case):
    text = _text(railgun_case)
    assert text.count(PRIVACY_TITLE) == 1
    section = text.split(PRIVACY_TITLE, 1)[1].split("LISTS SCREENED AGAINST", 1)[0]
    assert sum(line.startswith("* ") for line in section.splitlines()) == 1


def test_a_follow_on_traces_privacy_match_is_listed_and_named_as_the_follow_ons(railgun_case, flag):
    plain = _without(railgun_case) | {"privacy_matches": [], "privacy_notes": []}
    plain["follow_ons"] = [{"asset": "USDT", "address": W1, "result": railgun_case}]
    report = build_report(_case(plain), generated_at=WHEN)
    assert report["privacy_protocols"]["matches"] == []
    [follow] = report["privacy_protocols"]["follow_ons"]
    assert follow["asset"] == "USDT" and follow["matches"][0]["address"] == RAILGUN
    flat = " ".join(render_text_report(report).split())
    assert f"In the follow-on trace of USDT from {W1}: Privacy protocol: {RAILGUN}" in flat


# --- nothing changes without the flag or without a match -----------------------

def test_flag_off_the_report_is_byte_for_byte_as_before_even_for_a_case_with_matches(railgun_case, flag):
    flag(False)
    assert _text(railgun_case) == _text(_without(railgun_case))
    assert PRIVACY_TITLE not in _text(railgun_case)
    assert build_report(_case(railgun_case), generated_at=WHEN) == build_report(
        _case(_without(railgun_case)), generated_at=WHEN)


def test_flag_on_with_no_match_the_report_is_byte_for_byte_as_before(trace, flag):  # noqa: F811
    history = [_tx(SEED, W1, 9.0, 1_700_000_010), _tx(W1, BINANCE_14, 9.0, 1_700_000_020)]
    flag(False)
    off = trace(history)
    flag(True)
    on = trace(history)
    assert on["privacy_matches"] == [] and "privacy_matches" not in off
    assert _text(on) == _text(_without(on)) == _text(off)
    assert PRIVACY_TITLE not in _text(on)


def test_the_flag_changes_no_byte_of_a_report_without_privacy_fields(flag):
    result = full_result()
    flag(False)
    off = render_text_report(build_report(stored(result), generated_at=WHEN))
    flag(True)
    on = render_text_report(build_report(stored(result), generated_at=WHEN))
    assert on == off
    assert build_report(stored(result), generated_at=WHEN) == build_report(stored(result), generated_at=WHEN)


def test_flag_on_no_recorded_demos_report_changes(flag):
    rows = json.loads(demos.RECORDED_DEMOS_PATH.read_text())
    assert rows
    for row in rows:
        case = Case(id=f"demo-{row['demo']}", address=row["result"]["address"], created_at=WHEN,
                    result_json=json.dumps(row["result"]))
        flag(False)
        off = render_text_report(build_report(case, generated_at=WHEN))
        flag(True)
        on = render_text_report(build_report(case, generated_at=WHEN))
        assert on == off, row["demo"]


# --- the PDF --------------------------------------------------------------------

def test_the_pdf_renders_the_note_on_page_one_and_in_the_signed_copy(railgun_case):
    report = build_report(_case(railgun_case), generated_at=WHEN)
    text = render_text_report(report)
    pdf = render_pdf(report, text)
    reader = PdfReader(io.BytesIO(pdf))
    first = " ".join(reader.pages[0].extract_text().split())
    assert "PRIVACY PROTOCOLS ON THE PATH" in first and "NOT AN ACCUSATION" in first and RAILGUN in first
    (_, [attached]), = reader.attachments.items()
    assert attached.decode() == text and verify_report(attached.decode())["signature_ok"]
    checked = TestClient(app).post("/verify", content=pdf, headers={"Content-Type": "application/pdf"}).json()
    assert checked["status"] == "genuine" and checked["pdf"]["pages_match"] is True, checked["pdf"]["problems"]


def test_without_the_section_page_one_has_no_privacy_block(railgun_case, flag):
    flag(False)
    report = build_report(_case(railgun_case), generated_at=WHEN)
    first = PdfReader(io.BytesIO(render_pdf(report, render_text_report(report)))).pages[0].extract_text()
    assert "PRIVACY PROTOCOLS" not in first


# --- the lede: true for a case stored before #279 too ---------------------------

# #279's lede said "each note says whether the contract's payouts were followed";
# notes stored before #279 never say so, and the lede is drawn at render time.
UNTRUE = "each note says"
LEDE = "may not go past a contract that pays out to, or is paid by, many addresses"


def _entry_case(railgun_case, payouts_followed):
    """railgun_case with its match swapped for the Privacy Pools Entrypoint as a
    service contract: the note as #279 writes it (payouts_followed=False) or as
    a note stored before #279 reads (the default, which never says so)."""
    graph = nx.DiGraph()
    graph.add_edge(W1, ENTRY, value_native=0.5)
    graph.nodes[ENTRY].update(depth=1, is_service_contract=True)
    [match] = get_risk_matcher("ethereum").annotate_privacy(graph)
    if payouts_followed is None:
        match = replace(match, payouts_followed=None)
    return railgun_case | {"privacy_matches": [match.to_dict()], "privacy_notes": [match.describe()]}


def _rendered(result):
    report = build_report(_case(result), generated_at=WHEN)
    text = render_text_report(report)
    pdf = render_pdf(report, text)
    first = " ".join(PdfReader(io.BytesIO(pdf)).pages[0].extract_text().split())
    return " ".join(text.split()), text, pdf, first


@pytest.mark.parametrize("payouts_followed", [None, False], ids=["stored-before-279", "new"])
def test_the_lede_claims_nothing_a_stored_note_may_not_say(railgun_case, payouts_followed):
    flat, text, pdf, first = _rendered(_entry_case(railgun_case, payouts_followed))
    assert UNTRUE not in flat and UNTRUE not in first
    assert LEDE in flat and "Being a privacy protocol never stops the trace" in first
    assert verify_report(text)["signature_ok"] is True
    checked = TestClient(app).post("/verify", content=pdf, headers={"Content-Type": "application/pdf"}).json()
    assert checked["status"] == "genuine" and checked["pdf"]["pages_match"] is True, checked["pdf"]["problems"]


def test_a_pre_279_note_renders_as_stored(railgun_case):
    flat, _, _, _ = _rendered(_entry_case(railgun_case, None))
    assert f"Privacy protocol: {ENTRY}" in flat and "The trace did not stop here." in flat
    assert "payouts were not followed" not in flat


def test_a_new_note_still_says_the_payouts_were_not_followed(railgun_case):
    flat, _, _, first = _rendered(_entry_case(railgun_case, False))
    assert "The trace did not stop here" not in flat
    assert "Being a privacy protocol did not stop the trace here, but its payouts were not followed" in flat
    assert ENTRY in first


# --- the letters: deliberately left out ----------------------------------------

@pytest.mark.parametrize("through", [RAILGUN, POOL])
def test_the_letters_never_mention_a_privacy_protocol(trace, flag, through):  # noqa: F811
    flag(True)
    result = trace(_route(through))
    assert result["privacy_matches"] and result["exchange_address"] == BINANCE_14
    offered = request_letters.available(result)
    assert offered
    for letter in offered:
        body = request_letters.draft("case-privacy", result, letter["to"])
        assert body == request_letters.draft("case-privacy", _without(result), letter["to"])
        assert "privacy protocol" not in body.lower() and "visible link" not in body
