"""POST /identifiers/{id}/lookup for a Telegram username (feature 4, OSINT slice 4).

Signed-in officers only, behind EXCHEQUER_OSINT_LOOKUPS and EXCHEQUER_TELEGRAM_LOOKUPS;
kept like a domain lookup, by source, time and SHA-256; audited by ids and yes/no only.
No test touches the network: telegram_lookup._get serves synthetic pages
(tests/fixtures/osint/telegram/, hand-written). Throwaway SQLite.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import accounts, config, models, ownership, rate_limit, telegram_lookup
from app.main import app

PAGES = Path(__file__).parent / "fixtures" / "osint" / "telegram"
ALICE, BOB = "a" * 32, "b" * 32
H = {ownership.OWNER_HEADER: ALICE}
PW = "officer-password-long-2"


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 't.db'}", future=True))
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    monkeypatch.setattr(config, "OSINT_LOOKUPS", True)
    monkeypatch.setattr(config, "TELEGRAM_LOOKUPS", True)


@pytest.fixture
def asked(monkeypatch):
    calls: list[str] = []

    def fake(url):
        calls.append(url)
        return 200, (PAGES / "scam_group.html").read_bytes()

    monkeypatch.setattr(telegram_lookup, "_get", fake)
    return calls


@pytest.fixture
def officers(monkeypatch):
    """Asha in Cyber Cell North, Esha in Cyber Cell South: signed-in officers."""
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**4)
    for limiter in rate_limit.LOGIN_LIMITS:
        limiter.reset()
    rate_limit.request_writes.reset()
    north, south = accounts.create_unit("Cyber Cell North"), accounts.create_unit("Cyber Cell South")
    accounts.create_officer("asha@example.org", "Asha Rao", north.id, "officer", password=PW)
    accounts.create_officer("esha@example.org", "Esha Sen", south.id, "officer", password=PW)


def signed_in(who, key):
    c = TestClient(app, base_url="https://testserver")
    signed = c.post("/auth/login", json={"email": f"{who}@example.org", "password": PW}, headers={accounts.CSRF_HEADER: "1"})
    assert signed.status_code == 200
    c.headers.update({ownership.OWNER_HEADER: key})
    return c


@pytest.fixture
def client(officers):
    return signed_in("asha", ALICE)


def _post(client, value="@Sample_Recovery"):
    made = client.post("/trace/case-1/identifiers", json={"kind": "telegram", "value": value}, headers=H)
    assert made.status_code == 201
    return made.json()["identifier_id"]


def test_an_officer_looks_up_a_username_and_sees_what_the_page_shows(client, asked):
    iid = _post(client)
    out = client.post(f"/identifiers/{iid}/lookup", headers=H)
    assert out.status_code == 200 and asked == ["https://t.me/sample_recovery"]
    found = out.json()
    assert found["kind"] == "telegram" and found["queried"] == "sample_recovery"
    assert found["page"]["title"] == "Sample Recovery Desk" and found["page"]["badges"] == ["fake", "scam"]
    assert [(s["source"], s["provider"], s["status"]) for s in found["sources"]] == [("telegram-page", "t.me", 200)]
    assert "body" not in found["sources"][0]  # the page stays in the store, not on screen
    listed = client.get("/trace/case-1/identifiers", headers=H).json()
    assert listed["telegram_lookups_enabled"] is True
    assert listed["identifiers"][0]["lookup"]["lookup_id"] == found["lookup_id"]


def test_the_page_is_kept_as_received_with_its_sha256(client, asked):
    client.post(f"/identifiers/{_post(client)}/lookup", headers=H)
    with models.session() as s:
        [kept] = s.scalars(select(models.DomainLookup)).all()
    [record] = json.loads(kept.records_json)
    sent = (PAGES / "scam_group.html").read_bytes()
    assert record["sha256"] == hashlib.sha256(sent).hexdigest() and record["body"] == sent.decode()
    assert kept.queried == "sample_recovery" and kept.case_id == "case-1"


def test_the_audit_has_ids_and_yes_or_no_never_the_username_or_the_page(client, asked):
    iid = _post(client)
    lookup_id = client.post(f"/identifiers/{iid}/lookup", headers=H).json()["lookup_id"]
    with models.session() as s:
        row = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "identifier.lookup")).one()
    assert json.loads(row.detail) == {"identifier_id": iid, "lookup_id": lookup_id, "kind": "telegram",
                                      "page": True, "shows_account": True}
    for words in ("sample", "Recovery", "SCAM", "members", "t.me"):
        assert words not in row.detail


def test_the_demo_caller_is_refused_and_t_me_is_never_asked(asked):
    demo = TestClient(app)
    iid = _post(demo)
    refused = demo.post(f"/identifiers/{iid}/lookup", headers=H)
    assert refused.status_code == 403 and "Sign in as an officer" in refused.json()["detail"]
    assert demo.get("/trace/case-1/identifiers", headers=H).json()["telegram_lookups_enabled"] is False
    assert asked == []


def test_an_officer_of_another_unit_gets_404(client, asked):
    iid = _post(client)
    assert signed_in("esha", BOB).post(f"/identifiers/{iid}/lookup").status_code == 404
    assert asked == []


def test_off_unless_the_telegram_flag_is_on_too(client, asked, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_LOOKUPS", False)
    iid = _post(client)
    refused = client.post(f"/identifiers/{iid}/lookup", headers=H)
    assert refused.status_code == 400 and refused.json()["detail"] == "Only a website domain can be looked up."
    assert client.get("/trace/case-1/identifiers", headers=H).json()["telegram_lookups_enabled"] is False
    monkeypatch.setattr(config, "OSINT_LOOKUPS", False)
    monkeypatch.setattr(config, "TELEGRAM_LOOKUPS", True)
    assert client.post(f"/identifiers/{iid}/lookup", headers=H).status_code == 403
    assert client.get("/trace/case-1/identifiers", headers=H).json()["telegram_lookups_enabled"] is False
    assert asked == []


def test_a_four_letter_username_on_the_register_is_not_looked_up(client, asked):
    iid = _post(client, "@abcd")  # the register keeps it; t.me is not asked
    refused = client.post(f"/identifiers/{iid}/lookup", headers=H)
    assert refused.status_code == 400 and "5 to 32" in refused.json()["detail"] and asked == []


def test_a_withdrawn_username_and_other_kinds_are_not_looked_up(client, asked):
    phone = client.post("/trace/case-1/identifiers", json={"kind": "phone", "value": "98765 43210"}, headers=H).json()
    refused = client.post(f"/identifiers/{phone['identifier_id']}/lookup", headers=H)
    assert refused.json()["detail"] == "Only a website domain or a Telegram username can be looked up."
    iid = _post(client)
    client.patch(f"/identifiers/{iid}", json={"status": "withdrawn", "note": "typo"}, headers=H)
    assert client.post(f"/identifiers/{iid}/lookup", headers=H).status_code == 400
    assert asked == []


def test_one_username_is_looked_up_a_bounded_number_of_times(client, asked, monkeypatch):
    from app import domain_lookup

    monkeypatch.setattr(domain_lookup, "LOOKUPS_PER_IDENTIFIER", 1)
    iid = _post(client)
    assert client.post(f"/identifiers/{iid}/lookup", headers=H).status_code == 200
    again = client.post(f"/identifiers/{iid}/lookup", headers=H)
    assert again.status_code == 400 and "already looked up 1 times" in again.json()["detail"]
