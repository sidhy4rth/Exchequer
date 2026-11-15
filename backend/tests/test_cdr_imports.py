"""CDR summaries kept with a case (app/cdr_imports.py, routes/cdr.py): suite feature 5, behind EXCHEQUER_CDR_IMPORT.

Every number here is synthetic, and none can be a real Indian mobile. India's
mobile numbers start with 6, 7, 8 or 9 and India sets aside no range for fiction,
so a 10-digit number here starts with 5 (50000 0000x): no mobile series, and kept
as printed. The register (identifiers.phone) takes a 10-digit number as an Indian
mobile only when it starts 6 to 9, on purpose, so a number that must be on the
register is in Ofcom's range for drama (+44 7700 900000 to 900999), set aside so
that no subscriber holds it. IMEIs are made up and start with a run of zeros.
Throwaway SQLite, no network.
"""
from __future__ import annotations

import json
import logging

import pytest
from sqlalchemy import select

from app import cdr_imports, config, identifiers, models, statement_imports
from app.cdr_imports import CdrError
from test_statement_imports import BOB, H, UTR_ROW, store, viewer  # noqa: F401 -- the fixture
from test_statement_routes import client, demo  # noqa: F401 -- a signed-in officer, and a caller who has not signed in

SUBJECT, CONTACT, OTHER = "+447700900001", "+447700900002", "+447700900003"  # Ofcom drama range
IMEI = "000000000000011"
NUMBER_ROW = {"kind": "number", "value": "0044 7700 900002", "calls": 12, "sms": 3, "seconds": 1840,
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
    ("+44 7700 900002", CONTACT), ("0044 7700 900002", CONTACT), ("+44 (0)7700 900002", CONTACT),
    ("+44-7700-900002", CONTACT), ("+44 7700 900123", "+447700900123"),
    # not an Indian mobile series (those start 6 to 9): kept as printed, never made a +91 number
    ("5000000002", "5000000002"), ("05000000002", "05000000002"), ("915000000002", "915000000002"),
    ("121", "121"), ("01100000000", "01100000000"),  # a short code, a landline: kept as printed
    ("ax-testco", "AX-TESTCO"),  # an SMS sender
])
def test_a_number_is_kept_as_the_identifier_register_keeps_it(printed, kept):
    assert cdr_imports.number(printed) == kept


@pytest.mark.parametrize("printed", ["", "12", "call me", "+91 9000", "+91 50000 00002", "1234567890123456"])
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
    phone_on("case-1", "+44 (0)7700 900002")
    assert save([{**NUMBER_ROW, "reasons": ["case_identifier"]}])["rows"][0]["reasons"] == ["case_identifier"]
    phone_on("case-2", OTHER)  # on another case only: not this case's
    with pytest.raises(CdrError, match="not a phone identifier"):
        save([{**NUMBER_ROW, "value": OTHER, "reasons": ["case_identifier"]}])


def test_the_check_finds_the_number_on_this_case_and_on_cases_the_viewer_may_read_only():
    phone_on("case-1", SUBJECT)
    phone_on("case-2", CONTACT)
    phone_on("case-2", OTHER, who=viewer(BOB))  # another browser's case: never revealed
    found = cdr_imports.check(viewer(), "case-1", ["0044 7700 900001", "+44 7700 900002", "+44-7700-900003", "+447700900123"])
    assert [(f["number"], f["on_this_case"], [o["case_id"] for o in f["also_in"]]) for f in found] == [
        (SUBJECT, True, []), (CONTACT, False, ["case-2"]), (OTHER, False, []), ("+447700900123", False, [])]
    assert save([{**NUMBER_ROW, "reasons": ["other_case"]}])["rows"][0]["reasons"] == ["other_case"]
    with pytest.raises(CdrError, match="no other case"):
        save([{**NUMBER_ROW, "value": OTHER, "reasons": ["other_case"]}])
    with pytest.raises(CdrError, match="Number 1"):
        cdr_imports.check(viewer(), "case-1", ["121"])
    with pytest.raises(CdrError, match="Number 1"):  # not a mobile series: the register holds no such number
        cdr_imports.check(viewer(), "case-1", ["5000000002"])
    with pytest.raises(CdrError, match="1 to"):
        cdr_imports.check(viewer(), "case-1", [CONTACT] * (cdr_imports.CHECK_MAX + 1))


def test_cdr_summaries_share_the_statement_imports_caps(monkeypatch):
    """One table, one set of caps: a case full of statements has no room for a CDR either."""
    monkeypatch.setattr(statement_imports, "MAX_PER_CASE", 1)
    asha = viewer(unit=7, officer=1)
    statement_imports.create(asha.owner_hash, "case-1", {"source": "bank", "currency": "INR", "rows": [UTR_ROW]}, asha)
    with pytest.raises(CdrError, match="This case already has 1 imports"):
        save([NUMBER_ROW], who=asha)
    monkeypatch.setattr(statement_imports, "MAX_PER_CASE", 50)
    monkeypatch.setattr(statement_imports, "MAX_PER_UNIT", 1)
    with pytest.raises(CdrError, match="Your unit already has 1"):
        save([NUMBER_ROW], who=viewer(BOB, unit=7, officer=2), case="case-2")


# -- the routes ------------------------------------------------------------------------------
def test_a_caller_who_has_not_signed_in_cannot_save_a_summary_but_may_list_and_check(demo):  # noqa: F811 -- the fixture
    refused = demo.post("/trace/case-1/cdr", json={"rows": [NUMBER_ROW]}, headers=H)
    assert refused.status_code == 403 and "Sign in as an officer" in refused.json()["detail"]
    with models.session() as s:
        assert s.scalars(select(models.StatementImport)).all() == []
    assert demo.get("/trace/case-1/cdr", headers=H).json()["imports"] == []
    assert demo.post("/trace/case-1/cdr/check", json={"numbers": [CONTACT]}, headers=H).status_code == 200


def test_with_the_flag_off_nothing_is_listed_saved_or_checked(client, monkeypatch):  # noqa: F811 -- the fixture
    monkeypatch.setattr(config, "CDR_IMPORT", False)
    assert client.get("/trace/case-1/cdr", headers=H).json() == {"case_id": "case-1", "enabled": False, "imports": []}
    assert client.post("/trace/case-1/cdr", json={"rows": [NUMBER_ROW]}, headers=H).status_code == 403
    assert client.post("/trace/case-1/cdr/check", json={"numbers": [CONTACT]}, headers=H).status_code == 403
    with models.session() as s:
        assert s.scalars(select(models.StatementImport)).all() == []


def test_the_routes_save_list_and_check(client):  # noqa: F811 -- the fixture
    assert client.post("/trace/case-1/cdr", json={"rows": [NUMBER_ROW]}, headers=H).status_code == 201
    listed = client.get("/trace/case-1/cdr", headers=H).json()
    assert listed["enabled"] and listed["count"] == 1 and listed["rows_max"] == cdr_imports.ROWS_MAX
    assert client.post("/trace/case-1/cdr", json={"rows": [{**NUMBER_ROW, "first": "x"}]}, headers=H).status_code == 400
    assert client.post("/trace/case-1/cdr", json={"rows": [NUMBER_ROW]}).status_code == 400  # no owner key
    checked = client.post("/trace/case-1/cdr/check", json={"numbers": ["0044 7700 900002"]}, headers=H).json()
    assert checked["results"] == [{"number": CONTACT, "on_this_case": False, "also_in": []}]
    assert client.post("/trace/case-1/cdr/check", json={"numbers": ["121"]}, headers=H).status_code == 400


def test_the_audit_log_and_the_log_hold_counts_never_a_number(client, caplog):  # noqa: F811 -- the fixture
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
    for secret in ("7700900001", "7700900002", "7700900003", IMEI):
        assert secret not in json.dumps(logged) and secret not in caplog.text
