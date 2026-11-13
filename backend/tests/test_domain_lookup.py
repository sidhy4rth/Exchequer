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

from app import accounts, config, domain_lookup, identifiers, models, ownership, rate_limit
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
        if urlsplit(url).hostname == "rdap.verisign.com":
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


def test_the_cap_is_counted_again_before_a_lookup_is_kept(asked, monkeypatch):
    """A second click while the first lookup is still running must not take it past the cap."""
    monkeypatch.setattr(domain_lookup, "LOOKUPS_PER_IDENTIFIER", 1)
    row = add()
    first = domain_lookup.look_up

    def meanwhile(name):
        found = first(name)
        monkeypatch.setattr(domain_lookup, "look_up", first)
        domain_lookup.run_and_keep(row["identifier_id"], viewer())  # the other click, finished first
        return found

    monkeypatch.setattr(domain_lookup, "look_up", meanwhile)
    with pytest.raises(IdentifierError, match="already looked up"):
        domain_lookup.run_and_keep(row["identifier_id"], viewer())
    with models.session() as s:
        assert len(s.scalars(select(models.DomainLookup)).all()) == 1


# -- oddly shaped answers and slow servers ----------------------------------------------------------
@pytest.mark.parametrize("body", [b"[]", b'"text"', b'{"events": 5, "entities": {"a": 1}, "nameservers": "ns1"}',
                                  b'{"entities": [{"roles": "registrar", "vcardArray": 7, "publicIds": 3}]}'])
def test_an_oddly_shaped_rdap_or_dns_answer_is_a_note_never_a_crash(body, monkeypatch):
    def fake(url, params=None, accept=""):
        if url == domain_lookup.BOOTSTRAP_URL:
            return 200, json.dumps({"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]}).encode()
        return 200, body

    monkeypatch.setattr(domain_lookup, "_get", fake)
    found = domain_lookup.look_up("example.com")
    if body.startswith(b"{"):  # an object, however odd, gives a record with empty facts
        assert found["rdap"]["registrar"] == "" and found["rdap"]["name_servers"] == []
    else:
        assert found["rdap"] is None and found["rdap_note"] == "The registry's answer was not an RDAP record."
        assert found["dns_note"] == "The DNS resolver's answer could not be read."
    assert len(found["records"]) == 5  # bootstrap, RDAP and three DNS answers, all kept as evidence


@pytest.mark.parametrize("body", [b"[]", b'{"services": {"com": 1}}', b'{"services": [5, [["com"]], [["com"], "x"]]}'])
def test_an_oddly_shaped_bootstrap_file_stops_with_a_reason_or_is_skipped(body, monkeypatch):
    monkeypatch.setattr(domain_lookup, "_get", lambda url, params=None, accept="": (200, body))
    if b"services" in body and body.startswith(b'{"services": ['):
        assert domain_lookup.look_up("example.com")["rdap_note"].startswith("The .com registry offers no RDAP")
    else:
        with pytest.raises(domain_lookup.LookupError_, match="could not be read"):
            domain_lookup.look_up("example.com")


def test_a_slow_server_cannot_hold_a_lookup_past_its_deadline(monkeypatch):
    """httpx's timeout is per read; the deadline is for the whole lookup, checked as bytes arrive."""
    now = [1000.0]
    monkeypatch.setattr(domain_lookup, "_clock", lambda: now[0])

    def slow(request):
        now[0] += 20  # each answer takes 20 seconds to arrive
        hit = FIXTURES.get(str(request.url).split("?")[0] if "dns-query" not in str(request.url) else "", None)
        return httpx.Response(200, content=hit["body"].encode() if hit else b"{}")

    monkeypatch.setattr(domain_lookup, "_transport", httpx.MockTransport(slow))
    found = domain_lookup.look_up("example.com")  # bootstrap in 20 s; the registry's answer passes 30 s
    assert found["rdap"] is None and "longer than 30 seconds" in found["rdap_note"]
    assert found["dns"] == {} and "longer than 30 seconds" in found["dns_note"]
    assert [r["source"] for r in found["records"]] == ["rdap-bootstrap"]
    assert getattr(domain_lookup._deadline, "at", None) is None  # the next lookup starts with a full 30 s


# -- routes ---------------------------------------------------------------------------------------
H = {ownership.OWNER_HEADER: ALICE}


PW = "officer-password-long-2"


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
    assert signed_in("esha", BOB).post(f"/identifiers/{iid}/lookup").status_code == 404  # another unit

    def down(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(domain_lookup, "_get", down)
    assert client.post(f"/identifiers/{iid}/lookup", headers=H).status_code == 502


def test_the_demo_caller_never_makes_the_server_look_anything_up(asked, monkeypatch):
    monkeypatch.setattr(config, "OSINT_LOOKUPS", True)
    demo = TestClient(app)
    iid = _post_domain(demo)
    refused = demo.post(f"/identifiers/{iid}/lookup", headers=H)
    assert refused.status_code == 403 and "Sign in as an officer" in refused.json()["detail"]
    listed = demo.get("/trace/case-1/identifiers", headers=H).json()
    assert listed["lookups_enabled"] is False and listed["lookups_note"].startswith("Sign in as an officer")
    assert asked == []


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
