"""The offline prune script: it deletes evidence, so it must never guess.

What matters here:
  * a case to keep that is not in the store (a typo) deletes nothing;
  * nothing is deleted without --yes, and the run lists what would go;
  * the backup holds every case even while the write-ahead log is unmerged;
  * a Postgres store is refused unless a dump was taken;
  * a case an officer sent a freeze request about is never deleted;
  * a watch on a deleted case is unlinked, not left pointing at nothing;
  * the script never migrates the store it is pointed at.
"""
from __future__ import annotations

import shutil
import sqlite3

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import config, models
from scripts import prune_cases

IDS = ["case-a", "case-b", "case-c"]


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "prune.db"
    engine = create_engine(f"sqlite:///{path}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    monkeypatch.setattr(config, "DB_PATH", path)
    models.init_db()
    for case_id in IDS:
        models.save_case(case_id, "0x" + "1" * 40, {"graph": {"nodes": []}})
    yield path
    engine.dispose()


def stored() -> list[str]:
    with Session(models._engine) as session:
        return sorted(session.scalars(select(models.Case.id)))


def backups(path):
    return sorted(path.parent.glob(f"{path.name}.bak-*"))


def test_a_keep_id_that_is_not_stored_deletes_nothing(store, capsys):
    assert prune_cases.main(["--keep", "case-O", "--yes"]) == 2
    assert stored() == IDS
    assert "case-O" in capsys.readouterr().out
    assert backups(store) == []


def test_without_yes_nothing_is_deleted_and_the_run_lists_what_would_go(store, capsys):
    assert prune_cases.main(["--keep", "case-a"]) == 0
    out = capsys.readouterr().out
    assert stored() == IDS
    assert "case-b" in out and "case-c" in out and "--yes" in out
    assert backups(store) == []


def test_the_backup_holds_every_case_while_the_log_is_unmerged(store, tmp_path):
    # The engine's pooled connection is still open, so the cases sit in the
    # -wal file; a copy of the main file alone would hold none of them.
    assert store.with_name(store.name + "-wal").stat().st_size > 0
    assert prune_cases.main(["--keep", "case-a", "--yes"]) == 0
    assert stored() == ["case-a"]
    [backup] = backups(store)
    alone = tmp_path / "restored" / "store.db"
    alone.parent.mkdir()
    shutil.copy(backup, alone)  # the backup file by itself, no side files
    db = sqlite3.connect(alone)
    try:
        assert sorted(r[0] for r in db.execute("SELECT id FROM cases")) == IDS
    finally:
        db.close()


def test_a_postgres_store_is_refused_without_a_dump(monkeypatch, capsys):
    engine = create_engine("postgresql+psycopg://user:secret@db.example/cases", future=True)

    def no_connection(*_a, **_k):
        raise AssertionError("the script connected to a store it should have refused")

    monkeypatch.setattr(engine, "connect", no_connection)
    monkeypatch.setattr(models, "_engine", engine)
    assert prune_cases.main(["--keep", "case-a", "--yes"]) == 2
    out = capsys.readouterr().out
    assert "db.example" in out and "pg_dump" in out
    assert "secret" not in out


def test_cases_with_freeze_requests_are_kept(store, capsys):
    with Session(models._engine) as session, session.begin():
        session.add(models.FreezeRequest(
            id="req-1", owner_hash="o", case_id="case-b", recipient="Binance", kind="exchange",
            status="sent", created_at="2026-11-01", updated_at="2026-11-01"))
    assert prune_cases.main(["--keep", "case-a", "--yes"]) == 2
    assert stored() == IDS
    assert "case-b" in capsys.readouterr().out


def test_watches_on_deleted_cases_are_unlinked(store):
    with Session(models._engine) as session, session.begin():
        for watch_id, case_id in (("w-1", "case-b"), ("w-2", "case-a")):
            session.add(models.Watch(id=watch_id, owner_hash="o", chain="ethereum", asset="ETH",
                                     address="0x" + "2" * 40, case_id=case_id, created_at="2026-11-01"))
    assert prune_cases.main(["--keep", "case-a", "--yes"]) == 0
    with Session(models._engine) as session:
        links = dict(session.execute(select(models.Watch.id, models.Watch.case_id)).all())
    assert links == {"w-1": None, "w-2": "case-a"}


def test_the_script_never_migrates(store, monkeypatch, tmp_path):
    def migrate():
        raise AssertionError("the prune script migrated the store")

    monkeypatch.setattr(models, "init_db", migrate)
    assert prune_cases.main(["--keep", "case-a", "--yes"]) == 0
    assert stored() == ["case-a"]

    # A store that is not at the current schema is refused, not upgraded.
    blank = tmp_path / "blank.db"
    engine = create_engine(f"sqlite:///{blank}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    monkeypatch.setattr(config, "DB_PATH", blank)
    try:
        assert prune_cases.main(["--keep", "case-a", "--yes"]) == 2
    finally:
        engine.dispose()
