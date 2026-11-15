"""SOP reminders on asset-register rows (sop_reminders.py, behind EXCHEQUER_SOP_DEADLINES).

They appear on a bank hold with the flag on, never with it off, never on other
holders, and never change the register's 45-day court deadline.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import assets, config, models, ownership, sop_reminders
from app.auth import User
from app.main import app

ALICE = "a" * 32
H = {ownership.OWNER_HEADER: ALICE}
TODAY = date(2026, 11, 12)


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'a.db'}", future=True))
    monkeypatch.setattr(assets, "_today", lambda: TODAY)
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})


def viewer():
    return User(id="demo", role="officer", unit=None, owner_hash=ownership.owner_hash(ALICE), demo=True,
                officer_id=None, unit_id=None)


def bank(**over):
    fields = {"holder": "bank", "asset": "INR", "amount": "250000.50", "held_at": "Example Bank, Andheri branch",
              "seized_on": "2026-11-01"}
    fields.update(over)
    return fields


def add(fields):
    return assets.create(viewer().owner_hash, "case-1", fields, viewer())


def test_a_bank_hold_gets_the_sop_reminders_with_the_flag_on(monkeypatch):
    monkeypatch.setattr(config, "SOP_DEADLINES", True)
    row = add(bank())
    got = row["sop_reminders"]
    assert [r["id"] for r in got] == [r["id"] for r in sop_reminders.BANK_HOLD]
    ninety = got[0]
    assert ninety["section"] == "Annexure I, para 3"
    assert "90 calendar days from the date of amount put on hold" in ninety["quote"]
    assert ninety["date"] == "2027-01-30"  # 1 Nov 2026 + 90 days
    assert ninety["date_label"] == "Day 90 from the date seized recorded here"
    for r in got:
        assert r["hint"].startswith(f"Reminder, per MHA SOP for NCRP-CFCFRMS {r['section']} (copy dated 11 Feb 2026): ")
        assert r["quote"] in r["hint"]
        assert r["source_url"] == "https://www.zoroastrianbank.bank.in/download/SOP-NCRP.pdf"
        assert r["reminder_only"] is True and "Not a deadline Exchequer enforces" in r["note"]
    # Only the 90-day hold can be dated from what the register records.
    assert [r["date"] is not None for r in got] == [True, False, False, False, False]


def test_the_45_day_court_deadline_is_unchanged_by_the_reminders(monkeypatch):
    monkeypatch.setattr(config, "SOP_DEADLINES", True)
    row = add(bank())
    assert row["deadline"] == "2026-12-16" and row["days_left"] == 34 and row["due"] is True
    assert assets.DEADLINE_DAYS == 45


def test_nothing_with_the_flag_off(monkeypatch):
    monkeypatch.setattr(config, "SOP_DEADLINES", False)
    row = add(bank())
    assert "sop_reminders" not in row
    assert "sop_reminders" not in assets.list_for(viewer(), "case-1")[0]


@pytest.mark.parametrize("holder", ["exchange", "issuer", "custody"])
def test_no_reminders_for_holds_the_sop_sets_no_time_limit_for(monkeypatch, holder):
    monkeypatch.setattr(config, "SOP_DEADLINES", True)
    extra = {"chain": "tron", "tx_hash": "ab" * 32} if holder == "custody" else {}
    row = add(bank(holder=holder, asset="USDT", amount="635", **extra))
    assert row["sop_reminders"] == []


def test_no_reminders_once_the_hold_has_ended(monkeypatch):
    monkeypatch.setattr(config, "SOP_DEADLINES", True)
    row = add(bank())
    ended = assets.update(row["asset_id"], {"status": "released_to_victim", "outcome_ref": "Order 9/2026"}, viewer())
    assert ended["sop_reminders"] == []


def test_the_list_route_carries_the_reminders_only_with_the_flag(monkeypatch):
    client = TestClient(app)
    assert client.post("/trace/case-1/assets", json=bank(), headers=H).status_code == 201
    monkeypatch.setattr(config, "SOP_DEADLINES", False)
    assert "sop_reminders" not in client.get("/trace/case-1/assets", headers=H).json()["assets"][0]
    monkeypatch.setattr(config, "SOP_DEADLINES", True)
    listed = client.get("/trace/case-1/assets", headers=H).json()
    assert listed["assets"][0]["sop_reminders"][0]["date"] == "2027-01-30"
    assert listed["deadline_days"] == 45


def test_the_flag_is_registered_and_off_by_default():
    assert config.FLAGS["EXCHEQUER_SOP_DEADLINES"]["on"] is False


def test_each_reminder_cites_the_pdf_page_its_quote_is_printed_on():
    # Checked against the rendered pages of the copy (SHA-256 65400b47…): §6.1(k)
    # is printed on page 13 and §10.1(e), (f) and the closing paragraph on page 24.
    # A plain text dump of this file puts them a page early, because its layout
    # layers overlap the next page.
    assert {r["id"]: r["page"] for r in sop_reminders.BANK_HOLD} == {
        "annex1-90-days": 34, "s10-1e-15-days": 24, "s10-1f-2-days": 24, "s10-1-extension": 24, "s6-1k-1-week": 13,
    }


def test_the_90_day_date_counts_calendar_days_through_a_leap_day():
    got = sop_reminders.for_asset("bank", "held", "2027-12-01")
    assert got[0]["date"] == "2028-02-29"  # 30 + 31 + 29 days
