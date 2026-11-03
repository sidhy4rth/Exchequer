"""What the watcher has actually done (watchlist.watcher_status, R30): the
panel and /health/detail say when watches were last checked, and warn when
that was too long ago -- on a host that sleeps, the watcher sleeps with it.

Runs against a throwaway SQLite file; nothing is checked against a chain.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import config, models, ownership, watchlist
from app.main import app

OWNER = "o" * 32
TOKEN = "t" * 40


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'w.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(config, "WATCHER_ENABLED", True)
    monkeypatch.setattr(config, "WATCH_INTERVAL_SECONDS", 600)


def ago(minutes: float) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def add_watch(watch_id: str, checked: float | None, created: float = 0, active: bool = True) -> None:
    with models.session() as s:
        s.add(models.Watch(
            id=watch_id, owner_hash=ownership.owner_hash(OWNER), chain="ethereum", asset="ETH",
            address="0x" + "1" * 40, note="", created_at=ago(created),
            last_checked_at=None if checked is None else ago(checked), active=active,
        ))
        s.commit()


def test_no_watches_is_nothing_to_warn_about(store):
    status = watchlist.watcher_status()
    assert status["enabled"] is True and status["active_watches"] == 0
    assert status["last_check_at"] is None and status["stale"] is False


def test_a_recent_check_is_reported_and_not_stale(store):
    add_watch("w1", checked=4)
    add_watch("w2", checked=12)
    status = watchlist.watcher_status()
    assert status["active_watches"] == 2
    assert status["last_check_at"] == ago(4)
    assert status["stale"] is False


def test_no_check_for_three_intervals_is_stale(store):
    add_watch("w1", checked=31)  # interval 10 min
    assert watchlist.watcher_status()["stale"] is True


def test_a_new_watch_is_not_stale_until_it_is_overdue(store):
    add_watch("fresh", checked=None, created=1)
    assert watchlist.watcher_status()["stale"] is False
    add_watch("forgotten", checked=None, created=120)
    assert watchlist.watcher_status()["stale"] is True


def test_a_watch_added_just_now_does_not_hide_a_silent_watcher(store):
    add_watch("old", checked=31)
    add_watch("new", checked=None, created=0)
    assert watchlist.watcher_status()["stale"] is True


def test_with_the_watcher_off_nothing_is_stale_it_is_off(store, monkeypatch):
    monkeypatch.setattr(config, "WATCHER_ENABLED", False)
    add_watch("w1", checked=600)
    status = watchlist.watcher_status()
    assert status["enabled"] is False and status["stale"] is False


def test_removed_watches_do_not_count(store):
    add_watch("gone", checked=600, active=False)
    status = watchlist.watcher_status()
    assert status["active_watches"] == 0 and status["stale"] is False


def test_the_panel_and_the_operator_both_see_it(store, monkeypatch):
    add_watch("w1", checked=45)
    monkeypatch.setattr(config, "HEALTH_TOKEN", TOKEN)
    client = TestClient(app)
    panel = client.get("/watches", headers={ownership.OWNER_HEADER: OWNER}).json()
    assert panel["watcher"]["stale"] is True and panel["watcher"]["last_check_at"] == ago(45)
    detail = client.get("/health/detail", headers={"authorization": f"Bearer {TOKEN}"}).json()
    assert detail["watcher"]["stale"] is True
