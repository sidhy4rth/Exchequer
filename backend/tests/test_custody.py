"""Custody wallets (app/custody.py, routes/custody.py): suite feature 9.

Seized crypto is moved into a multisig wallet whose keys sit on hardware wallets
held by named officers. Exchequer keeps the record of that wallet -- chain,
address, scheme, threshold m of n, the signers by name, role and unit, who set
it up and when, and the asset-register rows moved into it -- never a key. Every
text field refuses a private key or seed phrase. Throwaway SQLite, no network.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm.exc import StaleDataError

from app import assets, config, custody, models, ownership
from app.auth import User
from app.custody import CustodyError, DuplicateWallet
from app.main import app

ALICE, BOB = "a" * 32, "b" * 32
TX = "ab" * 32
CUSTODY = "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU"  # the custody address test_assets.py uses
TODAY = date(2026, 11, 14)
SEED = "abandon ability able about above absent absorb abstract absurd abuse access accident"
SIGNERS = [{"name": "Insp. Rao", "role": "Inspector", "unit": "Cyber Cell"},
           {"name": "SI Iyer", "role": "Sub-Inspector", "unit": "Cyber Cell"},
           {"name": "SI Pal", "role": "Sub-Inspector", "unit": "Cyber Cell"}]


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True))
    monkeypatch.setattr(custody, "_today", lambda: TODAY)
    monkeypatch.setattr(assets, "_today", lambda: TODAY)
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    models.save_case("case-2", "0xseed2", {"address": "0xseed2"})


def viewer(key=ALICE, unit=None, officer=None):
    return User(id=f"officer-{officer}" if officer else "demo", role="officer", unit="Cyber Cell" if unit else None,
                owner_hash=ownership.owner_hash(key), demo=officer is None, officer_id=officer, unit_id=unit)


def wallet(**over):
    fields = {"chain": "tron", "address": CUSTODY, "scheme": "Tron multi-sign permission", "threshold": 2,
              "signers": [dict(s) for s in SIGNERS], "set_up_by": "Insp. Rao", "set_up_on": "2026-11-10"}
    fields.update(over)
    return fields


def add(fields=None, case_id="case-1", who=None):
    who = who or viewer()
    return custody.create(who.owner_hash, case_id, fields or wallet(), who)


def seized(case_id="case-1", holder="custody", who=None):
    who = who or viewer()
    fields = {"holder": holder, "asset": "USDT", "amount": "635", "chain": "tron", "held_at": CUSTODY,
              "tx_hash": TX if holder == "custody" else "", "seized_on": "2026-11-01"}
    return assets.create(who.owner_hash, case_id, fields, who)["asset_id"]


# -- recording a wallet -----------------------------------------------------------------------
def test_a_wallet_records_its_chain_address_scheme_threshold_and_signers_by_name():
    row = add()
    assert (row["chain"], row["address"], row["scheme"]) == ("tron", CUSTODY, "Tron multi-sign permission")
    assert (row["threshold"], row["signer_count"], row["proposer_may_sign"]) == (2, 3, False)
    assert row["signers"][0] == {"name": "Insp. Rao", "role": "Inspector", "unit": "Cyber Cell"}
    assert (row["set_up_by"], row["set_up_on"]) == ("Insp. Rao", "2026-11-10")
    assert [h["action"] for h in row["history"]] == ["recorded"]


def test_the_proposer_may_sign_only_when_the_scheme_is_recorded_as_allowing_it():
    assert add(wallet(proposer_may_sign=True))["proposer_may_sign"] is True
    assert add(wallet(proposer_may_sign="yes"), case_id="case-2")["proposer_may_sign"] is False


@pytest.mark.parametrize("over, why", [
    ({"threshold": 4}, "more than the number of signers"),
    ({"threshold": 1}, "at least two"),
    ({"threshold": "two"}, "whole number"),
    ({"threshold": True}, "whole number"),
    ({"signers": SIGNERS[:1]}, "between 2 and"),
    ({"signers": "Insp. Rao, SI Iyer"}, "between 2 and"),
    ({"chain": "bitcoin"}, "which chain"),
    ({"address": "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBV"}, "T followed by 33"),
    ({"chain": "ethereum"}, "0x followed by 40"),
    ({"scheme": ""}, "multisig scheme"),
    ({"set_up_by": ""}, "who set it up"),
    ({"set_up_on": "2026-12-01"}, "future"),
    ({"set_up_on": "14/11/2026"}, "YYYY-MM-DD"),
])
def test_missing_or_malformed_fields_are_refused(over, why):
    with pytest.raises(CustodyError, match=why):
        add(wallet(**over))


def test_the_same_signer_cannot_be_listed_twice_whatever_the_case_or_spacing():
    twice = [dict(s) for s in SIGNERS] + [{"name": "  insp.   RAO ", "role": "", "unit": ""}]
    with pytest.raises(CustodyError, match="listed twice"):
        add(wallet(signers=twice))


@pytest.mark.parametrize("field", ["scheme", "set_up_by", "notes"])
@pytest.mark.parametrize("secret", [SEED, "0x" + "4c" * 32, "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ"])
def test_a_private_key_or_seed_phrase_is_refused_in_any_text_field(field, secret):
    with pytest.raises(CustodyError, match="private key or seed phrase"):
        add(wallet(**{field: secret}))


def test_a_seed_phrase_is_refused_as_a_signer_and_a_key_as_the_address():
    with pytest.raises(CustodyError, match="private key or seed phrase"):
        add(wallet(signers=[dict(SIGNERS[0]), {"name": "SI Iyer", "role": " ".join(SEED.split()[:6]),
                                                    "unit": " ".join(SEED.split()[6:])}]))
    with pytest.raises(CustodyError, match="private key or seed phrase"):
        add(wallet(signers=[dict(SIGNERS[0]), {"name": SEED[:119]}]))
    with pytest.raises(CustodyError, match="private key or seed phrase"):
        add(wallet(chain="ethereum", address="4c" * 32))


def test_ordinary_notes_are_kept_and_not_mistaken_for_a_secret():
    note = "Set up on two hardware wallets in the strong room; tested with 1 USDT first, as the procedure says."
    assert add(wallet(notes=note))["notes"] == note


def test_a_wallet_needs_a_stored_case_and_is_recorded_once_per_case():
    with pytest.raises(CustodyError, match="No case"):
        add(case_id="case-9")
    add()
    with pytest.raises(DuplicateWallet):
        add()
    assert add(case_id="case-2")["case_id"] == "case-2"  # one unit wallet may serve several cases


# -- linking asset-register rows --------------------------------------------------------------
def test_asset_rows_held_in_custody_in_the_same_case_can_be_linked():
    held = seized()
    assert add(wallet(asset_ids=[held, held]))["asset_ids"] == [held]


def test_a_link_to_another_case_another_holder_or_a_strangers_row_is_refused():
    with pytest.raises(CustodyError, match="not in this case"):
        add(wallet(asset_ids=[seized(case_id="case-2")]))
    with pytest.raises(CustodyError, match="held in the custody wallet"):
        add(wallet(asset_ids=[seized(holder="exchange")]))
    with pytest.raises(CustodyError, match="not in this case"):
        add(wallet(asset_ids=[seized(who=viewer(BOB))]))


# -- changes ------------------------------------------------------------------------------------
def test_notes_and_links_change_and_are_kept_in_the_history():
    row = add()
    held = seized()
    out = custody.update(row["wallet_id"], {"notes": "Tested with 1 USDT.", "asset_ids": [held]}, viewer())
    assert (out["notes"], out["asset_ids"], out["changed"]) == ("Tested with 1 USDT.", [held], ["asset_ids", "notes"])
    assert [h["action"] for h in out["history"]] == ["recorded", "changed"]
    again = custody.update(row["wallet_id"], {"notes": "Tested with 1 USDT."}, viewer())
    assert again["changed"] == [] and len(again["history"]) == 2


def test_the_chain_address_threshold_and_signers_never_change():
    row = add()
    for field in ("address", "threshold", "signers", "chain", "scheme"):
        with pytest.raises(CustodyError, match="cannot be changed"):
            custody.update(row["wallet_id"], {field: "x"}, viewer())


def test_a_secret_is_refused_in_a_change_too():
    row = add()
    with pytest.raises(CustodyError, match="private key or seed phrase"):
        custody.update(row["wallet_id"], {"notes": SEED}, viewer())


def test_wallets_belong_to_their_browser_and_their_unit():
    row = add(who=viewer(unit=7, officer=1))
    assert custody.list_for(viewer(BOB), "case-1") == []
    assert custody.update(row["wallet_id"], {"notes": "x"}, viewer(BOB)) is None
    assert [w["wallet_id"] for w in custody.list_for(viewer(BOB, unit=7, officer=2), "case-1")] == [row["wallet_id"]]


def test_a_write_that_keeps_clashing_is_a_conflict_not_a_crash(monkeypatch):
    row = add()

    def clash(*args):
        raise StaleDataError("always")

    monkeypatch.setattr(custody, "_update_once", clash)
    with pytest.raises(custody.CustodyConflict):
        custody.update(row["wallet_id"], {"notes": "x"}, viewer())


# -- routes ---------------------------------------------------------------------------------------
H = {ownership.OWNER_HEADER: ALICE}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def switched_on(monkeypatch):
    monkeypatch.setattr(config, "CUSTODY_WALLETS", True)


def test_switched_off_the_list_says_so_and_every_write_is_refused(client, monkeypatch):
    monkeypatch.setattr(config, "CUSTODY_WALLETS", False)
    listed = client.get("/trace/case-1/custody", headers=H)
    assert listed.status_code == 200 and listed.json()["enabled"] is False
    assert client.post("/trace/case-1/custody", json=wallet(), headers=H).status_code == 403
    assert client.patch("/custody/whatever", json={"notes": "x"}, headers=H).status_code == 403
    with models.session() as s:
        assert s.scalars(select(models.CustodyWallet)).all() == []


def test_the_routes_add_list_and_change(client, switched_on):
    made = client.post("/trace/case-1/custody", json=wallet(), headers=H)
    assert made.status_code == 201
    wid = made.json()["wallet_id"]
    listed = client.get("/trace/case-1/custody", headers=H).json()
    assert (listed["enabled"], listed["count"], listed["chains"]["tron"]) == (True, 1, config.CHAINS["tron"].name)
    changed = client.patch(f"/custody/{wid}", json={"notes": "Tested with 1 USDT."}, headers=H)
    assert changed.status_code == 200 and changed.json()["notes"] == "Tested with 1 USDT."


def test_the_routes_refuse_secrets_bad_thresholds_duplicates_and_strangers(client, switched_on):
    assert client.post("/trace/case-1/custody", json=wallet(notes=SEED), headers=H).status_code == 400
    assert client.post("/trace/case-1/custody", json=wallet(threshold=5), headers=H).status_code == 400
    assert client.post("/trace/case-1/custody", json=wallet()).status_code == 400  # no owner key
    wid = client.post("/trace/case-1/custody", json=wallet(), headers=H).json()["wallet_id"]
    assert client.post("/trace/case-1/custody", json=wallet(), headers=H).status_code == 409
    assert client.patch(f"/custody/{wid}", json={"notes": "x"}, headers={ownership.OWNER_HEADER: BOB}).status_code == 404


def test_the_audit_log_records_what_happened_never_the_names_or_notes(client, switched_on):
    wid = client.post("/trace/case-1/custody", json=wallet(), headers=H).json()["wallet_id"]
    client.patch(f"/custody/{wid}", json={"notes": "Insp. Rao keeps device 1"}, headers=H)
    with models.session() as s:
        rows = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action.like("custody.%"))).all()
    assert [(r.action, json.loads(r.detail) if r.detail else None) for r in rows if r.action != "custody.list"] == [
        ("custody.add", {"wallet_id": wid, "chain": "tron", "threshold": 2, "signers": 3}),
        ("custody.update", {"wallet_id": wid, "changed": ["notes"]}),
    ]
    assert not any("Rao" in (r.detail or "") for r in rows)


def test_g7_custody_1_goes_down_and_up_again_keeping_the_cases():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    add()
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with models._engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.downgrade(settings, "g7_domain_lookups_1")
    assert "custody_wallets" not in set(inspect(models._engine).get_table_names())
    assert models.get_case("case-1") is not None
    models.init_db()
    assert "custody_wallets" in set(inspect(models._engine).get_table_names())
