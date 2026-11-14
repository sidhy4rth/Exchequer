"""A task list per case (app/tasks.py, routes/tasks.py): suite feature 6.

What still has to be done in a case, who it is assigned to (a name), by when,
and what came of it. A task is open, done or dropped; dropping one or opening
it again needs a reason. Nothing is deleted and every change is history.
Free text refuses private keys and seed phrases. Throwaway SQLite, no network.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import models, ownership, tasks
from app.auth import User
from app.main import app
from app.tasks import TaskError

ALICE, BOB = "a" * 32, "b" * 32
TODAY = date(2026, 11, 14)
SEED = "abandon ability able about above absent absorb abstract absurd abuse access accident"


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 't.db'}", future=True))
    monkeypatch.setattr(tasks, "_today", lambda: TODAY)
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    models.save_case("case-2", "0xseed2", {"address": "0xseed2"})


def viewer(key=ALICE, unit=None, officer=None):
    return User(id=f"officer-{officer}" if officer else "demo", role="officer", unit="Cyber Cell" if unit else None,
                owner_hash=ownership.owner_hash(key), demo=officer is None, officer_id=officer, unit_id=unit)


def add(title="Send the notice to the bank", case_id="case-1", who=None, **over):
    who = who or viewer()
    return tasks.create(who.owner_hash, case_id, {"title": title, **over}, who)


# -- adding a task ------------------------------------------------------------------------
def test_a_task_records_what_who_and_by_when():
    t = add(assignee="SI Iyer", due_on="2026-11-20", notes="Account frozen on the 12th")
    assert (t["title"], t["assignee"], t["due_on"], t["status"]) == ("Send the notice to the bank", "SI Iyer",
                                                                    "2026-11-20", "open")
    assert t["days_left"] == 6 and t["overdue"] is False
    assert [h["action"] for h in t["history"]] == ["added"]


def test_a_task_needs_no_date_or_assignee():
    t = add()
    assert (t["assignee"], t["due_on"], t["days_left"], t["overdue"]) == ("", "", None, False)


def test_a_past_due_date_is_allowed_and_shows_overdue():
    t = add(due_on="2026-11-10")
    assert t["days_left"] == -4 and t["overdue"] is True


@pytest.mark.parametrize("over, why", [
    ({"title": "  "}, "Enter what has to be done"),
    ({"title": "x" * 201}, "longer than 200"),
    ({"due_on": "20/11/2026"}, "YYYY-MM-DD"),
    ({"due_on": "2001-01-01"}, "before any cryptocurrency"),
    ({"due_on": "2040-01-01"}, "10 years away"),
    ({"assignee": "y" * 121}, "longer than 120"),
])
def test_bad_input_is_refused_with_the_reason(over, why):
    fields = {"title": "Get the court's order", **over}
    with pytest.raises(TaskError, match=why):
        tasks.create(viewer().owner_hash, "case-1", fields, viewer())


@pytest.mark.parametrize("field", ["title", "assignee", "notes"])
def test_a_seed_phrase_or_key_is_refused_in_every_text_field(field):
    fields = {"title": "Collect the phone extraction", field: SEED}
    with pytest.raises(TaskError, match="private key or seed phrase"):
        tasks.create(viewer().owner_hash, "case-1", fields, viewer())
    with pytest.raises(TaskError, match="private key or seed phrase"):
        tasks.create(viewer().owner_hash, "case-1", {"title": "Check " + "ab" * 32}, viewer())


def test_ordinary_text_is_not_mistaken_for_a_seed_phrase():
    t = add(title="Ask the exchange for the account holder's KYC and the login IP addresses for March",
            notes="They asked for the court's order first; the order was sent on the 10th by speed post.")
    assert t["status"] == "open"


def test_a_task_needs_a_real_case():
    with pytest.raises(TaskError, match="No case"):
        add(case_id="no-such-case")


# -- changing, closing, reopening ---------------------------------------------------------
def test_done_needs_no_reason_and_is_kept_in_history():
    t = add()
    done = tasks.update(t["task_id"], {"status": "done"}, viewer())
    assert done["status"] == "done" and done["changed"] == ["status"]
    assert done["days_left"] is None and done["overdue"] is False
    assert [h["action"] for h in done["history"]] == ["added", "done"]


def test_dropping_or_reopening_needs_a_reason():
    t = add()
    with pytest.raises(TaskError, match="needs a reason"):
        tasks.update(t["task_id"], {"status": "dropped"}, viewer())
    dropped = tasks.update(t["task_id"], {"status": "dropped", "note": "Bank already answered on the portal"}, viewer())
    assert dropped["history"][-1] == {**dropped["history"][-1], "action": "dropped",
                                      "note": "Bank already answered on the portal"}
    with pytest.raises(TaskError, match="needs a reason"):
        tasks.update(t["task_id"], {"status": "open"}, viewer())
    reopened = tasks.update(t["task_id"], {"status": "open", "note": "The portal reply was for another account"}, viewer())
    assert reopened["status"] == "open" and reopened["history"][-1]["action"] == "reopened"


def test_a_closed_task_takes_only_a_note_or_reopening():
    t = add()
    tasks.update(t["task_id"], {"status": "done"}, viewer())
    with pytest.raises(TaskError, match="open it again"):
        tasks.update(t["task_id"], {"due_on": "2026-12-01"}, viewer())
    noted = tasks.update(t["task_id"], {"note": "Reply filed as exhibit 4"}, viewer())
    assert noted["noted"] is True and noted["history"][-1]["action"] == "noted"


def test_changes_record_which_fields_changed():
    t = add(assignee="SI Iyer")
    out = tasks.update(t["task_id"], {"assignee": "SI Pal", "due_on": "2026-11-18", "title": t["title"]}, viewer())
    assert out["changed"] == ["assignee", "due_on"]
    assert out["history"][-1]["changed"] == ["assignee", "due_on"]


def test_nothing_changed_adds_nothing_to_history():
    t = add()
    out = tasks.update(t["task_id"], {"title": t["title"], "status": "open"}, viewer())
    assert out["changed"] == [] and len(out["history"]) == 1


def test_unknown_fields_and_statuses_are_refused():
    t = add()
    with pytest.raises(TaskError, match="cannot be changed: case_id"):
        tasks.update(t["task_id"], {"case_id": "case-2"}, viewer())
    with pytest.raises(TaskError, match="status must be"):
        tasks.update(t["task_id"], {"status": "deleted", "note": "x"}, viewer())


def test_a_full_history_refuses_instead_of_dropping_its_start(monkeypatch):
    monkeypatch.setattr(tasks, "HISTORY_MAX", 2)
    t = add()
    tasks.update(t["task_id"], {"note": "one"}, viewer())
    with pytest.raises(TaskError, match="history is full"):
        tasks.update(t["task_id"], {"note": "two"}, viewer())


# -- who sees what ------------------------------------------------------------------------
def test_another_browser_cannot_see_or_change_a_task():
    t = add()
    assert tasks.list_for(viewer(BOB), "case-1") == []
    assert tasks.update(t["task_id"], {"status": "done"}, viewer(BOB)) is None


def test_a_unit_shares_its_tasks():
    t = add(who=viewer(ALICE, unit=7, officer=1))
    colleague = viewer(BOB, unit=7, officer=2)
    assert [x["task_id"] for x in tasks.list_for(colleague, "case-1")] == [t["task_id"]]
    assert tasks.update(t["task_id"], {"status": "done"}, colleague)["history"][-1]["by"] == "officer-2"
    assert tasks.list_for(viewer(BOB, unit=8, officer=3), "case-1") == []


def test_the_list_puts_open_tasks_first_soonest_due_first():
    later = add("Later", due_on="2026-12-01")
    undated = add("Undated")
    soon = add("Soon", due_on="2026-11-15")
    done = add("Done")
    tasks.update(done["task_id"], {"status": "done"}, viewer())
    assert [t["title"] for t in tasks.list_for(viewer(), "case-1")] == ["Soon", "Later", "Undated", "Done"]
    assert later and undated and soon
    assert tasks.list_for(viewer(), "case-2") == []


def test_due_lists_open_dated_tasks_within_the_window_across_cases():
    add("Overdue", due_on="2026-11-01")
    add("This week", case_id="case-2", due_on="2026-11-19")
    add("Next month", due_on="2026-12-20")
    add("No date")
    closed = add("Closed", due_on="2026-11-02")
    tasks.update(closed["task_id"], {"status": "done"}, viewer())
    assert [t["title"] for t in tasks.due_for(viewer())] == ["Overdue", "This week"]
    assert [t["title"] for t in tasks.due_for(viewer(), within_days=0)] == ["Overdue"]
    assert tasks.due_for(viewer(BOB)) == []


# -- the routes ---------------------------------------------------------------------------
H = {ownership.OWNER_HEADER: ALICE}


@pytest.fixture
def client():
    return TestClient(app)


def test_the_routes_add_list_change_and_show_whats_due(client):
    made = client.post("/trace/case-1/tasks", json={"title": "Get the court's order", "due_on": "2026-11-16"}, headers=H)
    assert made.status_code == 201
    tid = made.json()["task_id"]
    listed = client.get("/trace/case-1/tasks", headers=H).json()
    assert (listed["count"], listed["open"]) == (1, 1)
    assert client.get("/tasks/due", headers=H).json()["tasks"][0]["task_id"] == tid
    changed = client.patch(f"/tasks/{tid}", json={"status": "done"}, headers=H)
    assert changed.status_code == 200 and changed.json()["status"] == "done"
    assert client.get("/tasks/due", headers=H).json()["count"] == 0


def test_the_routes_refuse_bad_input_and_strangers(client):
    assert client.post("/trace/case-1/tasks", json={"title": SEED}, headers=H).status_code == 400
    assert client.post("/trace/case-1/tasks", json={"title": "x"}).status_code == 400  # no owner key
    tid = client.post("/trace/case-1/tasks", json={"title": "x"}, headers=H).json()["task_id"]
    assert client.patch(f"/tasks/{tid}", json={"status": "dropped"}, headers=H).status_code == 400
    assert client.patch(f"/tasks/{tid}", json={"notes": "y"}, headers={ownership.OWNER_HEADER: BOB}).status_code == 404


def test_the_audit_log_records_what_changed_never_the_text(client):
    tid = client.post("/trace/case-1/tasks", json={"title": "Call SI Iyer"}, headers=H).json()["task_id"]
    client.patch(f"/tasks/{tid}", json={"assignee": "SI Iyer"}, headers=H)
    client.patch(f"/tasks/{tid}", json={"status": "dropped", "note": "Done by phone"}, headers=H)
    client.patch(f"/tasks/{tid}", json={"note": "Logged in the diary"}, headers=H)
    with models.session() as s:
        rows = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action.like("task.%"),
                                                         models.AuditEvent.action != "task.list")).all()
    details = [(r.action, json.loads(r.detail)) for r in rows]
    assert details == [("task.add", {"task_id": tid}),
                       ("task.update", {"task_id": tid, "changed": ["assignee"]}),
                       ("task.update", {"task_id": tid, "changed": ["status"], "status": "dropped"}),
                       ("task.update", {"task_id": tid, "changed": [], "noted": True})]
    assert "Iyer" not in json.dumps([d for _, d in details]) and "phone" not in json.dumps([d for _, d in details])


def test_g7_tasks_1_goes_down_and_up_again_keeping_the_cases():
    """case_tasks is a table of its own: rolling it back leaves every case."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from app import config
    add()
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with models._engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.downgrade(settings, "g7_domain_lookups_1")
    assert "case_tasks" not in set(inspect(models._engine).get_table_names())
    assert models.get_case("case-1") is not None
    models.init_db()
    assert "case_tasks" in set(inspect(models._engine).get_table_names())
    assert tasks.list_for(viewer(), "case-1") == []
