"""The MHA's 2019 list of treaty countries in a letter of request's notes (app/letters_of_request.py).

The list is Figure 3.6 of the MHA guidelines (F. No. 25016/52/2019-LC), transcribed
from a scan and checked against the page images. What must never happen: the list
changing without review, a near-miss spelling guessed into a match, the basis
chosen for the officer, or the note reaching the letter the Court signs.
"""
from __future__ import annotations

import hashlib

import pytest

from app import config, letters_of_request
from app.letters_of_request import draft, listed_country, treaty_countries

from test_letters_of_request import DETAILS, flat
from test_request_letters import case

# The list as transcribed and checked against pages [25] to [28]. A change is deliberate: say what changed
# and why in the pull request, and update this pin.
COUNTRIES_SHA256 = "e31237134a040c3d8a5d9767e485b12e6d4ad7bb8cc3f932c53d47b13363ffdc"


def notes_and_letter(details):
    notes, letter = draft("case-1", case(), details).split("LETTER OF REQUEST (LETTER ROGATORY)")
    return flat(notes), flat(letter)


def test_the_list_is_the_reviewed_transcription():
    assert letters_of_request.countries_sha256() == COUNTRIES_SHA256
    rows = treaty_countries()
    assert len(rows) == 42  # "42 countries (November 2019)", para 1.3
    assert [r["name"] for r in rows if r["status"] != "listed"] == ["Cambodia", "Maldives", "Morocco"]
    assert all(r["status"] in ("listed", "signed, not yet in force") for r in rows)


def test_the_list_names_its_source_and_its_date():
    head = flat(" ".join(ln.lstrip("# ") for ln in letters_of_request.COUNTRIES_FILE.read_text().splitlines()
                         if ln.startswith("#")))
    for part in ("F. No. 25016/52/2019-LC", "Figure 3.6", "pages [25] to [28]", "jkhighcourt.nic.in",
                 "a318fde9e80479b005cb3ee000feadfd7428fb07e2f6232600b8dab5d03ffbe2", "As listed on 4 December 2019",
                 "the list may have changed since; the officer confirms with MHA IS-II"):
        assert part in head, part


def test_a_listed_country_is_named_in_the_notes_and_never_the_letter():
    notes, letter = notes_and_letter({**DETAILS, "country": "  united   kingdom ", "basis": ""})
    assert "the MHA's 2019 list (Figure 3.6) names United Kingdom among countries with a treaty/agreement " \
           "(Agreement 1995); confirm it is still in force and name it" in notes
    assert "2019 list" not in letter and "Agreement 1995" not in letter
    assert "officer to keep one of the two" in letter  # the basis is still the officer's to choose


def test_the_formal_name_matches_too():
    assert listed_country("Republic of Korea")["name"] == "South Korea"
    assert listed_country("BOSNIA AND HERZEGOVINA")["name"] == "Bosnia & Herzegovina"


def test_a_signed_treaty_not_yet_in_force_says_so():
    notes, _ = notes_and_letter({**DETAILS, "country": "Maldives"})
    assert "names Maldives" in notes and "signed but not yet in force" in notes


def test_an_unlisted_country_points_to_reciprocity_without_choosing_it():
    notes, letter = notes_and_letter({**DETAILS, "country": "Seychelles", "basis": ""})
    assert "Seychelles is not on the MHA's 2019 list (Figure 3.6) under that name" in notes
    assert "reciprocity may be the route; confirm with the MHA" in notes
    assert "officer to keep one of the two" in letter and "2019 list" not in letter


def test_near_misses_are_not_guessed():
    for typed in ("UK", "Korea", "Oman", "Bosnia", "Australia Pty"):
        assert listed_country(typed) is None, typed


def test_the_officers_basis_is_kept_whatever_the_list_says():
    _, letter = notes_and_letter({**DETAILS, "country": "Seychelles", "basis": "treaty", "treaty": "of the UN Convention X"})
    assert "in accordance with the provisions of the UN Convention X" in letter
    _, letter = notes_and_letter({**DETAILS, "country": "France", "basis": "reciprocity"})
    assert "Assurance of Reciprocity in similar matters" in letter


def test_no_country_given_says_nothing_about_the_list():
    notes, _ = notes_and_letter({**DETAILS, "country": ""})
    assert "2019 list" not in notes and "Treaty:" not in notes


# Figure 3.6's Central Authority, language and specifications columns, and the MHA MLAT portal's current list
# (#352). Both await a by-eye check by a second person, so no draft uses them yet. A change is deliberate: say
# what changed and why in the pull request, and update the pin.
AUTHORITIES_SHA256 = "d19af6317c26feab5e88c1e80f256491d32dc02a051f5fd14906d999f8885fe7"
PORTAL_SHA256 = "b7b178dc93892154ab8b5867278975345f1fa9407c3d0de3c7f41e995fda9572"


@pytest.fixture
def fig36_on(monkeypatch):
    """EXCHEQUER_MHA_FIG36 on: the files are read, as #353 was written. The four tests below run with it."""
    monkeypatch.setattr(config, "MHA_FIG36", True)


def header(path):
    return flat(" ".join(ln.lstrip("# ") for ln in path.read_text().splitlines() if ln.startswith("#")))


@pytest.mark.usefixtures("fig36_on")
def test_figure_3_6_columns_are_the_reviewed_transcription_row_for_row():
    assert letters_of_request.authorities_sha256() == AUTHORITIES_SHA256
    rows = letters_of_request.central_authorities()
    assert [r["name"] for r in rows] == [r["name"] for r in treaty_countries()]  # same 42 rows, same order
    assert all(r["language"] and r["specifications"] for r in rows)
    assert [r["name"] for r in rows if not r["authority"]] == ["Switzerland"]  # the figure's cell is blank
    by_name = {r["name"]: r for r in rows}
    assert by_name["United States of America"]["language"] == "The request shall be in English"
    assert by_name["Morocco"]["language"] == "Arabic translation"
    # Kept as printed, slips included; never "corrected" into something the MHA did not print.
    assert "the Republic of Kazakhstan" in by_name["Kyrgyzstan"]["authority"]
    assert by_name["Vietnam"]["email"] == "tttp_mla@vks.gov.v"
    assert [r["name"] for r in rows if r["specifications"] != "No specific requirement."] == \
        ["Hong Kong", "Singapore", "United Arab Emirates"]


@pytest.mark.usefixtures("fig36_on")
def test_portal_list_is_the_reviewed_transcription():
    assert letters_of_request.portal_sha256() == PORTAL_SHA256
    rows = letters_of_request.portal_countries()
    assert len(rows) == 67
    linked = [r for r in rows if r["treaty"].startswith("document: https://mlat.mha.gov.in/UploadMedia/MlaTreaty/")]
    assert len(linked) == 41
    assert sorted(r["name"] for r in rows if r["treaty"] == "icon, no document linked") == [
        "Federal Democratic Republic of Nepal", "Germany", "Luxembourg", "New Zealand", "Poland",
        "The Kingdom of Cambodia", "The Kingdom of Morocco", "The Netherlands"]
    assert sum(r["treaty"] == "Not Exist" for r in rows) == 18
    assert len({r["name"] for r in rows}) == 67


@pytest.mark.usefixtures("fig36_on")
def test_both_files_name_their_source_and_await_a_second_check():
    authorities = header(letters_of_request.AUTHORITIES_FILE)
    for part in ("F. No. 25016/52/2019-LC", "Figure 3.6", "page [25] (PDF page 27)", "page [28] (PDF page 30)",
                 "a318fde9e80479b005cb3ee000feadfd7428fb07e2f6232600b8dab5d03ffbe2", "As listed on 4 December 2019",
                 "AWAITING A BY-EYE CHECK BY A SECOND PERSON"):
        assert part in authorities, part
    portal = header(letters_of_request.PORTAL_FILE)
    for part in ("https://mlat.mha.gov.in/", "Treaties/Agreements", "Retrieved: 15 November 2026",
                 "2cd27be206d0660e009afacadb0423a605d1b3136089d4c3d26a5de2a476a140",
                 "AWAITING A BY-EYE CHECK BY A SECOND PERSON", "A row is not proof that a treaty is in force"):
        assert part in portal, part


@pytest.mark.usefixtures("fig36_on")
def test_the_draft_does_not_use_the_unchecked_files_yet():
    notes, letter = notes_and_letter({**DETAILS, "country": "Kyrgyzstan"})
    for text in (notes, letter):
        assert "General Prosecutor's Office" not in text and "No specific requirement" not in text
        assert "Kazakhstan" not in text and "MLAT portal" not in text and "mlat.mha.gov.in" not in text


# EXCHEQUER_MHA_FIG36 stays off until that by-eye check; a separate PR switches it on. With it off, neither file is
# read and a letter of request is byte for byte what main drafted before #353. The pins are the SHA-256 of the
# draft of case() with DETAILS for each country, computed from main at cc79f72f (date and signing-key lines fixed
# below); Seychelles there gives test_letter_of_request_store_basis.py's BEFORE_SHA256. Kyrgyzstan has a Central
# Authority row, Belgium is only on the portal's list, and Maldives is "signed, not yet in force" on the 2019 list
# but has a linked document on the portal. A PR that changes the draft on purpose updates these pins.
MAIN_SHA256 = {
    "Belgium": "45e9d2393226e49695dc9bbeada8cfd04c745f88556a982f195aeaa464fd9ffa",
    "Kyrgyzstan": "e919643a33ad210af19c5ef61b69b34ea464cf0717865a891e6ce7d4cc5643dd",
    "Maldives": "4b4b40aa83e20634d05dc55681be59eb943afb0e4e16b9621efe61cb88a47647",
}


@pytest.fixture
def fig36_off(monkeypatch):
    """The flag off, and the date and the signing key's lines fixed, so a draft compares byte for byte."""
    monkeypatch.setattr(config, "MHA_FIG36", False)
    monkeypatch.setattr(letters_of_request, "_today", lambda: "16 November 2026")
    monkeypatch.setattr(letters_of_request, "_verify_lines", lambda: ["Check the attached report (fixed)."])


def test_the_flag_is_off_by_default():
    assert config.MHA_FIG36 is False and config.FLAGS["EXCHEQUER_MHA_FIG36"]["on"] is False


@pytest.mark.parametrize("country", sorted(MAIN_SHA256))
def test_flag_off_a_letter_of_request_is_byte_for_byte_mains(fig36_off, country):
    text = draft("case-1", case(), {**DETAILS, "country": country})
    assert hashlib.sha256(text.encode()).hexdigest() == MAIN_SHA256[country]


def test_flag_off_the_unchecked_files_are_never_read(fig36_off, monkeypatch, tmp_path):
    # Neither path exists, so any read would raise.
    monkeypatch.setattr(letters_of_request, "AUTHORITIES_FILE", tmp_path / "absent-authorities.txt")
    monkeypatch.setattr(letters_of_request, "PORTAL_FILE", tmp_path / "absent-portal.txt")
    assert letters_of_request.central_authorities() == [] and letters_of_request.portal_countries() == []
    text = draft("case-1", case(), {**DETAILS, "country": "Kyrgyzstan"})
    assert hashlib.sha256(text.encode()).hexdigest() == MAIN_SHA256["Kyrgyzstan"]
