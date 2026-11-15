"""Two more task suggestions (app/tasks.py, #334), behind EXCHEQUER_MORE_TASK_SUGGESTIONS.

An exhibit handed over (a change of holder in the exhibit register) with no
hash check recorded since, and alerts on the case's watches not yet marked
read. Each rule fires on the record it describes and stays silent once the
record says it was done. Throwaway SQLite, no network.
"""
from __future__ import annotations

import json
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import config, exhibits, models, ownership, tasks, watchlist
from app.auth import User
from app.main import app

ALICE, BOB = "a" * 32, "b" * 32
SHA = "c" * 64
TRON = "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU"


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 't.db'}", future=True))
    monkeypatch.setattr(tasks, "_today", lambda: date(2026, 11, 14))
    monkeypatch.setattr(config, "MORE_TASK_SUGGESTIONS", True)
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    models.save_case("case-2", "0xseed2", {"address": "0xseed2"})


def viewer(key=ALICE, unit=None, officer=None):
    return User(id=f"officer-{officer}" if officer else "demo", role="officer", unit="Cyber Cell" if unit else None,
                owner_hash=ownership.owner_hash(key), demo=officer is None, officer_id=officer, unit_id=unit)


def exhibit(who=None, **over):
    who = who or viewer()
    fields = {"kind": "phone_extraction", "label": "Victim's phone", "tool": "UFED 7.6", "sha256": SHA,
              "made_on": "2026-11-01", "holder": "SI Iyer", **over}
    return exhibits.create(who.owner_hash, "case-1", fields, who)


def hand_over(x, to="Insp. Rao", who=None):
    return exhibits.update(x["exhibit_id"], {"holder": to, "note": "Taken to the lab"}, who or viewer())


def watch(case_id="case-1", key=ALICE, active=True):
    wid = str(uuid.uuid4())
    w = models.Watch(id=wid, owner_hash=ownership.owner_hash(key), chain="tron", asset="USDT",
                     address=TRON, case_id=case_id, created_at="2026-11-01T00:00:00+00:00", active=active)
    with models.session() as s:
        s.add(w)
        s.commit()
    return wid


def alert(watch_id, kind="exchange", value=500.0, read=False, at="2026-11-10T09:00:00+00:00", key=ALICE):
    aid = str(uuid.uuid4())
    a = models.Alert(id=aid, watch_id=watch_id, owner_hash=ownership.owner_hash(key), created_at=at,
                     kind=kind, message="m", tx_hash="ab" * 32, tx_time=0, value=value, asset="USDT",
                     counterparty="T" + "1" * 33, read=read)
    with models.session() as s:
        s.add(a)
        s.commit()
    return aid


def rules(found):
    return sorted(x["source"].rsplit(":", 1)[-1] for x in found)


# -- an exhibit handed over with no check since -------------------------------------------
def test_an_exhibit_handed_over_with_no_check_since_is_suggested():
    x = exhibit()
    assert tasks.suggestions(viewer(), "case-1") == []  # recorded, never handed over: nothing to ask
    hand_over(x)
    [s] = tasks.suggestions(viewer(), "case-1")
    assert s["source"] == f"exhibit:{x['exhibit_id']}:1:check" and s["due_on"] == ""
    assert s["title"] == "Check the file of exhibit Victim's phone against its recorded hash"
    assert s["why"].startswith("Handed over to Insp. Rao on ")
    assert "does not show who had it" in s["why"]


def test_a_check_after_the_hand_over_ends_it_and_a_later_hand_over_asks_again():
    x = hand_over(exhibit())
    exhibits.check(x["exhibit_id"], "d" * 64, viewer())  # a mismatch is still a check: the register shows it
    assert tasks.suggestions(viewer(), "case-1") == []
    exhibits.update(x["exhibit_id"], {"stored_at": "Locker 4", "note": "Moved"}, viewer())  # a move is not a hand-over
    assert tasks.suggestions(viewer(), "case-1") == []
    hand_over(x, to="SI Pal")
    [s] = tasks.suggestions(viewer(), "case-1")
    assert s["source"] == f"exhibit:{x['exhibit_id']}:4:check" and "SI Pal" in s["why"]


def test_a_check_before_the_hand_over_does_not_count():
    x = exhibit()
    exhibits.check(x["exhibit_id"], SHA, viewer())
    hand_over(x)
    assert rules(tasks.suggestions(viewer(), "case-1")) == ["check"]


def test_an_ended_exhibit_or_one_with_no_sha256_suggests_nothing():
    ended = hand_over(exhibit())
    exhibits.update(ended["exhibit_id"], {"status": "released", "note": "Returned to the owner"}, viewer())
    hand_over(exhibit(sha256="", md5="e" * 32))  # the register checks a file by its SHA-256 only
    assert tasks.suggestions(viewer(), "case-1") == []


def test_another_browsers_exhibit_is_not_suggested():
    hand_over(exhibit())
    assert tasks.suggestions(viewer(BOB), "case-1") == []


# -- watch alerts not yet marked read ------------------------------------------------------
def test_unread_alerts_on_the_cases_watch_are_one_suggestion_keyed_by_the_newest():
    w = watch()
    alert(w, kind="moved", at="2026-11-09T09:00:00+00:00")
    newest = alert(w, kind="exchange", at="2026-11-10T09:00:00+00:00")
    [s] = tasks.suggestions(viewer(), "case-1")
    assert s["source"] == f"alert:{newest}:unread" and s["due_on"] == ""
    assert s["title"] == f"Look at the 2 unread watch alerts on {TRON}"
    assert s["why"] == ("The newest came on 10 Nov 2026 (funds sent to an exchange wallet); "
                        "none has been marked read on the Watchlist.")


def test_alerts_marked_read_dust_or_on_other_watches_suggest_nothing():
    alert(watch(), read=True)
    alert(watch(), value=0.01)  # below the dust floor, as the watchlist sorts it last
    alert(watch(case_id="case-2"))
    alert(watch(case_id=None))
    alert(watch(active=False))
    assert tasks.suggestions(viewer(), "case-1") == []


def test_marking_read_on_the_watchlist_ends_it_and_a_new_alert_asks_again():
    w = watch()
    alert(w)
    assert rules(tasks.suggestions(viewer(), "case-1")) == ["unread"]
    watchlist.mark_read(ownership.owner_hash(ALICE))
    assert tasks.suggestions(viewer(), "case-1") == []
    newer = alert(w, kind="more", value=0.0, at="2026-11-12T09:00:00+00:00")  # a notice counts, whatever its value
    [s] = tasks.suggestions(viewer(), "case-1")
    assert s["source"] == f"alert:{newer}:unread" and "it has not been marked read" in s["why"]


def test_watch_alerts_are_the_browsers_own_even_within_a_unit():
    alert(watch())
    assert tasks.suggestions(viewer(BOB, unit=7, officer=2), "case-1") == []


# -- both rules ----------------------------------------------------------------------------
def test_with_the_flag_off_neither_rule_suggests_anything(monkeypatch):
    hand_over(exhibit())
    alert(watch())
    monkeypatch.setattr(config, "MORE_TASK_SUGGESTIONS", False)
    assert tasks.suggestions(viewer(), "case-1") == []


def test_taking_up_or_declining_either_keeps_it_away():
    x = hand_over(exhibit())
    alert(watch())
    found = {s["source"].rsplit(":", 1)[-1]: s for s in tasks.suggestions(viewer(), "case-1")}
    who = viewer()
    t = tasks.create(who.owner_hash, "case-1", {"source": found["check"]["source"], "title": "anything"}, who)
    assert t["title"] == "Check the file of exhibit Victim's phone against its recorded hash"
    d = tasks.create(who.owner_hash, "case-1", {"source": found["unread"]["source"], "note": "Seen on the phone"}, who)
    assert d["status"] == "dropped"
    assert tasks.suggestions(viewer(), "case-1") == []
    assert x["exhibit_id"] in t["source"]


def test_the_route_lists_them_and_audits_which_rule_never_the_text():
    hand_over(exhibit())
    client, h = TestClient(app), {ownership.OWNER_HEADER: ALICE}
    [s] = client.get("/trace/case-1/tasks", headers=h).json()["suggested"]
    made = client.post("/trace/case-1/tasks", json={"source": s["source"]}, headers=h)
    assert made.status_code == 201
    with models.session() as db:
        row = db.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "task.add")).one()
    assert json.loads(row.detail) == {"task_id": made.json()["task_id"], "suggestion": "check"}
