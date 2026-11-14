"""The statement routes (routes/statements.py): suite feature 5, behind EXCHEQUER_STATEMENT_IMPORT.

Synthetic rows only (see test_statement_imports.py). Throwaway SQLite, no network.
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config, models, ownership
from app.main import app
from test_statement_imports import ACCOUNT, BOB, EXCHANGE_ROW, H, UTR_ROW, store  # noqa: F401 -- the fixture

# -- the routes ------------------------------------------------------------------------------
@pytest.fixture
def client():
    return TestClient(app)


def test_with_the_flag_off_nothing_is_listed_or_saved(client, monkeypatch):
    monkeypatch.setattr(config, "STATEMENT_IMPORT", False)
    assert client.get("/trace/case-1/statements", headers=H).json() == {
        "case_id": "case-1", "enabled": False, "imports": [], "exchange_names": []}
    body = {"source": "bank", "currency": "INR", "rows": [UTR_ROW]}
    assert client.post("/trace/case-1/statements", json=body, headers=H).status_code == 403
    with models.session() as s:
        assert s.scalars(select(models.StatementImport)).all() == []


def test_the_routes_save_and_list(client):
    made = client.post("/trace/case-1/statements", json={"source": "bank", "currency": "INR", "rows": [UTR_ROW]}, headers=H)
    assert made.status_code == 201
    listed = client.get("/trace/case-1/statements", headers=H).json()
    assert listed["enabled"] and listed["count"] == 1 and listed["imports"][0]["rows"][0]["amount"] == "250000"
    assert "CoinDCX" in listed["exchange_names"]
    assert client.get("/trace/case-1/statements", headers={ownership.OWNER_HEADER: BOB}).json()["imports"] == []
    bad = {"source": "bank", "currency": "INR", "rows": [{**UTR_ROW, "date": "yesterday"}]}
    assert client.post("/trace/case-1/statements", json=bad, headers=H).status_code == 400
    assert client.post("/trace/case-1/statements", json={**bad, "rows": [UTR_ROW]}).status_code == 400  # no owner key


def test_the_audit_log_and_the_log_hold_counts_never_an_account_number(client, caplog):
    caplog.set_level(logging.DEBUG)
    body = {"source": "bank", "currency": "INR", "title": f"A/C {ACCOUNT}", "rows": [UTR_ROW, EXCHANGE_ROW]}
    iid = client.post("/trace/case-1/statements", json=body, headers=H).json()["import_id"]
    client.get("/trace/case-1/statements", headers=H)
    with models.session() as s:
        rows = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action.like("statement.%"))).all()
    logged = [(r.action, json.loads(r.detail) if r.detail else None) for r in rows]
    assert logged[0] == ("statement.save", {"import_id": iid, "source": "bank", "rows": 2, "reasons": {
        "amount_date": 1, "utr": 1, "exchange": 1, "tx_hash": 0}})
    assert logged[1][0] == "statement.list"
    for secret in (ACCOUNT, "SBINN26071000001", "607200000001", "TEST PAYEE"):
        assert secret not in json.dumps(logged) and secret not in caplog.text
