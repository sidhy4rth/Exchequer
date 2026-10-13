"""Store snapshots (app/backups.py) and GET /admin/backup (app/routes/admin.py)."""
from __future__ import annotations

import gzip
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import backups, config, models
from app.main import app


@pytest.fixture
def store(tmp_path, monkeypatch):
    db = tmp_path / "exchequer.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    monkeypatch.setattr(config, "DB_PATH", db)
    models.init_db()
    models.save_case("c1", "0x" + "1" * 40, {"address": "0x" + "1" * 40, "chain": "ethereum"})
    return db


def _restore(gz: bytes, tmp_path):
    raw = tmp_path / "restored.db"
    raw.write_bytes(gzip.decompress(gz))
    return sqlite3.connect(raw)


def test_a_snapshot_is_a_working_copy_of_the_store(store, tmp_path):
    out = backups.snapshot(tmp_path / "out" / "snap.db.gz")
    con = _restore(out.read_bytes(), tmp_path)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT id FROM cases").fetchall() == [("c1",)]
    assert not list(out.parent.glob("*.part"))


def test_daily_writes_once_a_day_and_keeps_the_last_few(store, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_KEEP", 3)
    for day in range(1, 6):
        when = datetime(2026, 10, day, tzinfo=timezone.utc)
        assert backups.daily(when) is not None
        assert backups.daily(when) is None  # same day: already there
    names = sorted(p.name for p in backups.backup_dir().iterdir())
    assert names == [f"exchequer-2026-10-0{d}.db.gz" for d in (3, 4, 5)]


def test_the_endpoint_does_not_exist_without_a_token(store, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_TOKEN", "")
    assert TestClient(app).get("/admin/backup", headers={"Authorization": "Bearer x"}).status_code == 404


def test_the_endpoint_needs_the_exact_token(store, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BACKUP_TOKEN", "s3cret-token")
    client = TestClient(app)
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "s3cret-token"},
                    {"Authorization": "Basic s3cret-token"}):
        assert client.get("/admin/backup", headers=headers).status_code == 401
    resp = client.get("/admin/backup", headers={"Authorization": "Bearer s3cret-token"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"
    assert resp.headers["cache-control"] == "no-store"
    con = _restore(resp.content, tmp_path)
    assert con.execute("SELECT count(*) FROM cases").fetchone()[0] == 1
