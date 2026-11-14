"""A draft letter of request to a foreign country (app/letters_of_request.py, POST /trace/{id}/letter-of-request).

The letter is the Court's, in the MHA's prescribed format (F. No. 25016/52/2019-LC,
Figure 3.5). What must never happen: a draft that names a treaty, a court or an
offence the officer did not give, that changes the MHA's fixed wording, that asks
about another customer's account, or that can pass for an issued letter. Facts
come from the case; the rest is the officer's, or a marked blank.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import config, freeze_requests, letters_of_request, models, ownership
from app.contracts import on_read
from app.letters_of_request import NOT_VALID, LetterOfRequestError, draft
from app.main import app
from app.request_letters import BLANK

from test_request_letters import DEPOSIT, TX, case

# The MHA's wording as transcribed and checked against the page images. A change to it is deliberate:
# say what changed and why in the pull request, and update this pin.
WORDING_SHA256 = "6046b1bd5fabe3fe95ca45b86b9f05e113b42df5f9b683b20058382daedf9e78"
DETAILS = {"country": "Seychelles", "court": "Court of the Chief Judicial Magistrate, Bengaluru",
           "presiding": "Smt. A. Rao", "basis": "reciprocity", "agency": "CEN Police Station, Bengaluru",
           "reference": "FIR 12/2026, CEN PS Bengaluru", "offences": "BNS s.318(4): cheating (officer's text)",
           "limitation": "Not time-barred (officer's text)", "facts": "Victim was promised returns on a trading app.",
           "liaison": "Insp. Iyer, CEN PS, iyer@example.invalid"}


def flat(text):
    return " ".join(text.split())


def recorded(demo):
    row = next(r for r in json.loads((config.DATA_DIR / "recorded_demos.json").read_text()) if r["demo"] == demo)
    return {**on_read(row["result"]), "created_at": row["recorded_at"]}


# -- the MHA's wording ---------------------------------------------------------------------
def test_the_mha_wording_is_the_reviewed_text():
    assert letters_of_request.wording_sha256() == WORDING_SHA256
    w = letters_of_request._wording()
    assert set(letters_of_request.SECTIONS) <= set(w)
    assert [ln[:3] for ln in w["assurances"].splitlines()[1:]] == ["(a)", "(b)", "(c)", "(d)", "(e)"]


def test_every_mandatory_assurance_appears_word_for_word():
    text = flat(draft("case-1", case(), DETAILS))
    for line in letters_of_request._wording()["assurances"].splitlines():
        assert flat(line) in text
    assert flat(letters_of_request._wording()["limitation_of_use"]) in text
    assert flat(letters_of_request._wording()["confidentiality"]) in text


def test_the_wording_file_names_its_source():
    head = letters_of_request.WORDING_FILE.read_text().splitlines()[:8]
    assert any("F. No. 25016/52/2019-LC" in ln for ln in head)
    assert any("jkhighcourt.nic.in" in ln for ln in head)


# -- the draft's shape -------------------------------------------------------------------
def test_the_draft_follows_the_mhas_sections_in_order():
    text = draft("case-1", case(), DETAILS)
    order = ["Request", "Nature of Request", "Criminal Offences / Applicable Legislation / Penalties",
             "Period of Limitations", "Statement of Facts", "Purpose of the Request", "Assistance Requested",
             "Mandatory Assurance And Undertakings", "Limitation of Use", "Execution of Request",
             "Period of Execution", "Confidentiality", "Liaison"]
    at = [text.index(f"\n{h}\n{'-' * len(h)}\n") for h in order]
    assert at == sorted(at)
    assert "Please accept the assurance of our highest consideration." in text


def test_it_cannot_pass_for_an_issued_letter():
    text = draft("case-1", case(), DETAILS)
    assert text.startswith("DRAFT") and NOT_VALID in text
    assert "(Signature along with seal)" in text and "Nothing below has been sent" in text


def test_the_notes_give_the_mhas_route_and_are_marked_for_removal():
    notes = flat(draft("case-1", case(), DETAILS).split("LETTER OF REQUEST")[0])
    assert "remove this part before the draft goes to the Court" in notes
    assert "IS-II Division, Ministry of Home Affairs" in notes and "for concurrence" in notes
    assert "three copies go to the Assistant Director (IPCC), CBI" in notes
    assert "CrPC s.166A" in notes and "BNSS s.112" in notes and "Confirm the provision" in notes


# -- what the officer gives, and the blanks ------------------------------------------------
def test_the_officers_details_fill_the_letter():
    text = flat(draft("case-1", case(), DETAILS))
    for key in ("court", "presiding", "agency", "reference", "offences", "limitation", "facts", "liaison"):
        assert DETAILS[key] in text, key
    assert "Competent Authority of the Seychelles (Requested Country)" in text


def test_nothing_the_officer_did_not_give_is_made_up():
    text = flat(draft("case-1", case(), {}))
    for hint in ("the requested country", "name of the presiding officer of the Court", "the Court and its place",
                 "officer to set out the offences in the FIR", "officer to state that the offence is not time-barred",
                 "officer to describe the fraud", "name of the officer handling this request"):
        assert f"{BLANK} ({hint}" in text, hint
    assert "BNS" not in text.split("LETTER OF REQUEST")[1]  # no offence is suggested to the Court


def test_the_basis_is_the_officers_choice_and_never_assumed():
    reciprocity = flat(draft("case-1", case(), {**DETAILS, "basis": "reciprocity"}))
    assert "Assurance of Reciprocity in similar matters" in reciprocity and "provisions of the Treaty" not in reciprocity
    treaty = flat(draft("case-1", case(), {**DETAILS, "basis": "treaty", "treaty": "of the UN Convention X"}))
    assert "in accordance with the provisions of the UN Convention X" in treaty
    assert "Assurance of Reciprocity in similar matters" not in treaty
    neither = flat(draft("case-1", case(), {**DETAILS, "basis": ""}))
    assert "officer to keep one of the two" in neither
    assert "Assurance of Reciprocity in similar matters" in neither and f"provisions {BLANK}" in neither


@pytest.mark.parametrize("over, why", [
    ({"basis": "custom"}, "basis must be one of"),
    ({"basis": "treaty", "treaty": ""}, "Name the treaty"),
    ({"country": "x" * 81}, "longer than 80"),
])
def test_bad_details_are_refused_with_the_reason(over, why):
    with pytest.raises(LetterOfRequestError, match=why):
        draft("case-1", case(), {**DETAILS, **over})


def test_typed_text_cannot_add_a_line_to_the_letter():
    text = draft("case-1", case(), {**DETAILS, "court": "CJM Court\nTo: Forged Authority"})
    assert "\nTo: Forged Authority" not in text and "CJM Court To: Forged Authority" in text


# -- the facts come from the case ------------------------------------------------------------
def test_the_facts_name_the_exchange_address_and_every_hop():
    text = draft("case-1", case(), DETAILS)
    assert DEPOSIT in text and TX in text and "Binance" in text and "f" * 64 in text


def test_what_is_asked_follows_what_the_case_holds_about_the_address():
    inferred = recorded(3)  # a probable deposit address: only the exchange can confirm it
    text = flat(draft("demo-3", inferred, DETAILS))
    assert (f"associated with the address {inferred['exchange_address']}, if that address was issued by "
            f"{inferred['exchange']}") in text
    tagged = recorded(12)  # an explorer's tag: first ask whether the exchange controls it
    text = flat(draft("demo-12", tagged, DETAILS))
    assert f"confirming whether it controls the address {tagged['exchange_address']}" in text


def test_an_explorer_tag_asks_for_the_records_it_names_and_points_to_nothing_missing():
    """The explorer-tag request used to ask for "the records in (b)", but (b) is the tracing paragraph."""
    tagged = recorded(12)
    text = flat(draft("demo-12", tagged, DETAILS))
    assert "the records in (b)" not in text
    assert "(i) the account holder's identity and KYC documents" in text
    assert "if it does, production" in text and "listed in the Statement of Facts, and no other" in text


@pytest.mark.parametrize("demo, unsaid", [
    (3, "to an account at Binance"),      # a probable deposit address: only the exchange can confirm it
    (12, "to an account at Flipster"),    # an explorer's tag this office has not confirmed
    (11, "to an account at Binance"),     # a wallet the exchange runs itself is no one customer's account
])
def test_the_letter_claims_no_more_about_the_address_than_the_case_holds(demo, unsaid):
    text = flat(draft(f"demo-{demo}", recorded(demo), DETAILS))
    assert unsaid not in text
    assert "the traced funds were deposited to the account at" not in text
    assert "expected to identify who received" not in text  # only the exchange can name its customer


def test_a_case_that_reached_no_exchange_has_no_letter_of_request():
    with pytest.raises(LetterOfRequestError, match="reached no exchange"):
        draft("case-1", case(exchange=None, exchange_address=None), DETAILS)


def test_a_wallet_the_exchange_runs_asks_only_about_the_transfers_that_can_carry_the_funds():
    text = flat(draft("demo-11", recorded(11), DETAILS))
    assert "The transfers into TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf that can carry the traced funds" in text
    assert "25 other transfers into it in this trace are not part of this request" in text
    assert "listed in the Statement of Facts, and no other" in text
    assert "Binance's own records of the deposits are authoritative" in text
    assert "your own records" not in text


def test_requests_already_sent_to_the_exchange_are_named_from_the_log():
    log = [{"recipient": "Binance", "kind": "exchange", "status": "declined", "sent_at": "2026-10-20T05:00:00+00:00",
            "reference": "LE-123"},
           {"recipient": "OKX", "kind": "exchange", "status": "sent", "sent_at": "2026-10-21T05:00:00+00:00"},
           {"recipient": "Binance", "kind": "exchange", "status": "drafted", "sent_at": None}]
    text = draft("case-1", case(), DETAILS, log)
    assert "2026-10-20: exchange request, reference LE-123; status declined" in text
    assert "OKX" not in text and "status drafted" not in text
    assert "Records preserved" not in text
    assert "Records preserved: [" in draft("case-1", case(), DETAILS, [])


# -- the route ---------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'l.db'}", future=True))
    models.init_db()
    models.save_case("case-1", case()["address"], case())
    models.save_case("case-2", case()["address"], case(exchange=None, exchange_address=None))
    return TestClient(app)


OWNER = {ownership.OWNER_HEADER: "a" * 32}


def test_the_route_returns_the_draft_named_by_case_and_audits_only_the_basis(client):
    r = client.post("/trace/case-1/letter-of-request", json=DETAILS, headers=OWNER)
    assert r.status_code == 200 and r.text.startswith("DRAFT")
    assert r.headers["content-disposition"] == 'attachment; filename="exchequer-case-1-letter-of-request.txt"'
    assert r.headers["cache-control"] == "no-store"
    with models.session() as s:
        row = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "case.letter_of_request_draft")).one()
    assert json.loads(row.detail) == {"basis": "reciprocity"}


def test_the_route_reads_the_cases_requests_log(client):
    who = ownership.owner_hash("a" * 32)
    made = freeze_requests.create(who, "case-1", "Binance", "exchange", status="sent")
    freeze_requests.update(who, made["request_id"], {"status": "declined", "reference": "LE-9"})
    r = client.post("/trace/case-1/letter-of-request", json=DETAILS, headers=OWNER)
    assert "reference LE-9; status declined" in r.text


def test_the_route_refuses_bad_details_an_unknown_case_and_a_case_with_no_exchange(client):
    assert client.post("/trace/case-1/letter-of-request", json={"basis": "custom"}, headers=OWNER).status_code == 400
    assert client.post("/trace/nope/letter-of-request", json=DETAILS, headers=OWNER).status_code == 404
    assert client.post("/trace/case-2/letter-of-request", json=DETAILS, headers=OWNER).status_code == 400
