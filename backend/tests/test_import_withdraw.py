"""Withdrawing a saved statement or CDR import entered by mistake (statement_imports.withdraw,
routes/statements.py and routes/cdr.py): suite feature 5, behind EXCHEQUER_STATEMENT_IMPORT and
EXCHEQUER_CDR_IMPORT.

Synthetic rows only (see test_statement_imports.py and test_cdr_imports.py). Throwaway SQLite, no network.
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from app import accounts, config, models, ownership, rate_limit, statement_imports
from app.main import app
from test_cdr_imports import NUMBER_ROW
from test_statement_imports import ALICE, BOB, H, SEED, UTR_ROW, store  # noqa: F401 -- the fixture

PW = "officer-password-long-2"
REASON = "Saved against the wrong case: TEST WRONG CASE"
STATEMENT = {"source": "bank", "currency": "INR", "rows": [UTR_ROW]}


@pytest.fixture(autouse=True)
def officers(store, monkeypatch):  # noqa: F811 -- after the store
    """Asha and Ravi in Cyber Cell North, Esha in Cyber Cell South."""
    monkeypatch.setattr(config, "CDR_IMPORT", True)
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**4)
    for limiter in rate_limit.LOGIN_LIMITS:
        limiter.reset()
    rate_limit.request_writes.reset()
    north, south = accounts.create_unit("Cyber Cell North"), accounts.create_unit("Cyber Cell South")
    for who, unit in (("asha", north), ("ravi", north), ("esha", south)):
        accounts.create_officer(f"{who}@example.org", who.title(), unit.id, "officer", password=PW)


def signed_in(who, key=ALICE):
    c = TestClient(app, base_url="https://testserver")
    signed = c.post("/auth/login", json={"email": f"{who}@example.org", "password": PW}, headers={accounts.CSRF_HEADER: "1"})
    assert signed.status_code == 200
    c.headers.update({ownership.OWNER_HEADER: key})
    return c


def saved(c, what="statements", body=None):
    made = c.post(f"/trace/case-1/{what}", json=body or STATEMENT)
    assert made.status_code == 201
    return made.json()["import_id"]


def withdraw(c, iid, reason=REASON, what="statements"):
    return c.post(f"/trace/case-1/{what}/{iid}/withdraw", json={"reason": reason})


def test_an_officer_withdraws_an_import_and_it_leaves_the_listing_unless_asked_for():
    asha = signed_in("asha")
    iid = saved(asha)
    done = withdraw(asha, iid)
    assert done.status_code == 200
    assert done.json()["withdrawn"]["reason"] == REASON and done.json()["withdrawn"]["by"].startswith("officer-")
    listed = asha.get("/trace/case-1/statements").json()
    assert listed["imports"] == [] and listed["withdrawn_count"] == 1 and listed["can_withdraw"] is True
    shown = asha.get("/trace/case-1/statements", params={"withdrawn": 1}).json()["imports"]
    assert [(i["import_id"], i["withdrawn"]["reason"]) for i in shown] == [(iid, REASON)]
    with models.session() as s:  # never deleted: the rows stay in the case record
        assert s.get(models.StatementImport, iid).rows_json != "[]"


def test_a_standing_import_is_listed_with_no_withdrawal():
    asha = signed_in("asha")
    saved(asha)
    listed = asha.get("/trace/case-1/statements").json()
    assert listed["imports"][0]["withdrawn"] is None and listed["withdrawn_count"] == 0


@pytest.mark.parametrize("reason", ["", "   ", SEED, "x" * 301])
def test_a_withdrawal_needs_a_reason_of_one_line_that_is_not_a_key(reason):
    asha = signed_in("asha")
    iid = saved(asha)
    assert withdraw(asha, iid, reason).status_code in (400, 422)
    assert len(asha.get("/trace/case-1/statements").json()["imports"]) == 1


def test_only_the_officers_own_unit_or_browser_may_withdraw():
    iid = saved(signed_in("asha"))
    esha = signed_in("esha", BOB)  # another unit, another browser: not theirs to see or withdraw
    assert withdraw(esha, iid).status_code == 404
    assert esha.get("/trace/case-1/statements", params={"withdrawn": 1}).json()["imports"] == []
    assert withdraw(signed_in("ravi", BOB), iid).status_code == 200  # a colleague in the same unit


def test_the_demo_caller_cannot_withdraw():
    demo = TestClient(app, headers=H)
    iid = saved(signed_in("asha"))  # saving needs an officer too; this browser (ALICE) then signs out
    refused = withdraw(demo, iid)
    assert refused.status_code == 403 and "Sign in as an officer" in refused.json()["detail"]
    listed = demo.get("/trace/case-1/statements").json()
    assert listed["can_withdraw"] is False and len(listed["imports"]) == 1


def test_a_second_withdrawal_is_refused_and_keeps_the_first_reason():
    asha = signed_in("asha")
    iid = saved(asha)
    withdraw(asha, iid)
    again = withdraw(asha, iid, "A different reason")
    assert again.status_code == 409 and "already withdrawn" in again.json()["detail"]
    shown = asha.get("/trace/case-1/statements", params={"withdrawn": 1}).json()["imports"]
    assert shown[0]["withdrawn"]["reason"] == REASON


def test_a_write_that_keeps_meeting_another_is_a_clean_conflict(monkeypatch):
    asha = signed_in("asha")
    iid = saved(asha)
    tries = []

    def stale(*_args):
        tries.append(1)
        raise StaleDataError("moved")

    monkeypatch.setattr(statement_imports, "_withdraw_once", stale)
    clash = withdraw(asha, iid)
    assert clash.status_code == 409 and "same moment" in clash.json()["detail"]
    assert len(tries) == statement_imports.WRITE_TRIES


def test_the_row_version_moves_on_a_withdrawal():
    asha = signed_in("asha")
    iid = saved(asha)
    withdraw(asha, iid)
    with models.session() as s:
        assert s.get(models.StatementImport, iid).row_version == 2


def test_a_cdr_summary_is_withdrawn_on_its_own_route_and_never_a_statement_by_it():
    asha = signed_in("asha")
    statement, summary = saved(asha), saved(asha, "cdr", {"rows": [NUMBER_ROW]})
    assert withdraw(asha, statement, what="cdr").status_code == 404
    assert withdraw(asha, summary).status_code == 404  # the statements route withdraws only statements
    assert withdraw(asha, summary, what="cdr").status_code == 200
    listed = asha.get("/trace/case-1/cdr").json()
    assert listed["imports"] == [] and listed["withdrawn_count"] == 1
    assert asha.get("/trace/case-1/cdr", params={"withdrawn": 1}).json()["imports"][0]["withdrawn"]["reason"] == REASON
    assert len(asha.get("/trace/case-1/statements").json()["imports"]) == 1  # the statement still stands


def test_with_the_flags_off_nothing_is_withdrawn(monkeypatch):
    asha = signed_in("asha")
    statement, summary = saved(asha), saved(asha, "cdr", {"rows": [NUMBER_ROW]})
    monkeypatch.setattr(config, "STATEMENT_IMPORT", False)
    monkeypatch.setattr(config, "CDR_IMPORT", False)
    assert withdraw(asha, statement).status_code == 403
    assert withdraw(asha, summary, what="cdr").status_code == 403
    with models.session() as s:
        assert all(r.withdrawn_at is None for r in s.scalars(select(models.StatementImport)))


def test_the_audit_log_holds_the_import_id_never_the_reason(caplog):
    caplog.set_level(logging.DEBUG)
    asha = signed_in("asha")
    statement, summary = saved(asha), saved(asha, "cdr", {"rows": [NUMBER_ROW]})
    withdraw(asha, statement)
    withdraw(asha, summary, what="cdr")
    asha.get("/trace/case-1/statements", params={"withdrawn": 1})
    with models.session() as s:
        events = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action.like("%.withdraw"))).all()
        shown = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "statement.list")).all()
    assert [(e.action, json.loads(e.detail)) for e in events] == [
        ("statement.withdraw", {"import_id": statement}), ("cdr.withdraw", {"import_id": summary})]
    assert json.loads(shown[-1].detail) == {"withdrawn": True}
    assert "TEST WRONG CASE" not in caplog.text


def test_g7_statements_2_goes_down_and_up_again_keeping_the_imports():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    asha = signed_in("asha")
    saved(asha)
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with models._engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.downgrade(settings, "g7_statements_1")
    assert "withdrawn_at" not in {c["name"] for c in inspect(models._engine).get_columns("statement_imports")}
    models.init_db()
    assert len(asha.get("/trace/case-1/statements").json()["imports"]) == 1
