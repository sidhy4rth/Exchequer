"""The case identifier register (app/identifiers.py, routes/identifiers.py): suite feature 4.

A complaint carries more than a wallet: the scam site, the Telegram handle, the
phone number, the UPI ID the victim paid. The officer records each by hand for
the case. Each is kept as typed and normalised, so the same identifier reads the
same in every case. Nothing is deleted; a mistake is withdrawn with a reason.
Throwaway SQLite, no network.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm.exc import StaleDataError

from app import identifiers, models, ownership
from app.auth import User
from app.identifiers import IdentifierError
from app.main import app

ALICE, BOB = "a" * 32, "b" * 32
SEED = "abandon ability able about above absent absorb abstract absurd abuse access accident"


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'i.db'}", future=True))
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    models.save_case("case-2", "0xother", {"address": "0xother"})


def viewer(key=ALICE, unit=None, officer=None):
    return User(id=f"officer-{officer}" if officer else "demo", role="officer", unit="Cyber Cell" if unit else None,
                owner_hash=ownership.owner_hash(key), demo=officer is None, officer_id=officer, unit_id=unit)


def add(kind="domain", value="scam-shop.in", who=None, case="case-1", **more):
    who = who or viewer()
    return identifiers.create(who.owner_hash, case, {"kind": kind, "value": value, **more}, who)


# -- normalising ------------------------------------------------------------------------------
@pytest.mark.parametrize("typed, kept", [
    ("scam-shop.in", "scam-shop.in"),
    ("https://www.Scam-Shop.IN/pay?ref=1#top", "scam-shop.in"),
    ("http://pay.scam-shop.in:8443/login", "pay.scam-shop.in"),
    ("scam-shop.in.", "scam-shop.in"),
    ("münchen-pay.de", "xn--mnchen-pay-9db.de"),
])
def test_a_domain_is_kept_as_its_host_name_in_lower_case(typed, kept):
    assert identifiers.domain(typed) == kept


@pytest.mark.parametrize("typed", [
    "127.0.0.1", "http://10.0.0.5/admin", "[::1]", "localhost", "http://localhost:8000", "db.internal",
    "printer.local", "intranet", "metadata", "169.254.169.254", "user:pass@scam.in", "scam..in", "-scam.in",
    "scam.in1", "a.b.c.example",
])
def test_ip_addresses_local_and_reserved_names_are_never_a_domain(typed):
    with pytest.raises(IdentifierError):
        identifiers.domain(typed)


@pytest.mark.parametrize("typed, kept", [
    ("@Crypto_Help", "crypto_help"), ("t.me/Crypto_Help", "crypto_help"),
    ("https://t.me/crypto_help?start=1", "crypto_help"), ("crypto_help", "crypto_help"),
])
def test_a_telegram_username_loses_its_at_sign_and_link(typed, kept):
    assert identifiers.telegram(typed) == kept


@pytest.mark.parametrize("typed", ["@ab", "1crypto", "crypto help", "@" + "a" * 40])
def test_a_telegram_username_must_be_one_telegram_allows(typed):
    with pytest.raises(IdentifierError):
        identifiers.telegram(typed)


@pytest.mark.parametrize("typed, kept", [
    ("98765 43210", "+919876543210"), ("+91 98765-43210", "+919876543210"), ("09876543210", "+919876543210"),
    ("919876543210", "+919876543210"), ("0091 98765 43210", "+919876543210"), ("+44 20 7946 0958", "+442079460958"),
])
def test_a_phone_number_is_kept_with_its_country_code(typed, kept):
    assert identifiers.phone(typed) == kept


@pytest.mark.parametrize("typed", ["12345", "2345678901", "+91 12345 67890", "+91 98765", "call 98765 43210", "+0123456789"])
def test_a_phone_number_without_a_country_code_or_digits_is_refused(typed):
    with pytest.raises(IdentifierError):
        identifiers.phone(typed)


def test_a_upi_id_is_kept_in_lower_case_and_must_name_its_bank():
    assert identifiers.upi("Shop.Pay@OKAXIS") == "shop.pay@okaxis"
    for typed in ("shop.pay", "@okaxis", "shop pay@okaxis", "shop@1bank"):
        with pytest.raises(IdentifierError):
            identifiers.upi(typed)


# -- recording ----------------------------------------------------------------------------------
def test_an_identifier_keeps_what_was_typed_and_its_normal_form():
    row = add(value="https://www.Scam-Shop.in/pay", context="link in the WhatsApp chat")
    assert (row["kind"], row["value"], row["entered"]) == ("domain", "scam-shop.in", "https://www.Scam-Shop.in/pay")
    assert (row["context"], row["status"]) == ("link in the WhatsApp chat", "active")
    assert [h["action"] for h in row["history"]] == ["recorded"]


def test_the_same_identifier_twice_in_one_case_is_refused_but_another_case_may_have_it():
    add(kind="phone", value="98765 43210")
    with pytest.raises(identifiers.DuplicateIdentifier):
        add(kind="phone", value="+91 98765 43210")
    assert add(kind="phone", value="+919876543210", case="case-2")["value"] == "+919876543210"


@pytest.mark.parametrize("fields, why", [
    ({"kind": "email", "value": "x@y.in"}, "one of"),
    ({"kind": "upi", "value": ""}, "Enter"),
    ({"kind": "domain", "value": "x" * 301}, "longer"),
    ({"kind": "domain", "value": "scam.in", "context": SEED}, "seed|key"),
    ({"kind": "upi", "value": SEED}, "seed|key"),
])
def test_unknown_kinds_empty_values_and_secrets_are_refused(fields, why):
    who = viewer()
    with pytest.raises(IdentifierError, match=why):
        identifiers.create(who.owner_hash, "case-1", fields, who)


def test_an_unknown_case_is_refused():
    with pytest.raises(IdentifierError, match="No case"):
        add(case="nope")


def test_ordinary_notes_are_kept():
    row = add(notes="Victim says the site asked for a 10% fee before withdrawal.")
    assert row["notes"].startswith("Victim says")


# -- changing, withdrawing, nothing deleted -----------------------------------------------------
def test_withdrawing_needs_a_reason_and_keeps_the_identifier():
    row = add()
    with pytest.raises(IdentifierError, match="why"):
        identifiers.update(row["identifier_id"], {"status": "withdrawn"}, viewer())
    out = identifiers.update(row["identifier_id"], {"status": "withdrawn", "note": "typo, wrong site"}, viewer())
    assert out["status"] == "withdrawn" and out["changed"] == ["status"]
    assert [h["action"] for h in out["history"]] == ["recorded", "changed"]
    assert len(identifiers.list_for(viewer(), "case-1")) == 1


def test_a_withdrawn_identifier_takes_only_notes():
    row = add()
    identifiers.update(row["identifier_id"], {"status": "withdrawn", "note": "typo"}, viewer())
    with pytest.raises(IdentifierError, match="withdrawn"):
        identifiers.update(row["identifier_id"], {"context": "x"}, viewer())
    out = identifiers.update(row["identifier_id"], {"note": "victim confirmed the typo"}, viewer())
    assert out["history"][-1] == {**out["history"][-1], "action": "noted", "note": "victim confirmed the typo"}


def test_the_kind_and_value_never_change_and_status_cannot_return_to_active():
    row = add()
    with pytest.raises(IdentifierError, match="cannot be changed"):
        identifiers.update(row["identifier_id"], {"value": "other.in"}, viewer())
    with pytest.raises(IdentifierError, match="withdrawn"):
        identifiers.update(row["identifier_id"], {"status": "deleted", "note": "x"}, viewer())


def test_a_change_that_changes_nothing_adds_no_history():
    row = add(context="chat")
    out = identifiers.update(row["identifier_id"], {"context": "chat"}, viewer())
    assert out["changed"] == [] and len(out["history"]) == 1


def test_a_full_history_refuses_rather_than_dropping_the_first_entry(monkeypatch):
    monkeypatch.setattr(identifiers, "HISTORY_MAX", 2)
    row = add()
    identifiers.update(row["identifier_id"], {"note": "one"}, viewer())
    with pytest.raises(IdentifierError, match="full"):
        identifiers.update(row["identifier_id"], {"note": "two"}, viewer())


# -- who sees what ------------------------------------------------------------------------------
def test_another_browser_sees_and_changes_nothing():
    row = add()
    assert identifiers.list_for(viewer(BOB), "case-1") == []
    assert identifiers.update(row["identifier_id"], {"note": "x"}, viewer(BOB)) is None


def test_a_unit_shares_its_identifiers_and_its_duplicate_check_stays_inside_it():
    theirs = add(who=viewer(ALICE, unit=7, officer=1))
    assert [r["identifier_id"] for r in identifiers.list_for(viewer(BOB, unit=7, officer=2), "case-1")] == [theirs["identifier_id"]]
    assert add(who=viewer(BOB))["identifier_id"] != theirs["identifier_id"]  # not unit 7: not told about it


def test_a_viewer_with_no_owner_key_and_no_unit_reads_nothing():
    add()
    nobody = User(id="demo", role="officer", unit=None, owner_hash=None, demo=True, officer_id=None, unit_id=None)
    assert identifiers.list_for(nobody, "case-1") == []


# -- routes ---------------------------------------------------------------------------------------
H = {ownership.OWNER_HEADER: ALICE}


@pytest.fixture
def client():
    return TestClient(app)


def test_the_routes_add_list_and_withdraw(client):
    made = client.post("/trace/case-1/identifiers", json={"kind": "telegram", "value": "@Crypto_Help"}, headers=H)
    assert made.status_code == 201 and made.json()["value"] == "crypto_help"
    iid = made.json()["identifier_id"]
    listed = client.get("/trace/case-1/identifiers", headers=H).json()
    assert listed["count"] == 1 and set(listed["kinds"]) == {"domain", "telegram", "phone", "upi"}
    out = client.patch(f"/identifiers/{iid}", json={"status": "withdrawn", "note": "wrong handle"}, headers=H)
    assert out.status_code == 200 and out.json()["status"] == "withdrawn"


def test_the_routes_refuse_bad_input_duplicates_and_strangers(client):
    assert client.post("/trace/case-1/identifiers", json={"kind": "domain", "value": "localhost"}, headers=H).status_code == 400
    assert client.post("/trace/case-1/identifiers", json={"kind": "domain", "value": "scam.in"}).status_code == 400  # no owner key
    iid = client.post("/trace/case-1/identifiers", json={"kind": "domain", "value": "scam.in"}, headers=H).json()["identifier_id"]
    assert client.post("/trace/case-1/identifiers", json={"kind": "domain", "value": "www.scam.in"}, headers=H).status_code == 409
    assert client.patch(f"/identifiers/{iid}", json={"note": "x"}, headers={ownership.OWNER_HEADER: BOB}).status_code == 404


def test_the_routes_answer_a_clash_with_409(client, monkeypatch):
    iid = client.post("/trace/case-1/identifiers", json={"kind": "domain", "value": "scam.in"}, headers=H).json()["identifier_id"]

    def clash(*args):
        raise StaleDataError("always")

    monkeypatch.setattr(identifiers, "_update_once", clash)
    assert client.patch(f"/identifiers/{iid}", json={"note": "x"}, headers=H).status_code == 409


def test_the_audit_log_records_the_kind_never_the_value(client):
    iid = client.post("/trace/case-1/identifiers", json={"kind": "phone", "value": "98765 43210"}, headers=H).json()["identifier_id"]
    client.patch(f"/identifiers/{iid}", json={"context": "called the victim"}, headers=H)
    client.get("/trace/case-1/identifiers", headers=H)
    with models.session() as s:
        rows = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action.like("identifier.%"))).all()
    logged = [(r.action, json.loads(r.detail) if r.detail else None) for r in rows]
    assert logged[:2] == [
        ("identifier.add", {"identifier_id": iid, "kind": "phone"}),
        ("identifier.update", {"identifier_id": iid, "changed": ["context"]}),
    ]
    assert logged[2][0] == "identifier.list"
    assert "9876543210" not in json.dumps(logged)


def test_g7_identifiers_1_goes_down_and_up_again_keeping_the_cases():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from app import config
    add()
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with models._engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.downgrade(settings, "g7_exhibits_1")
    assert "case_identifiers" not in set(inspect(models._engine).get_table_names())
    assert models.get_case("case-1") is not None
    models.init_db()
    assert "case_identifiers" in set(inspect(models._engine).get_table_names())
