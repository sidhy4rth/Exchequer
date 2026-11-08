"""Alerts do not outlive their watch, and the table has a site-wide budget
(r2-g2-watchlist-alerts-0-3, 8 Nov check).

remove_watch only marked the watch inactive and kept every alert; nothing
else deleted them, and inactive watches counted toward no cap. Five rounds
of (watch a busy wallet, fill it, remove it) left 1000 rows, and creation
limits alone allowed about 290k rows a day: the free 0.5 GB database fills
in days. Now removing a watch deletes its alerts, and past MAX_ALERTS_TOTAL
the oldest go, least important first.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app import models, ownership, watchlist
from app.main import app
from test_watchlist import ALICE, BINANCE_14, BOB, STRANGER, WALLET, FakeChain, owner, tx


@pytest.fixture
def chain(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'k.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(watchlist, "chain_head", lambda *a, **k: None)
    return FakeChain()


def rows(**where):
    with models.session() as s:
        stmt = select(func.count()).select_from(models.Alert)
        for k, v in where.items():
            stmt = stmt.where(getattr(models.Alert, k) == v)
        return s.scalar(stmt)


def filled(chain, key=ALICE, address=WALLET, start=100, n=150, to=STRANGER, value=1.0):
    w = watchlist.create_watch(owner(key), address, "ethereum", "ETH")
    chain.transfers = [tx(start, to)]
    watchlist.check_watch(w.id, source=chain)  # history
    for page in range(n // 50):
        chain.transfers = [tx(start + 1 + page * 50 + i, to, value) for i in range(50)]
        watchlist.check_watch(w.id, source=chain)
    return w


def test_create_fill_remove_leaves_no_alert_rows(chain):
    w = filled(chain)
    assert rows(watch_id=w.id) > 100
    assert watchlist.remove_watch(owner(ALICE), w.id)
    assert rows() == 0


def test_five_rounds_of_create_fill_remove_leave_nothing(chain):
    for n in range(5):
        w = filled(chain, start=1000 * (n + 1))
        watchlist.remove_watch(owner(ALICE), w.id)
    assert rows() == 0


def test_removing_through_the_api_empties_the_alert_list(chain):
    w = filled(chain, n=50)
    client = TestClient(app)
    h = {ownership.OWNER_HEADER: ALICE}
    assert client.get("/alerts", headers=h).json()["count"] > 0
    assert client.delete(f"/watches/{w.id}", headers=h).status_code == 200
    assert client.get("/alerts", headers=h).json()["count"] == 0


def test_alerts_left_by_watches_removed_before_this_fix_are_pruned(chain):
    old = filled(chain, n=50)
    with models.session() as s:  # removed the old way: inactive, alerts kept
        s.get(models.Watch, old.id).active = False
        s.commit()
    keep = filled(chain, key=BOB, n=50)
    other = filled(chain, key=BOB, address="0x" + "6" * 40, n=50)
    watchlist.remove_watch(owner(BOB), other.id)
    assert rows(watch_id=old.id) == 0 and rows(watch_id=other.id) == 0
    assert rows(watch_id=keep.id) > 0  # an active watch's alerts are untouched


def test_the_table_has_a_site_wide_budget_and_drops_the_least_important_first(chain, monkeypatch):
    monkeypatch.setattr(watchlist, "MAX_ALERTS_TOTAL", 120)
    cash = filled(chain, key=ALICE, n=50, to=BINANCE_14, value=5.0)  # 50 unread cash-outs
    read = filled(chain, key=BOB, address="0x" + "6" * 40, start=500, n=50)
    watchlist.mark_read(owner(BOB))
    busy = filled(chain, key=BOB, address="0x" + "5" * 40, start=900, n=100)
    assert rows() <= 120
    assert rows(watch_id=cash.id, kind="exchange") == 50  # unread cash-outs kept
    assert rows(watch_id=read.id) == 0  # read alerts went first
    assert rows(watch_id=busy.id) > 0
