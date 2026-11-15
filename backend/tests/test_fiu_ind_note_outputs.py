"""Where the FIU-IND note is printed: the report's FINDING and the exchange letters.

With EXCHEQUER_FIU_IND_NOTE off, every report and letter is byte for byte what
it was. With it on, the only change is the note's own block of lines; the
letter still goes to the exchange (app/fiu_ind_status.py).
"""
from __future__ import annotations

import difflib
import io

import pytest
from pypdf import PdfReader

from app import config, fiu_ind_status
from app.report import build_report, render_text_report, signed_finding
from app.report_pdf import render_pdf
from app.request_letters import EXCHANGE, EXCHANGE_FREEZE, INSTANT, INSTANT_FREEZE, available, draft

from test_fiu_ind_status import LS_5805, PIB_DEC_2023
from test_instant_exchangers import instant_case
from test_letter_kinds import labelled
from test_report import full_result, stored


@pytest.fixture(autouse=True)
def _fresh():
    fiu_ind_status.clear_cache()
    yield
    fiu_ind_status.clear_cache()


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(config, "FIU_IND_NOTE", True)


def _at(exchange, label):
    return labelled("hot_wallet", label=label, exchange=exchange, exchange_label=label)


def _report(exchange="Binance"):
    result = full_result()
    result["exchange"] = exchange
    return build_report(stored(result))


def _outputs(report, letters):
    return [render_text_report(report)] + [draft("case-1", result, to) for result, to in letters]


LETTERS = [(_at("Kraken", "Kraken 3"), EXCHANGE), (_at("Kraken", "Kraken 3"), EXCHANGE_FREEZE),
           (_at("Binance", "Binance 14"), EXCHANGE), (_at("BitMEX", "BitMEX 1 (defunct)"), EXCHANGE)]



# -- flag off: nothing changes ----------------------------------------------------------
def test_flag_off_every_output_is_byte_identical(monkeypatch):
    report = _report("Kraken")
    letters = LETTERS + [(instant_case(), INSTANT), (instant_case(), INSTANT_FREEZE)]
    monkeypatch.setattr(config, "FIU_IND_NOTE", False)
    off = _outputs(report, letters)
    assert not any("FIU-IND" in text for text in off)
    monkeypatch.setattr(config, "FIU_IND_NOTE", True)
    with_note = _outputs(report, letters)
    for before, after in zip(off, with_note, strict=True):
        # The only change is one block of added lines, the note's own: take it out and
        # the rest is the flag-off text, byte for byte. (The report's seal covers every byte
        # above it, so it changes with them; it is compared without its two seal lines.)
        before, after = _unsealed(before), _unsealed(after)
        old, new = before.split("\n"), after.split("\n")
        changes = [op for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
                   if op[0] != "equal"]
        assert len(changes) == 1 and changes[0][0] == "insert", changes
        _, _, _, j1, j2 = changes[0]
        added = new[j1:j2]
        assert [line for line in added if line][0].startswith("FIU-IND")  # its blank line may align either side
        assert "\n".join(new[:j1] + new[j2:]) == before
        assert "FIU-IND" not in "\n".join(new[:j1] + new[j2:])  # and the block is all of the note


def test_flag_off_never_reads_the_file(monkeypatch):
    monkeypatch.setattr(config, "FIU_IND_NOTE", False)
    report = _report("Kraken")
    off = _outputs(report, LETTERS)

    def unread():
        raise AssertionError("read with the flag off")
    unread.cache_clear = lambda: None  # for the fixture's clear_cache
    monkeypatch.setattr(fiu_ind_status, "_document", unread)
    assert _outputs(report, LETTERS) == off


def _unsealed(text):
    return "\n".join(line for line in text.split("\n") if not line.startswith(("CONTENT HASH (", "SIGNATURE (")))


def test_flag_off_offers_are_unchanged(monkeypatch):
    monkeypatch.setattr(config, "FIU_IND_NOTE", False)
    off = available(_at("Kraken", "Kraken 3"))
    monkeypatch.setattr(config, "FIU_IND_NOTE", True)
    assert available(_at("Kraken", "Kraken 3")) == off  # the letter still goes to the exchange


def test_an_unregistered_exchange_letter_says_so_with_the_date_and_sources(on):
    for to in (EXCHANGE, EXCHANGE_FREEZE):
        text = draft("case-1", _at("Kraken", "Kraken 3"), to)
        flat = " ".join(text.split())
        assert ("FIU-IND NOTE (about the exchange, not any customer): Kraken, in date order: on 28 Dec 2023 "
                "FIU-IND announced a show-cause notice to it under section 13 of the PMLA and that it had written "
                "to MeitY to block its URLs (PIB release 1991372); as of 9 Mar 2026 Kraken was not on FIU-IND's "
                "list of registered VDA service providers (Lok Sabha USQ 5805, Annexure-I). Exchequer last "
                "checked the sources on 15 Nov 2026.") in flat
        assert LS_5805 in text and PIB_DEC_2023 in text  # each URL whole, on its line
        assert "Kraken — Law Enforcement / Compliance team" in text  # still addressed to the exchange
        assert "illegal" not in flat.lower()


def test_a_registered_exchange_shows_its_listing_and_its_penalty(on):
    flat = " ".join(draft("case-1", _at("Binance", "Binance 14"), EXCHANGE).split())
    assert ("as of 9 Mar 2026 Binance, listed as Nest Services Limited (Earlier Binance International Limited), "
            "was on FIU-IND's list of registered VDA service providers (Lok Sabha USQ 5805, Annexure-I)") in flat
    assert "on 19 Jun 2024 FIU-IND imposed a penalty of Rs 18,82,00,000" in flat
    assert "https://fiuindia.gov.in/pdfs/judgements/Binance_Order_10_2024.pdf" in flat


def test_a_closed_exchange_shows_its_closure_first_then_fiu_ind(on):
    text = draft("case-1", _at("BitMEX", "BitMEX 1 (defunct)"), EXCHANGE)
    assert text.index("NOTE: BitMEX has closed") < text.index("FIU-IND NOTE")
    assert "on 1 Oct 2025 FIU-IND announced a notice to it under section 13" in " ".join(text.split())


def test_an_instant_exchanger_named_by_fiu_ind_gets_the_note(on):
    for to in (INSTANT, INSTANT_FREEZE):
        flat = " ".join(draft("case-1", instant_case(), to).split())
        assert "ChangeNOW was not on FIU-IND's list" in flat and "on 9 Sep 2026 FIU-IND announced" in flat
        assert "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2308131" in flat


def test_an_unlisted_exchange_letter_and_report_say_nothing(on):
    assert "FIU-IND" not in draft("case-1", _at("FTX", "FTX 12 (defunct)"), EXCHANGE)
    assert "FIU-IND" not in render_text_report(_report("FTX"))


def test_the_report_finding_carries_the_note_and_its_sources(on):
    text = render_text_report(_report("Kraken"))
    finding = text[text.index("\nFINDING\n"):text.index("CONFIDENCE")]
    assert "FIU-IND          : Kraken, in date order: on 28 Dec 2023 FIU-IND announced a" in finding
    assert "as of 9 Mar 2026 Kraken was not on FIU-IND's list of registered VDA" in " ".join(finding.split())
    assert "Exchequer last checked the sources on 15 Nov 2026." in " ".join(finding.split())
    assert f"FIU-IND source   : {LS_5805}" in finding and f"FIU-IND source   : {PIB_DEC_2023}" in finding
    assert "This is about the exchange, not any customer." in " ".join(finding.split())
    # The signed finding and the PDF still read: the note is its own field, after the others.
    assert signed_finding(text)["exchange"] == "Kraken"
    assert len(PdfReader(io.BytesIO(render_pdf(_report("Kraken"), text))).pages) >= 1
