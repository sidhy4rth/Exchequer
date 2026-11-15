"""The export scan's server side (routes/export_scan.py, suite feature 2).

The scan runs in the officer's browser; the server only says whether it is
offered (config.EXPORT_SCAN) and records that a scan ran, by its counts. These
tests hold it to that: off means 404, and the audit row carries numbers only.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import config, models
from app.main import app

COUNTS = {"lines": 1200, "bytes": 48213, "addresses": 3, "tx_hashes": 2, "seed_runs": 1}


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})


@pytest.fixture
def client():
    return TestClient(app)


def _audit(action):
    with models.session() as s:
        return [json.loads(r.detail) if r.detail else None
                for r in s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == action)).all()]


def test_the_flag_is_registered_and_off_by_default():
    assert "EXCHEQUER_EXPORT_SCAN" in config.FLAGS
    assert config.FLAGS["EXCHEQUER_EXPORT_SCAN"]["on"] is False


def test_off_means_404_for_both_routes_and_nothing_audited(client, monkeypatch):
    monkeypatch.setattr(config, "EXPORT_SCAN", False)
    assert client.get("/trace/case-1/export-scan").status_code == 404
    assert client.post("/trace/case-1/export-scan", json=COUNTS).status_code == 404
    assert _audit("export_scan.open") == [] and _audit("export_scan.run") == []


def test_on_it_is_offered_for_a_case_and_the_open_is_audited(client, monkeypatch):
    monkeypatch.setattr(config, "EXPORT_SCAN", True)
    out = client.get("/trace/case-1/export-scan")
    assert out.status_code == 200 and out.json() == {"case_id": "case-1", "enabled": True}
    assert _audit("export_scan.open") == [{}]


def test_an_unknown_case_is_404(client, monkeypatch):
    monkeypatch.setattr(config, "EXPORT_SCAN", True)
    assert client.get("/trace/no-such-case/export-scan").status_code == 404
    assert client.post("/trace/no-such-case/export-scan", json=COUNTS).status_code == 404


def test_a_scan_is_audited_by_its_counts_only(client, monkeypatch):
    monkeypatch.setattr(config, "EXPORT_SCAN", True)
    out = client.post("/trace/case-1/export-scan", json=COUNTS)
    assert out.status_code == 201 and out.json() == {"case_id": "case-1", "recorded": True}
    assert _audit("export_scan.run") == [COUNTS]


@pytest.mark.parametrize("extra", [
    {"words": "abandon ability able about above absent absorb abstract absurd abuse access accident"},
    {"address": "THWYhwUQnBcKpwSxaXjqv18RPtSoK4C5Ph"},
    {"file_name": "chats.csv"},
])
def test_anything_but_counts_is_refused(client, monkeypatch, extra):
    monkeypatch.setattr(config, "EXPORT_SCAN", True)
    assert client.post("/trace/case-1/export-scan", json={**COUNTS, **extra}).status_code == 422
    assert _audit("export_scan.run") == []


@pytest.mark.parametrize("bad", [{"lines": -1}, {"seed_runs": "many"}, {"bytes": 10**13}])
def test_counts_must_be_sensible_numbers(client, monkeypatch, bad):
    monkeypatch.setattr(config, "EXPORT_SCAN", True)
    assert client.post("/trace/case-1/export-scan", json={**COUNTS, **bad}).status_code == 422
