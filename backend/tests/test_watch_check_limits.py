"""'Check now' on a watch is bounded (routes/watches.py check_now).

A manual check reads the provider fresh, past the cache, and on the free host
it is the only way watches are checked at all (EXCHEQUER_WATCHER=0). It had
only a one-minute cooldown per watch: anyone could make 25 watches per free
owner key and check each every minute, for ever, and two simultaneous clicks
on one watch both reached the provider. Now each connection and the site as a
whole have a per-minute allowance, and a watch already being checked is not
checked again in parallel.
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import models, ownership, rate_limit, watchlist
from app.main import app
from app.routes import watches as watch_routes

KEY = "k" * 32


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'w.db'}", future=True))
    models.init_db()
    calls = []
    monkeypatch.setattr(watchlist, "check_watch", lambda watch_id, *a, **k: calls.append(watch_id) or 0)
    monkeypatch.setattr(watch_routes, "checks_per_client", rate_limit.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(watch_routes, "checks_total", rate_limit.SlidingWindowLimiter(100, 60))
    c = TestClient(app)
    c.calls = calls
    return c


def watches(n: int) -> list[str]:
    owner = ownership.owner_hash(KEY)
    return [watchlist.create_watch(owner, "0x" + f"{i + 1:040x}", "ethereum", "ETH").id for i in range(n)]


def check(client, watch_id):
    return client.post(f"/watches/{watch_id}/check", headers={ownership.OWNER_HEADER: KEY})


def test_one_connection_gets_a_per_minute_allowance(client, monkeypatch):
    monkeypatch.setattr(watch_routes, "checks_per_client", rate_limit.SlidingWindowLimiter(3, 60))
    ids = watches(4)
    assert [check(client, w).status_code for w in ids[:3]] == [200, 200, 200]
    limited = check(client, ids[3])
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    assert len(client.calls) == 3


def test_the_site_as_a_whole_has_a_per_minute_ceiling(client, monkeypatch):
    monkeypatch.setattr(watch_routes, "checks_total", rate_limit.SlidingWindowLimiter(2, 60))
    ids = watches(3)
    assert [check(client, w).status_code for w in ids] == [200, 200, 429]
    assert "this site" in check(client, ids[2]).json()["detail"].lower()


def test_a_watch_being_checked_is_not_checked_again_in_parallel(client, monkeypatch):
    (watch_id,) = watches(1)
    inside, finish = threading.Event(), threading.Event()

    def slow(wid, *a, **k):
        client.calls.append(wid)
        inside.set()
        finish.wait(5)
        return 0
    monkeypatch.setattr(watchlist, "check_watch", slow)
    first = []
    t = threading.Thread(target=lambda: first.append(check(client, watch_id).status_code))
    t.start()
    assert inside.wait(5)
    second = check(client, watch_id)
    finish.set()
    t.join(5)
    assert first == [200]
    assert second.status_code == 429 and "being checked" in second.json()["detail"]
    assert client.calls == [watch_id]


def test_a_site_wide_refusal_does_not_use_up_the_clients_allowance(client, monkeypatch):
    per_client = rate_limit.SlidingWindowLimiter(5, 60)
    monkeypatch.setattr(watch_routes, "checks_per_client", per_client)
    monkeypatch.setattr(watch_routes, "checks_total", rate_limit.SlidingWindowLimiter(1, 60))
    ids = watches(2)
    assert [check(client, w).status_code for w in ids] == [200, 429]
    assert per_client.remaining("testclient") == 4  # only the check that ran was counted


def test_a_click_racing_a_finishing_check_is_still_cooled_down(client, monkeypatch):
    # The cooldown was read before the lock: a click that read it just before
    # another check finished went on to read the provider again.
    (watch_id,) = watches(1)
    answers = iter([None, 5.0])
    monkeypatch.setattr(watchlist, "seconds_since_check", lambda w: next(answers, 5.0))
    r = check(client, watch_id)
    assert r.status_code == 429 and client.calls == []
