"""Who holds the watch slots (r1-authz-routes-3).

Owner keys are free, so the 25-watches-per-owner cap limited nothing: about
21 invented keys from one connection took all 500 slots and every officer
then got "The server is watching as many addresses as it can", for ever,
since watches never expired. Now one connection holds at most its share,
whatever owner keys it uses, and a watch nobody has listed or checked for
two weeks gives up its slot when the server is full.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app import config, models, ownership, watchlist
from app.main import app

KEYS = [c * 32 for c in "abcdefg"]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(watchlist, "chain_head", lambda *a, **k: None)


def address(i):
    return "0x" + f"{i + 1:040x}"


def post(key, i, peer="10.0.0.1"):
    return TestClient(app, client=(peer, 5000)).post(
        "/watches", json={"address": address(i), "chain": "ethereum"}, headers={ownership.OWNER_HEADER: key})


def days_ago(n):
    return (datetime.now(tz=timezone.utc) - timedelta(days=n)).isoformat(timespec="seconds")


def test_one_connection_cannot_hold_more_than_its_share_whatever_owner_keys_it_uses(store, monkeypatch):
    monkeypatch.setattr(config, "WATCHES_PER_CLIENT", 3)
    assert [post(KEYS[i], i).status_code for i in range(3)] == [201, 201, 201]
    refused = post(KEYS[3], 3)
    assert refused.status_code == 400 and "This connection already watches 3" in refused.json()["detail"]


def test_another_connection_still_gets_a_slot(store, monkeypatch):
    monkeypatch.setattr(config, "WATCHES_PER_CLIENT", 1)
    assert post(KEYS[0], 0).status_code == 201
    assert post(KEYS[1], 1).status_code == 400
    assert post(KEYS[1], 1, peer="10.0.0.2").status_code == 201


def test_an_ipv6_connection_is_one_client_across_its_slash_64(store, monkeypatch):
    monkeypatch.setattr(config, "WATCHES_PER_CLIENT", 1)
    assert post(KEYS[0], 0, peer="2001:db8:1:2::1").status_code == 201
    assert post(KEYS[1], 1, peer="2001:db8:1:2::ffff").status_code == 400


def test_a_watch_untouched_for_14_days_gives_up_its_slot_when_the_server_is_full(store, monkeypatch):
    monkeypatch.setattr(watchlist, "MAX_WATCHES_TOTAL", 2)
    old = watchlist.create_watch(ownership.owner_hash(KEYS[0]), address(0), "ethereum", "ETH")
    kept = watchlist.create_watch(ownership.owner_hash(KEYS[1]), address(1), "ethereum", "ETH")
    with models.session() as s:
        s.get(models.Watch, old.id).touched_at = days_ago(15)
        s.add(models.Alert(id="gone", watch_id=old.id, owner_hash=old.owner_hash, created_at=days_ago(15),
                           kind="moved", message="m", tx_hash="0x1", tx_time=1, value=1.0, asset="ETH",
                           counterparty=address(5), counterparty_label=""))
        s.commit()
    new = watchlist.create_watch(ownership.owner_hash(KEYS[2]), address(2), "ethereum", "ETH")
    with models.session() as s:
        assert s.get(models.Watch, old.id).active is False and s.get(models.Watch, old.id).webhook_url is None
        assert s.get(models.Watch, kept.id).active is True and s.get(models.Watch, new.id).active is True
        assert s.scalar(select(func.count()).select_from(models.Alert)) == 0
    # Recently used watches are never taken: the server is full again.
    with pytest.raises(watchlist.WatchError, match="as many addresses"):
        watchlist.create_watch(ownership.owner_hash(KEYS[3]), address(3), "ethereum", "ETH")


def test_listing_or_checking_keeps_a_watch_alive(store, monkeypatch):
    owner = ownership.owner_hash(KEYS[0])
    w = watchlist.create_watch(owner, address(0), "ethereum", "ETH")
    for when in (days_ago(10), days_ago(10)):
        with models.session() as s:
            s.get(models.Watch, w.id).touched_at = when
            s.commit()
    TestClient(app).get("/watches", headers={ownership.OWNER_HEADER: KEYS[0]})
    with models.session() as s:
        assert s.get(models.Watch, w.id).touched_at > days_ago(1)
        s.get(models.Watch, w.id).touched_at = days_ago(10)
        s.commit()
    monkeypatch.setattr(watchlist, "check_watch", lambda wid, **k: [])
    TestClient(app).post(f"/watches/{w.id}/check", headers={ownership.OWNER_HEADER: KEYS[0]})
    with models.session() as s:
        assert s.get(models.Watch, w.id).touched_at > days_ago(1)


def test_legacy_watches_without_a_client_count_against_no_one(store, monkeypatch):
    monkeypatch.setattr(config, "WATCHES_PER_CLIENT", 1)
    for i in range(3):  # made before connections were recorded
        watchlist.create_watch(ownership.owner_hash(KEYS[i]), address(i), "ethereum", "ETH")
    assert post(KEYS[4], 4).status_code == 201
