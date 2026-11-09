"""Dust sent to an exchange or a flagged address never buries a real alert
(r2-g2-watchlist-alerts-0-1, 8 Nov check).

Unread exchange and flagged alerts were kept and listed first with no regard
to value. So a scammer who cashed out 25 ETH to Binance, then sent 120 sends
of 0.000001 ETH to the same hot wallet, pushed the cash-out out of GET
/alerts; 300 such sends to a sanctioned address made the per-watch cap
delete it. Below the asset's dust floor an alert is now low priority:
stored, shown and posted after every material one.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app import models, ownership, watchlist
from app.main import app
from test_watchlist import ALICE, BINANCE_14, STRANGER, TORNADO, WALLET, FakeChain, owner, tx

DUST = 0.000001


@pytest.fixture
def chain(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(watchlist, "chain_head", lambda *a, **k: None)
    return FakeChain()


def stored(watch_id):
    with models.session() as s:
        return list(s.scalars(select(models.Alert).where(models.Alert.watch_id == watch_id)))


def cash_out_then_dust(chain, sends=250, per_check=50):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)  # history
    chain.transfers = [tx(101, BINANCE_14, 25.0)]
    watchlist.check_watch(w.id, source=chain)
    block = 102
    for _ in range(sends // per_check):  # urgent-kind dust, to Binance and to a mixer
        chain.transfers = [tx(block + i, BINANCE_14 if i % 2 else TORNADO, DUST) for i in range(per_check)]
        block += per_check
        watchlist.check_watch(w.id, source=chain)
    return w


def test_a_cash_out_then_250_urgent_dust_sends_keeps_the_cash_out_first(chain):
    w = cash_out_then_dust(chain)
    rows = stored(w.id)
    assert len(rows) == watchlist.MAX_ALERTS_PER_WATCH  # the cap still holds
    assert [r.value for r in rows if r.value == 25.0] == [25.0]  # and kept the cash-out
    top = watchlist.list_alerts(owner(ALICE))
    assert (top[0]["kind"], top[0]["value"]) == ("exchange", 25.0) and top[0]["dust"] is False
    body = TestClient(app).get("/alerts", headers={ownership.OWNER_HEADER: ALICE}).json()
    assert body["alerts"][0]["value"] == 25.0
    assert all(a["dust"] or a["kind"] == "more" for a in body["alerts"][1:])


def test_dust_to_a_sanctioned_address_never_makes_the_cap_delete_the_cash_out(chain, monkeypatch):
    monkeypatch.setattr(watchlist, "MAX_ALERTS_PER_WATCH", 30)
    w = cash_out_then_dust(chain, sends=300)
    rows = stored(w.id)
    assert len(rows) == 30 and any(r.value == 25.0 and r.kind == "exchange" for r in rows)


def test_past_the_cap_the_smallest_material_alerts_go_never_the_largest(chain, monkeypatch):
    monkeypatch.setattr(watchlist, "MAX_ALERTS_PER_WATCH", 10)
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(101, BINANCE_14, 25.0)]
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(102 + i, BINANCE_14, 2.0 + i / 100) for i in range(20)]
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(200 + i, STRANGER, 1.0) for i in range(20)]  # newer, not urgent
    watchlist.check_watch(w.id, source=chain)
    values = sorted((r.value for r in stored(w.id)), reverse=True)
    assert len(values) == 10 and values[0] == 25.0 and values[-1] == 2.11


def test_many_sends_just_above_the_floor_cannot_bury_a_cash_out_either(chain, monkeypatch):
    # 0.001 ETH is the floor itself (about $3): 300 such sends to a mixer
    # sorted above the 25 ETH cash-out by time, and pushed it past the ceiling.
    monkeypatch.setattr(watchlist, "MAX_ALERTS_PER_WATCH", 100)
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(101, BINANCE_14, 25.0)]
    watchlist.check_watch(w.id, source=chain)
    for start in (102, 152, 202, 252, 302, 352):
        chain.transfers = [tx(start + i, TORNADO, 0.001) for i in range(50)]
        watchlist.check_watch(w.id, source=chain)
    assert any(r.value == 25.0 for r in stored(w.id))
    assert watchlist.list_alerts(owner(ALICE))[0]["value"] == 25.0


def test_once_read_a_cash_out_is_pruned_like_any_other_alert(chain, monkeypatch):
    monkeypatch.setattr(watchlist, "MAX_ALERTS_PER_WATCH", 30)
    w = cash_out_then_dust(chain, sends=0)
    watchlist.mark_read(owner(ALICE))
    chain.transfers = [tx(300 + i, STRANGER, 1.0) for i in range(40)]
    watchlist.check_watch(w.id, source=chain)
    with models.session() as s:
        assert s.scalar(select(func.count()).select_from(models.Alert)) == 30


def test_the_dust_floor_is_per_asset():
    assert watchlist.is_dust(0.0009, "ETH") and not watchlist.is_dust(0.001, "ETH")
    assert watchlist.is_dust(0.5, "USDT") and not watchlist.is_dust(5.0, "USDT")
    assert watchlist.is_dust(9.0, "TRX") and not watchlist.is_dust(10.0, "trx")


# -- every kind ranked by size, dust below everything material (8 Nov re-check, p_bury2) ----
# Every alert that was not an unread material exchange or flagged alert
# sorted as equal, newest first. So a 25 ETH "moved" alert (the next hop an
# officer must follow) followed by 240 one-wei sends to fresh addresses was
# deleted by the per-watch cap, and after 120 sends of 0.0011 ETH to an
# exchange it was not in GET /alerts' top 100. Now every unread alert above
# the dust floor ranks before every dust alert, each by its size in dust
# floors (an exchange or flagged alert counting a hundred times its size,
# so a small cash-out still outranks a larger movement), and the cap deletes
# dust first.
def fresh(i):
    return "0x" + f"{0xabc000 + i:040x}"


def moved_then(chain, sends, n, checks=4):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)  # history
    chain.transfers = [tx(101, STRANGER, 25.0)]
    watchlist.check_watch(w.id, source=chain)
    block = 102
    for _ in range(checks):
        chain.transfers = [tx(block + i, *sends(block + i)) for i in range(n // checks)]
        block += n // checks
        watchlist.check_watch(w.id, source=chain)
    return w


def test_a_large_movement_survives_240_one_wei_sends(chain):
    w = moved_then(chain, lambda i: (fresh(i), 1e-18), 240)
    rows = stored(w.id)
    assert len(rows) <= watchlist.MAX_ALERTS_PER_WATCH
    assert any(r.value == 25.0 and r.kind == "moved" for r in rows)  # the cap deleted dust, not it
    top = watchlist.list_alerts(owner(ALICE))
    assert (top[0]["kind"], top[0]["value"]) == ("moved", 25.0)


def test_a_large_movement_stays_in_the_list_past_120_small_exchange_sends(chain):
    w = moved_then(chain, lambda i: (BINANCE_14, 0.0011), 120)
    assert any(r.value == 25.0 for r in stored(w.id))
    top = watchlist.list_alerts(owner(ALICE))
    assert any(a["value"] == 25.0 and a["kind"] == "moved" for a in top)
    body = TestClient(app).get("/alerts", headers={ownership.OWNER_HEADER: ALICE}).json()
    assert any(a["value"] == 25.0 for a in body["alerts"])


def test_a_cash_out_still_outranks_a_larger_movement(chain):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(101, STRANGER, 25.0), tx(102, BINANCE_14, 2.0)]
    watchlist.check_watch(w.id, source=chain)
    top = watchlist.list_alerts(owner(ALICE))
    assert [(a["kind"], a["value"]) for a in top[:2]] == [("exchange", 2.0), ("moved", 25.0)]


def test_the_cap_never_deletes_an_unread_material_alert_while_dust_remains(chain, monkeypatch):
    monkeypatch.setattr(watchlist, "MAX_ALERTS_PER_WATCH", 30)
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(101 + i, fresh(i), 0.5 + i / 100) for i in range(10)]  # ten material movements
    watchlist.check_watch(w.id, source=chain)
    for start in (200, 250, 300):  # 150 newer dust sends, of every kind
        chain.transfers = [tx(start + i, (fresh(1000 + i), BINANCE_14, TORNADO)[i % 3], DUST) for i in range(50)]
        watchlist.check_watch(w.id, source=chain)
    rows = stored(w.id)
    assert len(rows) == 30
    assert sum(1 for r in rows if r.kind == "moved" and r.value >= 0.5) == 10


def test_material_movements_are_kept_largest_first_past_the_cap(chain, monkeypatch):
    monkeypatch.setattr(watchlist, "MAX_ALERTS_PER_WATCH", 5)
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(101, fresh(0), 25.0)] + [tx(102 + i, fresh(1 + i), 0.01 + i / 1000) for i in range(20)]
    watchlist.check_watch(w.id, source=chain)
    values = sorted((r.value for r in stored(w.id) if r.kind == "moved"), reverse=True)
    assert values[0] == 25.0 and len(values) <= 5
    listed = [a["value"] for a in watchlist.list_alerts(owner(ALICE)) if a["kind"] == "moved"]
    assert listed == sorted(listed, reverse=True)
