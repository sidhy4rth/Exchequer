"""Domain lookups (app/domain_lookup.py, routes/identifiers.py): suite feature 4, OSINT slice 2.

For a domain on a case's identifier register: its RDAP registration record from
its own registry (found through IANA's bootstrap file) and its DNS records from
one fixed resolver, every response kept with its source, time and SHA-256.

No test touches the network (CLAUDE.md rule 8). Responses come from
tests/fixtures/osint/responses.json, which scripts/record_osint_fixtures.py
recorded live; never edit it by hand. Throwaway SQLite.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import config, domain_lookup, identifiers, models, ownership
from app.auth import User
from app.identifiers import IdentifierError
from app.main import app

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "osint" / "responses.json").read_text())
ALICE, BOB = "a" * 32, "b" * 32
ALLOWED_HOSTS = {"data.iana.org", "cloudflare-dns.com", "rdap.verisign.com", "rdap.nixiregistry.in"}


def _key(url, params):
    return url if not params else f"{url}?" + "&".join(f"{k}={v}" for k, v in params.items())


@pytest.fixture
def asked(monkeypatch):
    """Replay the recorded responses, and list every URL asked for."""
    calls = []

    def replay(url, params=None, accept="application/json"):
        calls.append(_key(url, params))
        hit = FIXTURES[_key(url, params)]
        return hit["status"], hit["body"].encode()

    monkeypatch.setattr(domain_lookup, "_get", replay)
    return calls


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'd.db'}", future=True))
    monkeypatch.setattr(domain_lookup, "_bootstrap", {"at": 0.0, "map": {}, "record": None})
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})


def viewer(key=ALICE, unit=None, officer=None):
    return User(id=f"officer-{officer}" if officer else "demo", role="officer", unit="Cyber Cell" if unit else None,
                owner_hash=ownership.owner_hash(key), demo=officer is None, officer_id=officer, unit_id=unit)


def add(kind="domain", value="example.com", who=None):
    who = who or viewer()
    return identifiers.create(who.owner_hash, "case-1", {"kind": kind, "value": value}, who)


# -- what a lookup finds -------------------------------------------------------------------------
def test_a_com_domain_gives_its_registrar_dates_and_name_servers_from_its_registry(asked):
    found = domain_lookup.look_up("example.com")
    rdap = found["rdap"]
    assert (rdap["name"], rdap["registered_on"], rdap["registrar_iana_id"]) == ("example.com", "1995-08-14", "376")
    assert rdap["registrar"] and rdap["expires_on"] > rdap["registered_on"]
    assert rdap["name_servers"] == found["dns"]["NS"]
    assert found["dns"]["A"] and found["rdap_note"] == "" and found["dns_note"] == ""


def test_an_in_domain_comes_from_the_in_registry_with_its_abuse_contact(asked):
    rdap = domain_lookup.look_up("nixi.in")["rdap"]
    assert rdap["registered_on"] == "2004-12-16"
    assert rdap["abuse_email"] == "registry@nixi.in"
    assert any(urlsplit(u).hostname == "rdap.nixiregistry.in" for u in asked)


def test_a_name_inside_a_registered_domain_falls_back_to_that_domain(asked):
    found = domain_lookup.look_up("sub.example.com")
    rdap_calls = [r for r in found["records"] if r["source"] == "rdap"]
    assert [r["status"] for r in rdap_calls] == [404, 200]
    assert found["rdap"]["name"] == "example.com"
    assert found["queried"] == "sub.example.com" and found["dns"]["A"] == []


def test_every_response_is_kept_with_its_source_time_and_the_sha256_of_its_body(asked):
    found = domain_lookup.look_up("example.com")
    assert {r["source"] for r in found["records"]} == {"rdap-bootstrap", "rdap", "dns"}
    for r in found["records"]:
        recorded = FIXTURES[r["request"]]["body"].encode()
        assert r["sha256"] == hashlib.sha256(recorded).hexdigest() and r["bytes"] == len(recorded)
        assert r["fetched_at"] and r["provider"] == urlsplit(r["request"]).hostname
    assert "body" not in found["records"][0]  # the bootstrap list is kept by its hash only


def test_only_iana_the_registry_iana_names_and_the_fixed_resolver_are_ever_asked(asked):
    for name in ("example.com", "sub.example.com", "nixi.in"):
        domain_lookup.look_up(name)
    assert {urlsplit(u).hostname for u in asked} <= ALLOWED_HOSTS


def test_the_bootstrap_list_is_fetched_once_and_reused(asked):
    domain_lookup.look_up("example.com")
    domain_lookup.look_up("nixi.in")
    assert sum(u == domain_lookup.BOOTSTRAP_URL for u in asked) == 1


@pytest.mark.parametrize("name", ["127.0.0.1", "localhost", "http://169.254.169.254/latest", "db.internal", "[::1]"])
def test_a_private_or_reserved_name_is_refused_before_anything_is_fetched(asked, name):
    with pytest.raises(IdentifierError):
        domain_lookup.look_up(name)
    assert asked == []


# -- when a source fails --------------------------------------------------------------------------
def _bootstrap_body(tlds_to_url):
    return json.dumps({"services": [[[t], [u]] for t, u in tlds_to_url.items()]}).encode()


def test_a_tld_with_no_rdap_service_says_so_and_still_reads_dns(monkeypatch):
    def fake(url, params=None, accept="application/json"):
        if url == domain_lookup.BOOTSTRAP_URL:
            return 200, _bootstrap_body({"com": "https://rdap.verisign.com/com/v1/"})
        return 200, json.dumps({"Answer": [{"type": 1, "data": "203.0.113.7"}]}).encode()

    monkeypatch.setattr(domain_lookup, "_get", fake)
    found = domain_lookup.look_up("scam-shop.in")
    assert found["rdap"] is None and "no RDAP service" in found["rdap_note"]
    assert found["dns"]["A"] == ["203.0.113.7"]


def test_a_bootstrap_entry_that_is_not_https_is_never_used(monkeypatch):
    monkeypatch.setattr(domain_lookup, "_get", lambda url, params=None, accept="": (
        200, _bootstrap_body({"com": "http://rdap.example.net/"})) if url == domain_lookup.BOOTSTRAP_URL else (200, b"{}"))
    assert domain_lookup.look_up("example.com")["rdap"] is None


def test_a_registry_error_or_an_unreachable_resolver_is_a_note_not_a_crash(monkeypatch):
    def fake(url, params=None, accept="application/json"):
        if url == domain_lookup.BOOTSTRAP_URL:
            return 200, _bootstrap_body({"com": "https://rdap.verisign.com/com/v1/"})
        if url.startswith("https://rdap.verisign.com"):
            return 503, b"busy"
        raise httpx.ConnectError("down")

    monkeypatch.setattr(domain_lookup, "_get", fake)
    found = domain_lookup.look_up("example.com")
    assert found["rdap"] is None and "503" in found["rdap_note"]
    assert found["dns"] == {} and "could not be reached" in found["dns_note"]


def test_iana_unreachable_stops_the_lookup_with_a_reason(monkeypatch):
    def down(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(domain_lookup, "_get", down)
    with pytest.raises(domain_lookup.LookupError_, match="IANA"):
        domain_lookup.look_up("example.com")


def test_the_http_client_never_follows_a_redirect_and_refuses_a_huge_answer(monkeypatch):
    def handler(request):
        if request.url.path == "/moved":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/"})
        return httpx.Response(200, content=b"x" * (domain_lookup.BODY_MAX + 1))

    monkeypatch.setattr(domain_lookup, "_transport", httpx.MockTransport(handler))
    assert domain_lookup._get("https://rdap.verisign.com/moved")[0] == 302
    with pytest.raises(domain_lookup.LookupError_, match="more than"):
        domain_lookup._get("https://rdap.verisign.com/huge")


# -- kept per identifier --------------------------------------------------------------------------
def test_a_lookup_is_kept_and_the_newest_one_is_listed_with_its_identifier(asked):
    row = add()
    first = domain_lookup.run_and_keep(row["identifier_id"], viewer())
    second = domain_lookup.run_and_keep(row["identifier_id"], viewer())
    assert first["rdap"]["registered_on"] == "1995-08-14" and first["case_id"] == "case-1"
    assert domain_lookup.latest_for([row["identifier_id"]])[row["identifier_id"]]["lookup_id"] == second["lookup_id"]
    assert all("body" not in s for s in second["sources"])  # bodies stay in the store, not on screen
    with models.session() as s:
        kept = s.scalars(select(models.DomainLookup)).all()
    assert len(kept) == 2 and all(r["body"] for r in json.loads(kept[0].records_json) if r["source"] != "rdap-bootstrap")


def test_only_an_active_domain_the_viewer_may_read_is_looked_up(asked):
    phone = add(kind="phone", value="98765 43210")
    with pytest.raises(IdentifierError, match="Only a website"):
        domain_lookup.run_and_keep(phone["identifier_id"], viewer())
    site = add()
    assert domain_lookup.run_and_keep(site["identifier_id"], viewer(BOB)) is None
    identifiers.update(site["identifier_id"], {"status": "withdrawn", "note": "typo"}, viewer())
    with pytest.raises(IdentifierError, match="withdrawn"):
        domain_lookup.run_and_keep(site["identifier_id"], viewer())
    assert asked == []


def test_one_domain_is_looked_up_a_bounded_number_of_times(asked, monkeypatch):
    monkeypatch.setattr(domain_lookup, "LOOKUPS_PER_IDENTIFIER", 1)
    row = add()
    domain_lookup.run_and_keep(row["identifier_id"], viewer())
    with pytest.raises(IdentifierError, match="already looked up"):
        domain_lookup.run_and_keep(row["identifier_id"], viewer())


# -- routes ---------------------------------------------------------------------------------------
H = {ownership.OWNER_HEADER: ALICE}


@pytest.fixture
def client():
    return TestClient(app)


def _post_domain(client, value="example.com"):
    return client.post("/trace/case-1/identifiers", json={"kind": "domain", "value": value}, headers=H).json()["identifier_id"]


def test_lookups_are_off_unless_the_flag_is_on(client, asked, monkeypatch):
    monkeypatch.setattr(config, "OSINT_LOOKUPS", False)
    iid = _post_domain(client)
    assert client.post(f"/identifiers/{iid}/lookup", headers=H).status_code == 403
    assert client.get("/trace/case-1/identifiers", headers=H).json()["lookups_enabled"] is False
    assert asked == []


def test_the_route_looks_up_lists_and_audits_without_the_domain(client, asked, monkeypatch):
    monkeypatch.setattr(config, "OSINT_LOOKUPS", True)
    iid = _post_domain(client)
    out = client.post(f"/identifiers/{iid}/lookup", headers=H)
    assert out.status_code == 200 and out.json()["rdap"]["registered_on"] == "1995-08-14"
    listed = client.get("/trace/case-1/identifiers", headers=H).json()
    assert listed["lookups_enabled"] is True and listed["identifiers"][0]["lookup"]["lookup_id"] == out.json()["lookup_id"]
    with models.session() as s:
        row = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "identifier.lookup")).one()
    assert row.case_id == "case-1"
    assert json.loads(row.detail) == {"identifier_id": iid, "lookup_id": out.json()["lookup_id"], "rdap": True, "dns": True}
    assert "example.com" not in row.detail


def test_the_route_answers_strangers_404_and_a_dead_iana_502(client, monkeypatch):
    monkeypatch.setattr(config, "OSINT_LOOKUPS", True)
    iid = _post_domain(client)
    assert client.post(f"/identifiers/{iid}/lookup", headers={ownership.OWNER_HEADER: BOB}).status_code == 404

    def down(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(domain_lookup, "_get", down)
    assert client.post(f"/identifiers/{iid}/lookup", headers=H).status_code == 502


def test_g7_domain_lookups_1_goes_down_and_up_again_keeping_the_identifiers():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    add()
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with models._engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.downgrade(settings, "g7_identifiers_1")
    assert "domain_lookups" not in set(inspect(models._engine).get_table_names())
    assert len(identifiers.list_for(viewer(), "case-1")) == 1
    models.init_db()
    assert "domain_lookups" in set(inspect(models._engine).get_table_names())
