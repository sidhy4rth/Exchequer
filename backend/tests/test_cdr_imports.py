"""CDR summaries kept with a case (app/cdr_imports.py, routes/cdr.py): suite feature 5, behind EXCHEQUER_CDR_IMPORT.

Every number here is synthetic. India sets aside no mobile range for fiction, so
the Indian mobiles are a visibly patterned run, +91 90000 0000x, made up for the
test; the foreign one is in Ofcom's range for drama (+44 7700 900000 to 900999).
IMEIs are made up and start with a run of zeros. Throwaway SQLite, no network.
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import cdr_imports, config, identifiers, models, statement_imports
from app.cdr_imports import CdrError
from app.main import app
from test_statement_imports import BOB, H, UTR_ROW, store, viewer  # noqa: F401 -- the fixture

SUBJECT, CONTACT, OTHER = "+919000000001", "+919000000002", "+919000000003"
IMEI = "000000000000011"
NUMBER_ROW = {"kind": "number", "value": "09000000002", "calls": 12, "sms": 3, "seconds": 1840,
              "first": "2026-03-01", "last": "2026-03-20", "reasons": ["top_contact"]}
IMEI_ROW = {"kind": "imei", "value": IMEI, "events": 40, "first": "2026-03-01", "last": "2026-03-10"}


@pytest.fixture(autouse=True)
def flag_on(monkeypatch):
    monkeypatch.setattr(config, "CDR_IMPORT", True)


def save(rows, who=None, case="case-1", **more):
    who = who or viewer()
    return cdr_imports.create(who.owner_hash, case, {"rows": rows, **more}, who)


def phone_on(case, value, who=None):
    who = who or viewer()
    identifiers.create(who.owner_hash, case, {"kind": "phone", "value": value}, who)


# -- numbers -----------------------------------------------------------------------------------
@pytest.mark.parametrize(("printed", "kept"), [
    ("9000000002", CONTACT), ("09000000002", CONTACT), ("919000000002", CONTACT), ("+91 90000 00002", CONTACT),
    ("0091-90000-00002", CONTACT), ("+44 7700 900123", "+447700900123"),
    ("121", "121"), ("01100000000", "01100000000"),  # a short code, a landline: kept as printed
    ("ax-testco", "AX-TESTCO"),  # an SMS sender
])
def test_a_number_is_kept_as_the_identifier_register_keeps_it(printed, kept):
    assert cdr_imports.number(printed) == kept


@pytest.mark.parametrize("printed", ["", "12", "call me", "+91 9000", "1234567890123456"])
def test_what_is_not_a_number_is_refused(printed):
    with pytest.raises(CdrError):
        cdr_imports.number(printed)


# -- saving a summary ------------------------------------------------------------------------
def test_a_summary_is_saved_with_its_numbers_normalised_and_listed_apart_from_statements():
    made = save([{**NUMBER_ROW}, IMEI_ROW, {"kind": "subject", "value": SUBJECT, "calls": 50, "sms": 9, "seconds": 9000,
                                            "first": "2026-03-01", "last": "2026-03-31"}], title="CDR (test)")
    assert made["row_count"] == 3 and made["rows"][0]["value"] == CONTACT and made["rows"][1]["events"] == 40
    assert [i["import_id"] for i in cdr_imports.list_for(viewer(), "case-1")] == [made["import_id"]]
    statement_imports.create(viewer().owner_hash, "case-1", {"source": "bank", "currency": "INR", "rows": [UTR_ROW]}, viewer())
    assert [i["source"] for i in statement_imports.list_for(viewer(), "case-1")] == ["bank"]
    assert len(cdr_imports.list_for(viewer(), "case-1")) == 1
    assert cdr_imports.list_for(viewer(BOB), "case-1") == []  # another browser's


@pytest.mark.parametrize(("over", "says"), [
    ({"kind": "tower"}, "say what it is"), ({"reasons": []}, "why this number"), ({"reasons": ["guess"]}, "reasons"),
    ({"calls": -1}, "whole number"), ({"calls": "12"}, "whole number"), ({"first": "01/03/2026"}, "YYYY-MM-DD"),
    ({"first": "2026-03-21"}, "after the last"), ({"calls": 0, "sms": 0}, "not worth keeping"),
    ({"value": "not a number"}, "3 to 15 digits"),
])
def test_a_malformed_row_is_refused_with_its_row_number(over, says):
    with pytest.raises(CdrError, match=says):
        save([{**NUMBER_ROW, **over}])


def test_handsets_and_the_subject_take_only_their_own_shapes():
    with pytest.raises(CdrError, match="14 to 16 digits"):
        save([{**IMEI_ROW, "value": "12345"}])
    with pytest.raises(CdrError, match="without reasons"):
        save([{**IMEI_ROW, "reasons": ["top_contact"]}])
    with pytest.raises(CdrError, match="one number of its own"):
        save([{**NUMBER_ROW, "kind": "subject", "reasons": []}] * 2)
    with pytest.raises(CdrError, match="at most"):
        save([NUMBER_ROW] * (cdr_imports.ROWS_MAX + 1))


# -- matches: fire on the case's identifier, silent otherwise --------------------------------
def test_a_case_identifier_claim_holds_only_for_the_cases_own_phone():
    with pytest.raises(CdrError, match="not a phone identifier of this case"):
        save([{**NUMBER_ROW, "reasons": ["case_identifier"]}])
    phone_on("case-1", "+91 90000 00002")
    assert save([{**NUMBER_ROW, "reasons": ["case_identifier"]}])["rows"][0]["reasons"] == ["case_identifier"]
    phone_on("case-2", OTHER)  # on another case only: not this case's
    with pytest.raises(CdrError, match="not a phone identifier"):
        save([{**NUMBER_ROW, "value": OTHER, "reasons": ["case_identifier"]}])


def test_the_check_finds_the_number_on_this_case_and_on_cases_the_viewer_may_read_only():
    phone_on("case-1", SUBJECT)
    phone_on("case-2", CONTACT)
    phone_on("case-2", OTHER, who=viewer(BOB))  # another browser's case: never revealed
    found = cdr_imports.check(viewer(), "case-1", ["09000000001", "9000000002", "+91 90000 00003", "+447700900123"])
    assert [(f["number"], f["on_this_case"], [o["case_id"] for o in f["also_in"]]) for f in found] == [
        (SUBJECT, True, []), (CONTACT, False, ["case-2"]), (OTHER, False, []), ("+447700900123", False, [])]
    assert save([{**NUMBER_ROW, "reasons": ["other_case"]}])["rows"][0]["reasons"] == ["other_case"]
    with pytest.raises(CdrError, match="no other case"):
        save([{**NUMBER_ROW, "value": OTHER, "reasons": ["other_case"]}])
    with pytest.raises(CdrError, match="Number 1"):
        cdr_imports.check(viewer(), "case-1", ["121"])
    with pytest.raises(CdrError, match="1 to"):
        cdr_imports.check(viewer(), "case-1", [CONTACT] * (cdr_imports.CHECK_MAX + 1))


# -- the routes ------------------------------------------------------------------------------
@pytest.fixture
def client():
    return TestClient(app)


def test_with_the_flag_off_nothing_is_listed_saved_or_checked(client, monkeypatch):
    monkeypatch.setattr(config, "CDR_IMPORT", False)
    assert client.get("/trace/case-1/cdr", headers=H).json() == {"case_id": "case-1", "enabled": False, "imports": []}
    assert client.post("/trace/case-1/cdr", json={"rows": [NUMBER_ROW]}, headers=H).status_code == 403
    assert client.post("/trace/case-1/cdr/check", json={"numbers": [CONTACT]}, headers=H).status_code == 403
    with models.session() as s:
        assert s.scalars(select(models.StatementImport)).all() == []


def test_the_routes_save_list_and_check(client):
    assert client.post("/trace/case-1/cdr", json={"rows": [NUMBER_ROW]}, headers=H).status_code == 201
    listed = client.get("/trace/case-1/cdr", headers=H).json()
    assert listed["enabled"] and listed["count"] == 1 and listed["rows_max"] == cdr_imports.ROWS_MAX
    assert client.post("/trace/case-1/cdr", json={"rows": [{**NUMBER_ROW, "first": "x"}]}, headers=H).status_code == 400
    assert client.post("/trace/case-1/cdr", json={"rows": [NUMBER_ROW]}).status_code == 400  # no owner key
    checked = client.post("/trace/case-1/cdr/check", json={"numbers": ["9000000002"]}, headers=H).json()
    assert checked["results"] == [{"number": CONTACT, "on_this_case": False, "also_in": []}]
    assert client.post("/trace/case-1/cdr/check", json={"numbers": ["121"]}, headers=H).status_code == 400


def test_the_audit_log_and_the_log_hold_counts_never_a_number(client, caplog):
    caplog.set_level(logging.DEBUG)
    client.post("/trace/case-1/identifiers", json={"kind": "phone", "value": CONTACT}, headers=H)
    rows = [{**NUMBER_ROW, "reasons": ["top_contact", "case_identifier"]}, IMEI_ROW]
    iid = client.post("/trace/case-1/cdr", json={"title": f"CDR of {SUBJECT}", "rows": rows}, headers=H).json()["import_id"]
    client.get("/trace/case-1/cdr", headers=H)
    client.post("/trace/case-1/cdr/check", json={"numbers": [CONTACT, OTHER]}, headers=H)
    with models.session() as s:
        events = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action.like("cdr.%"))).all()
    logged = [(e.action, json.loads(e.detail) if e.detail else None) for e in events]
    assert logged == [
        ("cdr.save", {"import_id": iid, "rows": 2, "subject": 0, "number": 1, "imei": 1,
                      "top_contact": 1, "case_identifier": 1, "other_case": 0}),
        ("cdr.list", {}),
        ("cdr.check", {"numbers": 2, "on_this_case": 1, "on_other_cases": 0}),
    ]
    for secret in ("9000000001", "9000000002", "9000000003", IMEI):
        assert secret not in json.dumps(logged) and secret not in caplog.text
