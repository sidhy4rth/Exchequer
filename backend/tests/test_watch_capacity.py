"""Watch checks cannot use up what traces need, and the watch caps hold under
concurrency (r1-authz-routes-3, 8 Nov check).

"Check now" reads were charged only to the site's daily provider allowance,
with no connection's share: a few connections at the per-minute ceiling could
spend the whole day's Etherscan allowance, and every trace was refused until
midnight UTC. Now a check's reads count against the connection's share and
against the part of the day kept for watch checks (WATCH_SHARE_PERCENT), and
the per-minute ceilings are lower. The create caps were checked apart from
the insert: 40 creates at once for one owner made 36 watches against a cap
of 25. Count and insert now happen under one lock.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app import api_budget, config, models, ownership, rate_limit, watchlist
from app.api_budget import BudgetSpent, TraceBudget, UnitMeter
from app.main import app
from app.routes import watches as watch_routes

sys.path.insert(0, str(Path(__file__).parent))
import test_watch_forward_read as fr  # noqa: E402

KEY = "q" * 32


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'w.db'}", future=True))
    models.init_db()
    for name in ("watches", "watches_total"):
        monkeypatch.setattr(rate_limit, name, rate_limit.SlidingWindowLimiter(1000, 3600))
    # This module's checks must not use up the per-minute ceilings of later tests.
    monkeypatch.setattr(watch_routes, "checks_per_client",
                        rate_limit.SlidingWindowLimiter(watch_routes.CHECKS_PER_MINUTE_PER_CLIENT, 60))
    monkeypatch.setattr(watch_routes, "checks_total",
                        rate_limit.SlidingWindowLimiter(watch_routes.CHECKS_PER_MINUTE_TOTAL, 60))
    api_budget.reset()
    yield
    api_budget.reset()


def _meter() -> UnitMeter:
    return api_budget.get_meter("etherscan", api_budget.credential("k"))


def test_check_now_reads_count_against_the_connection_and_the_watch_part(store, monkeypatch):
    """The probe: 10 checks from one connection showed meter connections=0, so
    no share applied. Now they are that connection's, and watch checks'."""
    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 1000)
    eth = fr.Etherscan(head=1000)
    src = eth.source()
    real = watchlist.check_watch
    monkeypatch.setattr(watchlist, "check_watch", lambda wid, *a, **k: real(wid, source=src, post=lambda u, p: None))
    client = TestClient(app)
    ids = [client.post("/watches", json={"address": "0x" + f"{9000 + i:040x}", "chain": "ethereum"},
                       headers={ownership.OWNER_HEADER: KEY}).json()["watch_id"] for i in range(3)]
    with models.session() as s:
        for w in s.scalars(select(models.Watch)):
            w.last_seen_block = 900
        s.commit()
    assert all(client.post(f"/watches/{w}/check", headers={ownership.OWNER_HEADER: KEY}).status_code == 200
               for w in ids)
    stats = _meter().stats()
    assert stats["connections"] == 1 and stats["used"] == stats["watch_used"] > 0


def test_watch_checks_stop_at_their_part_of_the_day_and_traces_go_on():
    meter = UnitMeter("etherscan", 100, client_share=0.25, watch_share=0.2)
    # Each connection's watch checks may take a quarter of the 20 units kept for watches.
    for n in range(3):
        for _ in range(5):
            assert meter.charge(1, client=f"10.0.0.{n}", watch=True) is None
        assert meter.charge(1, client=f"10.0.0.{n}", watch=True) == "watch-client"
    for _ in range(5):
        assert meter.charge(1, client="10.0.0.3", watch=True) is None
    assert meter.charge(1, client="10.0.0.9", watch=True) == "watch"  # four connections spent the part
    assert meter.charge(1, watch=True) == "watch"  # the background watcher too
    # 80 units are still there for traces, the same connections' included.
    assert meter.charge(1, client="10.0.0.0") is None
    assert meter.stats()["remaining"] == 79


def test_a_refused_watch_read_stops_the_check_with_the_reason(store, monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 100)
    monkeypatch.setattr(config, "WATCH_SHARE_PERCENT", 20)
    monkeypatch.setattr(config, "PROVIDER_CLIENT_SHARE_PERCENT", 25)
    api_budget.reset()
    with api_budget.charged_to("10.0.0.1", watch=True):
        for _ in range(5):  # a quarter of the 20 kept for watches
            api_budget.spend("etherscan", "k", 1, None)
        with pytest.raises(BudgetSpent) as stopped:
            api_budget.spend("etherscan", "k", 1, None)
    assert "watch checks" in stopped.value.reason
    api_budget.spend("etherscan", "k", 1, TraceBudget(60, 0, client="10.0.0.1"))  # a trace still reads


def test_the_per_minute_ceilings_fit_the_watch_part_of_the_day():
    # Two reads per check on Ethereum: one connection at its ceiling for a day
    # would spend far more than its share, so the share is what stops it; the
    # site-wide ceiling takes ten connections to fill.
    assert watch_routes.CHECKS_PER_MINUTE_PER_CLIENT <= 3
    assert watch_routes.CHECKS_PER_MINUTE_TOTAL // watch_routes.CHECKS_PER_MINUTE_PER_CLIENT >= 10
    assert 0 < config.WATCH_SHARE_PERCENT <= 25


def test_concurrent_creates_never_pass_the_owner_cap(store):
    """The probe: 40 creates at once for one owner gave 36 active watches."""
    owner = ownership.owner_hash("z" * 32)
    barrier = threading.Barrier(40)
    errors: list[str] = []

    def make(i):
        barrier.wait()
        try:
            watchlist.create_watch(owner, "0x" + f"{5000 + i:040x}", "ethereum", "ETH", client=f"10.0.0.{i}")
        except watchlist.WatchError:
            errors.append("refused")
    threads = [threading.Thread(target=make, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with models.session() as s:
        active = s.scalar(select(func.count()).select_from(models.Watch)
                          .where(models.Watch.owner_hash == owner, models.Watch.active))
    assert active == watchlist.MAX_WATCHES_PER_OWNER
    assert len(errors) == 40 - watchlist.MAX_WATCHES_PER_OWNER


def test_concurrent_creates_never_pass_the_connection_cap(store, monkeypatch):
    monkeypatch.setattr(config, "WATCHES_PER_CLIENT", 5)
    barrier = threading.Barrier(12)

    def make(i):
        barrier.wait()
        try:
            watchlist.create_watch(ownership.owner_hash(f"{i:032d}"), "0x" + f"{6000 + i:040x}", "ethereum",
                                   "ETH", client="10.0.0.66")
        except watchlist.WatchError:
            pass
    threads = [threading.Thread(target=make, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with models.session() as s:
        assert s.scalar(select(func.count()).select_from(models.Watch).where(models.Watch.active)) == 5
