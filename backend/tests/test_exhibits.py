"""The exhibit register (app/exhibits.py, routes/exhibits.py): suite feature 3.

Outside forensic tools produce files a case relies on: a phone extraction, a
disk image, a memory capture, the tool's own report. The register records each:
what it is, the tool that made it, its hashes, who made it and when, where it is
kept and who holds it now. The file itself is never uploaded: the officer records
the hash the tool printed, and can later check a file against the record by
hashing it in the browser and sending only the hash.

Nothing is deleted. Hand-overs and checks are history: a chain of custody that
reads the same in court as it did the day it was written. Throwaway SQLite.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import exhibits, models, ownership
from app.auth import User
from app.exhibits import ExhibitError
from app.main import app

ALICE, BOB = "a" * 32, "b" * 32
SHA256 = "9f" * 32
SHA1 = "1a" * 20
MD5 = "5d" * 16
TODAY = date(2026, 11, 13)
SEED = "abandon ability able about above absent absorb abstract absurd abuse access accident"


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'e.db'}", future=True))
    monkeypatch.setattr(exhibits, "_today", lambda: TODAY)
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})


def viewer(key=ALICE, unit=None, officer=None):
    return User(id=f"officer-{officer}" if officer else "demo", role="officer", unit="Cyber Cell" if unit else None,
                owner_hash=ownership.owner_hash(key), demo=officer is None, officer_id=officer, unit_id=unit)


def image(**over):
    fields = {"kind": "phone_extraction", "label": "Accused's phone, Samsung A54", "tool": "Cellebrite UFED 7.69",
              "file_name": "A54_full.ufdr", "size_bytes": 64_000_000_000, "sha256": SHA256, "made_by": "SI Iyer",
              "made_on": "2026-11-12", "stored_at": "Evidence room, shelf 3", "holder": "SI Iyer"}
    fields.update(over)
    return fields


def add(fields=None, who=None):
    who = who or viewer()
    return exhibits.create(who.owner_hash, "case-1", fields or image(), who)


# -- recording an exhibit ---------------------------------------------------------------------
def test_an_exhibit_records_the_file_its_tool_its_hashes_and_who_holds_it():
    row = add()
    assert (row["kind"], row["tool"], row["sha256"], row["size_bytes"]) == ("phone_extraction", "Cellebrite UFED 7.69", SHA256, 64_000_000_000)
    assert (row["holder"], row["stored_at"], row["status"]) == ("SI Iyer", "Evidence room, shelf 3", "held")
    assert [h["action"] for h in row["history"]] == ["recorded"]


def test_hashes_are_kept_lower_case_and_any_one_of_the_three_will_do():
    assert add(image(sha256=SHA256.upper()))["sha256"] == SHA256
    row = add(image(sha256="", sha1=SHA1, md5=MD5, kind="disk_image", label="Laptop SSD image", tool="FTK Imager 4.7"))
    assert (row["sha256"], row["sha1"], row["md5"]) == ("", SHA1, MD5)


@pytest.mark.parametrize("over, why", [
    ({"kind": "photocopy"}, "kind"),
    ({"label": ""}, "what the file is"),
    ({"tool": ""}, "tool"),
    ({"sha256": "", "sha1": "", "md5": ""}, "hash"),
    ({"sha256": "abc"}, "SHA-256"),
    ({"sha1": "zz" * 20}, "SHA-1"),
    ({"md5": "12"}, "MD5"),
    ({"made_on": "2027-01-01"}, "future"),
    ({"made_on": "last week"}, "date"),
    ({"size_bytes": -1}, "size"),
])
def test_missing_or_malformed_fields_are_refused(over, why):
    with pytest.raises(ExhibitError, match=why):
        add(image(**over))


@pytest.mark.parametrize("field", ["label", "notes", "stored_at", "holder"])
def test_a_seed_phrase_is_refused_in_any_text_field(field):
    with pytest.raises(ExhibitError, match="private key or seed phrase"):
        add(image(**{field: SEED}))


def test_the_same_file_cannot_be_recorded_twice_in_a_case():
    first = add()
    with pytest.raises(ExhibitError, match=first["exhibit_id"][:8]):
        add(image(label="the same image again"))


def test_an_exhibit_needs_a_stored_case():
    who = viewer()
    with pytest.raises(ExhibitError, match="case"):
        exhibits.create(who.owner_hash, "nope", image(), who)


# -- chain of custody -----------------------------------------------------------------------------
def test_a_hand_over_names_who_now_holds_it_and_why():
    row = add()
    after = exhibits.update(row["exhibit_id"], {"holder": "Insp. Rao", "note": "for the s.63 certificate"}, viewer())
    assert after["holder"] == "Insp. Rao"
    last = after["history"][-1]
    assert (last["action"], last["changed"], last["note"]) == ("changed", ["holder"], "for the s.63 certificate")


def test_a_hand_over_needs_a_reason():
    row = add()
    with pytest.raises(ExhibitError, match="why"):
        exhibits.update(row["exhibit_id"], {"holder": "Insp. Rao"}, viewer())


def test_an_exhibit_ends_released_or_destroyed_only_with_a_reason_and_then_takes_only_notes():
    row = add()
    with pytest.raises(ExhibitError, match="why"):
        exhibits.update(row["exhibit_id"], {"status": "destroyed"}, viewer())
    done = exhibits.update(row["exhibit_id"], {"status": "released", "note": "returned to the owner on the court's order"}, viewer())
    assert done["status"] == "released"
    with pytest.raises(ExhibitError, match="already"):
        exhibits.update(row["exhibit_id"], {"holder": "x", "note": "y"}, viewer())
    assert exhibits.update(row["exhibit_id"], {"notes": "kept for the record"}, viewer())["notes"] == "kept for the record"


def test_the_hashes_and_the_file_never_change_and_nothing_is_deleted():
    row = add()
    with pytest.raises(ExhibitError):
        exhibits.update(row["exhibit_id"], {"sha256": "00" * 32}, viewer())
    assert not hasattr(exhibits, "delete")


# -- checking a file against the record -------------------------------------------------------------
def test_a_check_compares_a_files_hash_with_the_record_and_keeps_the_result():
    row = add()
    match = exhibits.check(row["exhibit_id"], SHA256.upper(), viewer())
    assert match["result"] == "match"
    differ = exhibits.check(row["exhibit_id"], "00" * 32, viewer())
    assert differ["result"] == "mismatch"
    history = differ["exhibit"]["history"]
    assert [(h["action"], h.get("result")) for h in history] == [("recorded", None), ("checked", "match"), ("checked", "mismatch")]


def test_a_check_needs_a_recorded_sha256_and_a_well_formed_one():
    row = add(image(sha256="", md5=MD5))
    with pytest.raises(ExhibitError, match="no SHA-256"):
        exhibits.check(row["exhibit_id"], SHA256, viewer())
    with pytest.raises(ExhibitError, match="SHA-256"):
        exhibits.check(add()["exhibit_id"], "abc", viewer())


# -- who sees what ------------------------------------------------------------------------------------
def test_exhibits_belong_to_their_browser_and_their_unit():
    mine = add(who=viewer(ALICE, unit=7, officer=1))
    assert [r["exhibit_id"] for r in exhibits.list_for(viewer(BOB, unit=7, officer=2), "case-1")] == [mine["exhibit_id"]]
    assert exhibits.list_for(viewer(BOB), "case-1") == []
    assert exhibits.update(mine["exhibit_id"], {"notes": "x"}, viewer(BOB)) is None
    assert exhibits.check(mine["exhibit_id"], SHA256, viewer(BOB)) is None


# -- routes ---------------------------------------------------------------------------------------------
H = {ownership.OWNER_HEADER: ALICE}


@pytest.fixture
def client():
    return TestClient(app)


def test_the_routes_add_list_hand_over_and_check(client):
    made = client.post("/trace/case-1/exhibits", json=image(), headers=H)
    assert made.status_code == 201
    eid = made.json()["exhibit_id"]
    assert client.get("/trace/case-1/exhibits", headers=H).json()["count"] == 1
    moved = client.patch(f"/exhibits/{eid}", json={"holder": "Insp. Rao", "note": "court"}, headers=H)
    assert moved.status_code == 200 and moved.json()["holder"] == "Insp. Rao"
    checked = client.post(f"/exhibits/{eid}/check", json={"sha256": SHA256}, headers=H)
    assert checked.status_code == 200 and checked.json()["result"] == "match"


def test_the_routes_refuse_bad_input_duplicates_and_strangers(client):
    assert client.post("/trace/case-1/exhibits", json=image(notes=SEED), headers=H).status_code == 400
    assert client.post("/trace/case-1/exhibits", json=image()).status_code == 400  # no owner key
    eid = client.post("/trace/case-1/exhibits", json=image(), headers=H).json()["exhibit_id"]
    assert client.post("/trace/case-1/exhibits", json=image(), headers=H).status_code == 409
    other = {ownership.OWNER_HEADER: BOB}
    assert client.patch(f"/exhibits/{eid}", json={"notes": "x"}, headers=other).status_code == 404
    assert client.post(f"/exhibits/{eid}/check", json={"sha256": SHA256}, headers=other).status_code == 404


def test_the_audit_log_records_what_happened_never_the_text_or_the_hash(client):
    eid = client.post("/trace/case-1/exhibits", json=image(), headers=H).json()["exhibit_id"]
    client.patch(f"/exhibits/{eid}", json={"holder": "Insp. Rao", "note": "court"}, headers=H)
    client.post(f"/exhibits/{eid}/check", json={"sha256": "00" * 32}, headers=H)
    with models.session() as s:
        rows = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action.like("exhibit.%"))).all()
    assert [(r.action, json.loads(r.detail)) for r in rows] == [
        ("exhibit.add", {"exhibit_id": eid, "kind": "phone_extraction"}),
        ("exhibit.update", {"exhibit_id": eid, "changed": ["holder"]}),
        ("exhibit.check", {"exhibit_id": eid, "result": "mismatch"}),
    ]


def test_g7_exhibits_1_goes_down_and_up_again_keeping_the_cases():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from app import config
    add()
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with models._engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.downgrade(settings, "g7_assets_1")
    assert "exhibits" not in set(inspect(models._engine).get_table_names())
    assert models.get_case("case-1") is not None
    models.init_db()
    assert "exhibits" in set(inspect(models._engine).get_table_names())
