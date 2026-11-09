"""The watcher is idle when there is nothing to watch (watchlist._loop).

It queried the store every 60 s whether or not a watch existed. That is
shorter than Neon's 5-minute scale-to-zero window, so the free database's
compute never slept while the site was awake and spent the month's hours.
Now it parks until a watch is created, and rounds are a full interval apart."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event

from app import models, ownership, watchlist

WALLET = "0x" + "7" * 40


@pytest.fixture
def engine(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'w.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    return engine


@pytest.fixture
def statements(engine):
    seen: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, sql, *a: seen.append(sql))
    return seen


class OneRound:
    """Stands in for the loop's events: records how the loop waits, then stops it."""

    def __init__(self):
        self.waits: list[tuple[str, float | None]] = []
        self.stopped = False

    def event(self, name: str):
        gate = self

        class Event:
            def is_set(self):
                return gate.stopped if name == "stop" else False

            def wait(self, timeout=None):
                gate.waits.append((name, timeout))
                gate.stopped = True
                return False

            def set(self):
                pass

            def clear(self):
                pass
        return Event()


@pytest.fixture
def one_round(monkeypatch):
    gate = OneRound()
    monkeypatch.setattr(watchlist, "_stop", gate.event("stop"))
    monkeypatch.setattr(watchlist, "_wake", gate.event("wake"), raising=False)
    return gate


def test_with_no_watches_the_loop_parks_after_one_query(engine, statements, one_round):
    watchlist._loop(600)
    assert one_round.waits == [("wake", None)]  # until a watch is created
    assert len(statements) == 1


def test_with_watches_rounds_are_a_full_interval_apart(engine, one_round, monkeypatch):
    checked = []
    monkeypatch.setattr(watchlist, "check_watch", lambda watch_id: checked.append(watch_id))
    w = watchlist.create_watch(ownership.owner_hash("a" * 32), WALLET, "ethereum", "ETH")
    watchlist._loop(600)
    assert checked == [w.id]
    assert one_round.waits == [("wake", 600)]


def test_creating_a_watch_wakes_the_watcher(engine):
    watchlist._wake.clear()
    watchlist.create_watch(ownership.owner_hash("a" * 32), WALLET, "ethereum", "ETH")
    assert watchlist._wake.is_set()
    watchlist._wake.clear()


def test_stopping_wakes_a_parked_watcher(engine):
    watchlist._wake.clear()
    watchlist.stop()
    assert watchlist._wake.is_set() and watchlist._stop.is_set()
    watchlist._stop.clear()
    watchlist._wake.clear()
