"""The draft s.63(4) certificate for Exchequer's own report (certificates.draft_report).

The record an officer produces is the report file they downloaded, PDF or text.
The server cannot rebuild those exact bytes later (rendered reports are kept in
memory only), so the officer gives the file itself: it must be a genuine,
unchanged Exchequer report of this case, and the certificate states the SHA-256
of exactly those bytes, with what the signature check found in the hash report.
"""
from __future__ import annotations

import base64
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import certificates, models, ownership
from app.auth import User
from app.certificates import CertificateError
from app.main import app
from app.report import build_report, render_text_report
from app.report_pdf import render_pdf
from test_report import MID, full_result

DEVICE = {"device": "Server", "make_model": "", "other_info": ""}


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True))
    models.init_db()
    models.save_case("case-1", MID, full_result())
    models.save_case("case-2", MID, full_result())


def viewer():
    return User(id="demo", role="officer", unit=None, owner_hash=ownership.owner_hash("a" * 32), demo=True,
                officer_id=None, unit_id=None)


def text_report(case_id="case-1") -> bytes:
    return render_text_report(build_report(models.get_case(case_id))).encode()


def pdf_report(case_id="case-1") -> bytes:
    report = build_report(models.get_case(case_id))
    return render_pdf(report, render_text_report(report))


def draft(body: bytes, name="exchequer-case-1.txt", details=None, case="case-1"):
    return certificates.draft_report(case, body, name, DEVICE if details is None else details, viewer())


def test_a_genuine_text_report_gets_the_sha256_of_exactly_its_bytes():
    body = text_report()
    out = certificates.as_text(draft(body))
    sha = hashlib.sha256(body).hexdigest()
    part_a = out[out.index("PART A"):out.index("PART B")]
    assert f"[x] SHA256: {sha}" in part_a and "[ ] SHA1:" in part_a and "[ ] MD5:" in part_a
    assert "Server [x]" in part_a
    report = out[out.index("HASH REPORT"):]
    for want in ("exchequer-case-1.txt", sha, f"{len(body):,} bytes", "Genuine", "case-1", "/verify"):
        assert want in report


def test_a_genuine_pdf_report_is_accepted_and_its_pages_were_compared():
    body = pdf_report()
    out = certificates.as_text(draft(body, "exchequer-case-1.pdf"))
    assert hashlib.sha256(body).hexdigest() in out
    assert "pages match the signed report" in out[out.index("HASH REPORT"):]


def test_the_draft_still_leaves_part_b_for_the_expert_and_says_it_is_a_draft():
    out = certificates.as_text(draft(text_report()))
    part_b = out[out.index("PART B"):out.index("HASH REPORT")]
    assert "[x]" not in part_b and "DRAFT" in out and "not valid until" in out


@pytest.mark.parametrize("change, why", [
    (lambda b: b.replace(b"Binance", b"Bitnance", 1), "not a genuine, unchanged Exchequer report"),
    (lambda b: b + b"AMENDMENT: added after signing\n", "not a genuine, unchanged Exchequer report"),
    (lambda b: b"just some notes\n", "not a genuine, unchanged Exchequer report"),
    (lambda b: b"\xff\xfe not text", "not a genuine, unchanged Exchequer report"),
    (lambda b: b"x" * (certificates.REPORT_MAX + 1), "larger than any Exchequer report"),
])
def test_a_changed_or_foreign_file_is_refused(change, why):
    with pytest.raises(CertificateError, match=why):
        draft(change(text_report()))


def test_another_cases_report_is_refused():
    with pytest.raises(CertificateError, match="report of case case-2"):
        draft(text_report("case-2"))


def test_what_the_officer_types_is_still_checked():
    with pytest.raises(CertificateError, match="seed phrase"):
        draft(text_report(), details={**DEVICE, "other_info": "abandon ability able about above absent absorb "
                                                               "abstract absurd abuse access accident"})


# -- the route ---------------------------------------------------------------------------------------------
H = {ownership.OWNER_HEADER: "a" * 32}
client = TestClient(app)


def post(body: bytes, case="case-1", **extra):
    return client.post(f"/trace/{case}/report-certificate", headers=H, json={
        "report_b64": base64.b64encode(body).decode(), "file_name": "exchequer-case-1.txt", **DEVICE, **extra})


def test_the_route_sends_the_pdf_and_audits_the_start_of_the_reports_hash_only():
    body = text_report()
    got = post(body)
    assert got.status_code == 200 and got.content.startswith(b"%PDF")
    assert got.headers["cache-control"] == "no-store"
    assert got.headers["content-disposition"] == 'attachment; filename="exchequer-case-1-s63-certificate-report-draft.pdf"'
    with models.session() as s:
        row = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "case.report_certificate_draft")).one()
    assert json.loads(row.detail) == {"report_sha256_16": hashlib.sha256(body).hexdigest()[:16]} and row.case_id == "case-1"


def test_the_route_refuses_a_changed_report_bad_base64_and_an_unknown_case():
    changed = post(text_report().replace(b"Binance", b"Bitnance", 1))
    assert changed.status_code == 400 and "not a genuine" in changed.json()["detail"]
    bad = client.post("/trace/case-1/report-certificate", headers=H, json={"report_b64": "%%%", "file_name": "x.txt"})
    assert bad.status_code == 400 and "base64" in bad.json()["detail"]
    assert post(text_report(), case="nope").status_code == 404
