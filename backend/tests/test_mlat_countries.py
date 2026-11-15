"""The MHA's 2019 list of treaty countries in a letter of request's notes (app/letters_of_request.py).

The list is Figure 3.6 of the MHA guidelines (F. No. 25016/52/2019-LC), transcribed
from a scan and checked against the page images. What must never happen: the list
changing without review, a near-miss spelling guessed into a match, the basis
chosen for the officer, or the note reaching the letter the Court signs.
"""
from __future__ import annotations

from app import letters_of_request
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
