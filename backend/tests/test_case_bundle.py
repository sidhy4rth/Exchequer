"""The case bundle (app/case_bundle.py, routes/case_bundle.py): suite feature 6, #186.

One zip of what a case already holds: the signed report as the report download
serves it, each register as CSV with its history, the audit trail, and a
MANIFEST.txt whose hashes let anyone check the files are unchanged since
download. Only for the browser or unit that traced the case (or a public demo
case), behind EXCHEQUER_CASE_BUNDLE. Throwaway SQLite.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import case_bundle, config, exhibits, models, ownership, signing
from app.auth import User
from app.main import app

ALICE, BOB = "a" * 32, "b" * 32
HEAD = {ownership.OWNER_HEADER: ALICE}
CASE = {
    "address": "0xseed", "chain": "ethereum", "chain_name": "Ethereum Mainnet", "asset": "ETH",
    "direction": "outgoing", "graph": {"nodes": [{"id": "0xseed"}], "edges": []}, "confidence_detail": {},
    "exchange": "Binance", "exchange_address": "0xdep", "exchange_label": "Binance 14",
    "trace_path": [{"address": "0xseed", "depth": 0}], "risk_matches": [], "follow_ons": [],
}
NOTE = "kept in locker four"
FILES = ["report.txt", "report.pdf", "exhibits.csv", "exhibits-custody.csv", "assets.csv", "assets-history.csv",
         "requests.csv", "requests-history.csv", "identifiers.csv", "identifiers-history.csv", "audit-trail.csv",
         "MANIFEST.txt"]


@pytest.fixture
def engine(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'b.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    monkeypatch.setattr(config, "CASE_BUNDLE", True)
    models.init_db()
    models.save_case("case-1", "0xseed", CASE, owner_hash=ownership.owner_hash(ALICE))
    return engine


@pytest.fixture
def client(engine):
    return TestClient(app)


def viewer(key=ALICE, unit=None, officer=None):
    return User(id=f"officer-{officer}" if officer else "demo", role="officer", unit="Cyber Cell",
                owner_hash=ownership.owner_hash(key) if key else None, demo=officer is None,
                officer_id=officer, unit_id=unit)


def an_exhibit(case_id="case-1", who=None):
    who = who or viewer()
    return exhibits.create(who.owner_hash, case_id, {
        "kind": "phone_extraction", "label": "Accused's phone", "tool": "Cellebrite UFED 7.69",
        "sha256": "9f" * 32, "made_on": "2026-11-01", "holder": "SI Iyer", "notes": NOTE}, who)


def bundle(client, case_id="case-1", headers=HEAD):
    got = client.get(f"/trace/{case_id}/bundle", headers=headers)
    assert got.status_code == 200, got.text
    return zipfile.ZipFile(io.BytesIO(got.content))


def manifest_entries(zf):
    body = zf.read("MANIFEST.txt").decode()
    return re.findall(r"^\d+\. (\S+)\n   Size: (\d+) bytes\n   SHA-256: ([0-9a-f]{64})$", body, re.M), body


def test_the_bundle_holds_the_report_each_register_its_history_and_the_audit_trail_in_a_fixed_order(client):
    made = an_exhibit()
    exhibits.update(made["exhibit_id"], {"holder": "Inspector Rao", "note": "handed over for analysis"}, viewer())
    zf = bundle(client)
    assert zf.namelist() == FILES == case_bundle.names()
    rows = list(csv.DictReader(io.StringIO(zf.read("exhibits.csv").decode())))
    assert [(r["exhibit_id"], r["holder"], r["sha256"]) for r in rows] == [(made["exhibit_id"], "Inspector Rao", "9f" * 32)]
    custody = list(csv.DictReader(io.StringIO(zf.read("exhibits-custody.csv").decode())))
    assert [c["action"] for c in custody] == ["recorded", "changed"]
    assert json.loads(custody[1]["details"]) == {"changed": ["holder"], "note": "handed over for analysis"}
    assert zf.read("assets.csv").decode().startswith("asset_id,case_id,")  # empty, but there


def test_the_report_files_are_the_report_downloads_bytes_and_the_text_verifies(client):
    zf = bundle(client)
    assert zf.read("report.txt") == client.get("/trace/case-1/report?format=text", headers=HEAD).content
    assert zf.read("report.pdf") == client.get("/trace/case-1/report?format=pdf", headers=HEAD).content
    assert signing.verify_report(zf.read("report.txt").decode())["genuine"] is True


def test_the_manifest_hashes_and_sizes_match_the_bytes_and_say_where_to_verify(client):
    zf = bundle(client)
    entries, body = manifest_entries(zf)
    assert [name for name, _, _ in entries] == FILES[:-1]
    for name, size, digest in entries:
        data = zf.read(name)
        assert (len(data), hashlib.sha256(data).hexdigest()) == (int(size), digest)
    assert "Case: case-1" in body and "Downloaded by: demo-" in body and "/verify" in body
    assert "unchanged since download" in body and "s.63(4) certificate drafts" in body
    assert not re.search(r"(?i)certified|admissible", body)


def test_another_browser_holding_the_link_is_refused_and_nothing_is_recorded(client, engine):
    an_exhibit()
    got = client.get("/trace/case-1/bundle", headers={ownership.OWNER_HEADER: BOB})
    assert got.status_code == 403
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_events WHERE action='case.bundle_download'")).scalar() == 0


def test_the_unit_that_traced_a_case_may_bundle_it_and_another_unit_may_not():
    stored = models.Case(id="c", address="0xseed", created_at="", result_json="{}", owner_hash="f" * 64, unit_id=7)
    assert case_bundle.allowed(stored, viewer(BOB, unit=7, officer=3)) == (True, "f" * 64)
    assert case_bundle.allowed(stored, viewer(BOB, unit=8, officer=4))[0] is False
    assert case_bundle.allowed(stored, viewer(None))[0] is False


def test_a_public_demo_case_bundles_for_anyone_with_only_their_own_rows_and_no_audit_trail(client, engine):
    demo = sorted(ownership.demo_addresses())[0]
    models.save_case("demo-case", demo, {**CASE, "address": demo})
    an_exhibit("demo-case", viewer(BOB))
    zf = bundle(client, "demo-case")  # Alice: the exhibit is Bob's
    assert "audit-trail.csv" not in zf.namelist()
    assert zf.read("exhibits.csv").decode().count("\n") == 1  # the header only
    assert "audit-trail.csv: only the browser or unit" in zf.read("MANIFEST.txt").decode()


def test_flag_off_answers_404(client, monkeypatch):
    monkeypatch.setattr(config, "CASE_BUNDLE", False)
    assert client.get("/trace/case-1/bundle", headers=HEAD).status_code == 404
    assert client.get("/case-bundle", headers=HEAD).status_code == 404


def test_the_download_is_audited_by_its_file_count_only(client, engine):
    an_exhibit()
    bundle(client)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT action, detail FROM audit_events")).all()
    assert [json.loads(d) for a, d in rows if a == "case.bundle_download"] == [{"files": len(FILES)}]
    assert not any(NOTE in d for _, d in rows)


def test_a_bundle_past_the_cap_is_refused_with_413(client, monkeypatch):
    monkeypatch.setattr(case_bundle, "MAX_BYTES", 1000)
    got = client.get("/trace/case-1/bundle", headers=HEAD)
    assert got.status_code == 413 and "larger than" in got.json()["detail"]


def test_a_cell_that_would_run_as_a_spreadsheet_formula_is_quoted(client):
    who = viewer()
    exhibits.create(who.owner_hash, "case-1", {"kind": "document", "label": "=HYPERLINK(1)", "tool": "Notes 1",
                                              "md5": "5d" * 16, "made_on": "2026-11-01"}, who)
    row = next(csv.DictReader(io.StringIO(bundle(client).read("exhibits.csv").decode())))
    assert row["label"] == "'=HYPERLINK(1)"


def test_the_probe_lists_the_files_when_on(client):
    assert client.get("/case-bundle", headers=HEAD).json()["files"] == FILES
