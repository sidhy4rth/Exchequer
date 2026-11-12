"""The asset register (app/assets.py, routes/assets.py): suite feature 9.

Every amount frozen or seized in a case gets a row: what it is, where it is held,
the transaction that moved it there, who holds the keys (names only), when it
was seized, and the 45-day deadline for the court's order on its custody
(BNSS s.497, as the Karnataka High Court read it in Mukesh Jain). A row ends in
an outcome -- released to the victim, returned, confiscated, sold -- with the
transaction or order that did it. Nothing is deleted; every change is history.

The register must never hold a key: a private key, seed phrase or extended key
typed into any field is refused, so a careless paste cannot put the money in
the database's hands. Throwaway SQLite, no network.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import assets, models, ownership
from app.assets import AssetError
from app.auth import User
from app.main import app

ALICE, BOB = "a" * 32, "b" * 32
TX = "ab" * 32
CUSTODY = "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU"
TODAY = date(2026, 11, 12)
SEED = "abandon ability able about above absent absorb abstract absurd abuse access accident"


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'a.db'}", future=True))
    monkeypatch.setattr(assets, "_today", lambda: TODAY)
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    models.save_case("case-2", "0xseed2", {"address": "0xseed2"})


def viewer(key=ALICE, unit=None, officer=None):
    return User(id=f"officer-{officer}" if officer else "demo", role="officer", unit="Cyber Cell" if unit else None,
                owner_hash=ownership.owner_hash(key), demo=officer is None, officer_id=officer, unit_id=unit)


def held(**over):
    fields = {"holder": "custody", "asset": "USDT", "amount": "635.000000", "chain": "tron", "held_at": CUSTODY,
              "tx_hash": TX, "key_holders": "2 of 3: Insp. Rao, SI Iyer, SI Pal", "seized_on": "2026-11-01"}
    fields.update(over)
    return fields


def add(fields=None, case_id="case-1", who=None):
    who = who or viewer()
    return assets.create(who.owner_hash, case_id, fields or held(), who)


# -- adding a row -------------------------------------------------------------------------
def test_a_row_records_what_is_held_where_and_by_whom():
    row = add()
    assert (row["holder"], row["asset"], row["amount"], row["held_at"], row["tx_hash"]) == ("custody", "USDT", "635.000000", CUSTODY, TX)
    assert row["key_holders"] == "2 of 3: Insp. Rao, SI Iyer, SI Pal"
    assert row["status"] == "held" and [h["status"] for h in row["history"]] == ["held"]


def test_amounts_are_kept_exactly_as_decimals():
    assert add(held(amount="0.1"))["amount"] == "0.1"
    assert add(held(holder="bank", asset="INR", amount="2,50,000", tx_hash="", held_at="State Bank of India"))["amount"] == "250000"
    assert add(held(amount="1234567.123456789012345678"))["amount"] == "1234567.123456789012345678"


@pytest.mark.parametrize("over, why", [
    ({"holder": "pocket"}, "where"),
    ({"amount": "0"}, "more than zero"),
    ({"amount": "-5"}, "more than zero"),
    ({"amount": "about 600"}, "number"),
    ({"amount": "nan"}, "number"),
    ({"asset": ""}, "asset"),
    ({"tx_hash": ""}, "transaction"),  # money moved into custody always has a transaction
    ({"tx_hash": "not-a-hash"}, "transaction"),
    ({"seized_on": "yesterday"}, "date"),
    ({"seized_on": "2026-12-25"}, "future"),
])
def test_missing_or_malformed_fields_are_refused(over, why):
    with pytest.raises(AssetError, match=why):
        add(held(**over))


def test_a_hold_at_a_bank_or_exchange_needs_no_transaction():
    assert add(held(holder="exchange", held_at="Binance", tx_hash=""))["tx_hash"] == ""


def test_a_row_needs_a_stored_case():
    with pytest.raises(AssetError, match="case"):
        add(case_id="nope")


# -- never a key ----------------------------------------------------------------------------
@pytest.mark.parametrize("field, secret", [
    ("key_holders", SEED),
    ("notes", f"seed: {SEED}"),
    ("held_at", "0x" + "1f" * 32),  # a raw private key
    ("notes", "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ"),  # a WIF key (the textbook example)
    ("notes", "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi"),
])
def test_a_private_key_or_seed_phrase_is_refused_in_any_field(field, secret):
    with pytest.raises(AssetError, match="private key or seed phrase"):
        add(held(**{field: secret}))
    with models.session() as s:
        assert s.scalar(select(models.SeizedAsset.id)) is None


def test_ordinary_notes_are_not_mistaken_for_a_seed_phrase():
    note = ("Moved on the evening of the search after the second officer arrived and checked the device "
            "against the seizure memo and the video recording")
    assert add(held(notes=note))["notes"] == note


def test_a_transaction_hash_belongs_in_its_own_field_not_the_notes():
    with pytest.raises(AssetError, match="private key or seed phrase"):
        add(held(notes=f"moved in tx {TX}"))


# -- the court's deadline ---------------------------------------------------------------------
def test_the_custody_order_is_due_45_days_after_the_seizure():
    row = add(held(seized_on="2026-11-01"))
    assert row["deadline"] == "2026-12-16" and row["days_left"] == 34 and row["due"] is True


def test_an_overdue_row_counts_negative_days():
    assert add(held(seized_on="2026-09-01"))["days_left"] == (date(2026, 10, 16) - TODAY).days


def test_recording_the_courts_order_ends_the_countdown():
    row = add()
    who = viewer()
    after = assets.update(row["asset_id"], {"order_ref": "Order 21/2026, JMFC Court, 20 Nov 2026"}, who)
    assert after["due"] is False and after["order_ref"].startswith("Order 21/2026")


# -- outcomes and history -------------------------------------------------------------------
def test_a_row_ends_in_an_outcome_with_its_transaction_or_order():
    row = add()
    who = viewer()
    with pytest.raises(AssetError, match="transaction or the order"):
        assets.update(row["asset_id"], {"status": "released_to_victim"}, who)
    done = assets.update(row["asset_id"], {"status": "released_to_victim", "outcome_tx": "cd" * 32}, who)
    assert done["status"] == "released_to_victim" and done["due"] is False
    assert [h["status"] for h in done["history"]] == ["held", "released_to_victim"]
    with pytest.raises(AssetError, match="already"):
        assets.update(row["asset_id"], {"status": "sold", "outcome_ref": "auction"}, who)


def test_every_change_is_kept_in_the_history_and_nothing_is_deleted():
    row = add()
    who = viewer()
    assets.update(row["asset_id"], {"key_holders": "2 of 3: Insp. Rao, SI Iyer, SI Sen (Pal transferred)"}, who)
    after = assets.update(row["asset_id"], {"notes": "keys re-split on transfer"}, who)
    assert [h.get("changed") for h in after["history"]] == [None, ["key_holders"], ["notes"]]
    assert not hasattr(assets, "delete")


def test_an_unknown_status_or_field_is_refused():
    row = add()
    with pytest.raises(AssetError):
        assets.update(row["asset_id"], {"status": "lost"}, viewer())
    with pytest.raises(AssetError):
        assets.update(row["asset_id"], {"amount": "1"}, viewer())  # the amount seized never changes


# -- who sees what --------------------------------------------------------------------------
def test_rows_belong_to_their_browser_and_their_unit():
    add()
    assert len(assets.list_for(viewer(), "case-1")) == 1
    assert assets.list_for(viewer(BOB), "case-1") == []
    mine = add(held(), who=viewer(ALICE, unit=7, officer=1))
    colleague = viewer(BOB, unit=7, officer=2)
    assert [r["asset_id"] for r in assets.list_for(colleague, "case-1")] == [mine["asset_id"]]
    assert assets.update(mine["asset_id"], {"notes": "seen by a colleague"}, colleague)["notes"] == "seen by a colleague"
    assert assets.update(mine["asset_id"], {"notes": "x"}, viewer(BOB)) is None


def test_due_lists_only_held_rows_without_an_order_within_the_window_soonest_first():
    soon = add(held(seized_on="2026-09-30"))   # deadline 14 Nov: 2 days left
    add(held(seized_on="2026-11-10"))          # 43 days left: not due this week
    late = add(held(seized_on="2026-09-01"), case_id="case-2")  # overdue
    ordered = add(held(seized_on="2026-09-30"))
    assets.update(ordered["asset_id"], {"order_ref": "Order 3/2026"}, viewer())
    due = assets.due_for(viewer(), within_days=7)
    assert [r["asset_id"] for r in due] == [late["asset_id"], soon["asset_id"]]


# -- the routes -----------------------------------------------------------------------------
H = {ownership.OWNER_HEADER: ALICE}


@pytest.fixture
def client():
    return TestClient(app)


def test_the_routes_add_list_change_and_show_whats_due(client):
    made = client.post("/trace/case-1/assets", json=held(seized_on="2026-09-30"), headers=H)
    assert made.status_code == 201
    rid = made.json()["asset_id"]
    listed = client.get("/trace/case-1/assets", headers=H).json()
    assert listed["count"] == 1 and listed["deadline_days"] == 45
    assert client.get("/assets/due", headers=H).json()["assets"][0]["asset_id"] == rid
    changed = client.patch(f"/assets/{rid}", json={"order_ref": "Order 9/2026"}, headers=H)
    assert changed.status_code == 200 and changed.json()["due"] is False
    assert client.get("/assets/due", headers=H).json()["count"] == 0


def test_the_routes_refuse_bad_input_and_strangers(client):
    assert client.post("/trace/case-1/assets", json=held(key_holders=SEED), headers=H).status_code == 400
    assert client.post("/trace/case-1/assets", json=held()).status_code == 400  # no owner key
    rid = client.post("/trace/case-1/assets", json=held(), headers=H).json()["asset_id"]
    assert client.patch(f"/assets/{rid}", json={"notes": "x"}, headers={ownership.OWNER_HEADER: BOB}).status_code == 404


def test_the_audit_log_records_what_changed_never_the_text(client):
    rid = client.post("/trace/case-1/assets", json=held(), headers=H).json()["asset_id"]
    client.patch(f"/assets/{rid}", json={"key_holders": "2 of 3: Insp. Rao, SI Iyer, SI Sen"}, headers=H)
    with models.session() as s:
        rows = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action.like("asset.%"))).all()
    details = [(r.action, json.loads(r.detail)) for r in rows]
    assert details == [("asset.add", {"asset_id": rid, "holder": "custody"}),
                       ("asset.update", {"asset_id": rid, "changed": ["key_holders"]})]


def test_days_are_counted_in_india():
    assert assets.IST.utcoffset(None) == timedelta(hours=5, minutes=30)


def test_g7_assets_1_goes_down_and_up_again_keeping_the_cases():
    """seized_assets is a table of its own: rolling it back leaves every case."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from app import config
    add()
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with models._engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.downgrade(settings, "g6_queue_2")
    assert "seized_assets" not in set(inspect(models._engine).get_table_names())
    assert models.get_case("case-1") is not None
    models.init_db()
    assert "seized_assets" in set(inspect(models._engine).get_table_names())
    assert assets.list_for(viewer(), "case-1") == []
