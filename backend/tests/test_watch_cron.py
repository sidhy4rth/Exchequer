"""Scheduled watch checks (POST /watches/check-due, .github/workflows/watch-cron.yml).

Render's free instance sleeps after 15 idle minutes, and the in-process
watcher sleeps with it, so on the live site a watch was checked only when
someone pressed Check now. A GitHub Actions schedule now calls
/watches/check-due every 15 minutes: the call wakes the instance and checks a
bounded batch of the watches that are due, oldest first, inside the part of
the day's provider allowance kept for watch checks. Alerts go where they
always did: the app, and the watch's webhook.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import api_budget, audit, config, models, watchlist
from app.main import app
from test_watchlist import ALICE, BINANCE_14, STRANGER, FakeChain, later, owner, tx

TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def cron(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(watchlist, "chain_head", lambda *a, **k: None)  # never a real provider
    monkeypatch.setattr(config, "WATCH_CRON_TOKEN", TOKEN)
    monkeypatch.setattr(watchlist, "_pause", lambda seconds: None)
    monkeypatch.setattr(watchlist, "_last_cron_call", None)  # no scheduled call seen yet
    c = TestClient(app)
    c.chain, c.checked = FakeChain(), []
    c.source = c.chain
    real = watchlist.check_watch

    def spy(watch_id, *a, **k):
        c.checked.append(watch_id)
        return real(watch_id, *a, source=c.source, **k)
    monkeypatch.setattr(watchlist, "check_watch", spy)
    return c


def make(n: int, hook: str | None = None, case_id: str | None = None, who: str = ALICE) -> list[str]:
    return [watchlist.create_watch(owner(who), "0x" + f"{i + 1:040x}", "ethereum", "ETH",
                                   webhook_url=hook, case_id=case_id).id for i in range(n)]


def checked_at(watch_id: str, iso: str | None) -> None:
    with models.session() as s:
        s.get(models.Watch, watch_id).last_checked_at = iso
        s.commit()


def test_without_the_token_set_the_endpoint_is_not_there(cron, monkeypatch):
    monkeypatch.setattr(config, "WATCH_CRON_TOKEN", "")
    assert cron.post("/watches/check-due", headers=AUTH).status_code == 404
    assert cron.checked == []


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN},
                                     {"Authorization": f"Basic {TOKEN}"}])
def test_anything_but_the_exact_bearer_token_is_refused(cron, headers):
    make(1)
    assert cron.post("/watches/check-due", headers=headers).status_code == 401
    assert cron.checked == []


def test_the_token_is_compared_in_constant_time():
    import inspect

    from app.routes import watches as watch_routes
    assert "compare_digest" in inspect.getsource(watch_routes._cron_authorised)


def test_a_batch_is_bounded_and_says_when_the_next_watch_is_due(cron, monkeypatch):
    monkeypatch.setattr(config, "WATCH_CRON_BATCH", 3)
    ids = make(5)
    body = cron.post("/watches/check-due", headers=AUTH).json()
    assert body["checked"] == 3 and len(cron.checked) == 3
    assert body["alerts"] == 0 and body["skipped_budget"] == 0
    assert body["next_due"] <= models.utc_now_iso()  # two are still due now
    second = cron.post("/watches/check-due", headers=AUTH).json()
    assert second["checked"] == 2 and set(cron.checked) == set(ids)
    assert second["next_due"] > models.utc_now_iso()  # nothing left until the interval passes
    assert cron.post("/watches/check-due", headers=AUTH).json()["checked"] == 0


def test_with_no_watch_there_is_no_next_check(cron):
    body = cron.post("/watches/check-due", headers=AUTH).json()
    assert body == {"checked": 0, "alerts": 0, "skipped_budget": 0, "next_due": None}


def test_never_checked_watches_go_first_then_the_longest_unchecked(cron, monkeypatch):
    monkeypatch.setattr(config, "WATCH_CRON_BATCH", 3)
    a, b, c, d = make(4)
    checked_at(a, "2026-01-01T00:00:10+00:00")
    checked_at(b, "2026-01-01T00:00:05+00:00")
    checked_at(d, models.utc_now_iso())  # just checked: not due
    cron.post("/watches/check-due", headers=AUTH)
    assert cron.checked == [c, b, a]


def test_alerts_reach_the_app_and_the_webhook(cron, monkeypatch):
    posted = []
    monkeypatch.setattr(watchlist, "post_webhook", lambda url, payload: posted.append(payload))
    (w,) = make(1, hook="https://hooks.slack.com/services/T000/B000/secret")
    cron.chain.transfers = [tx(100, STRANGER)]
    cron.post("/watches/check-due", headers=AUTH)  # the baseline
    checked_at(w, "2026-01-01T00:00:00+00:00")  # due again
    cron.chain.transfers = [tx(100, STRANGER), tx(101, BINANCE_14, 4.0, ts=later())]
    body = cron.post("/watches/check-due", headers=AUTH).json()
    assert body["checked"] == 1 and body["alerts"] == 1
    assert [a["kind"] for a in watchlist.list_alerts(owner(ALICE))] == ["exchange"]
    assert len(posted) == 1 and "Binance" in posted[0]["text"]


def test_each_check_is_audit_recorded(cron, monkeypatch):
    calls = []
    real = audit.record
    monkeypatch.setattr(audit, "record", lambda event, **k: (real(event, **k), calls.append((event, k)))[0])
    a, b = make(2)
    cron.post("/watches/check-due", headers=AUTH)
    assert [(e, k["detail"]["watch_id"]) for e, k in calls] == [("watch.check", a), ("watch.check", b)]
    assert all(k["detail"]["trigger"] == "schedule" and k["detail"]["result"] == "checked" for _, k in calls)


def test_a_check_on_a_case_wallet_is_recorded_against_that_case(cron, monkeypatch):
    """So the case's own audit trail shows the scheduled checks of its wallets."""
    calls = []
    monkeypatch.setattr(audit, "record", lambda event, **k: calls.append(k))
    case = "c" * 36
    make(1, case_id=case)
    cron.post("/watches/check-due", headers=AUTH)
    assert [k.get("case_id") for k in calls] == [case]


def test_a_spent_watch_allowance_skips_the_rest_and_costs_nothing_more(cron, monkeypatch):
    """The watch part of the day is the bound: once it is used up the batch
    reads nothing more, and each watch it could not read says why."""
    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 100)
    monkeypatch.setattr(config, "WATCH_SHARE_PERCENT", 2)  # two reads for watches today
    api_budget.reset()
    reads = []

    def metered(chain_cfg, asset):
        @contextmanager
        def client():
            class C:
                def get_outgoing_transactions(self, address, limit=None):
                    api_budget.spend("etherscan", "k", 1, None)
                    reads.append(address)
                    return []
            yield C()
        return client()
    cron.source = metered
    ids = make(4)
    body = cron.post("/watches/check-due", headers=AUTH).json()
    assert body["checked"] == 2 and body["skipped_budget"] == 2 and len(reads) == 2
    errors = {w["watch_id"]: w["last_error"] for w in watchlist.list_watches(owner(ALICE))}
    assert errors[ids[0]] is None and "watch checks" in errors[ids[3]]


def test_a_scheduled_check_does_not_need_the_demo_code(cron, monkeypatch):
    """The token is its own guard; the job holds no demo code."""
    monkeypatch.setattr(config, "DEMO_CODE", "c" * 30)
    make(1)
    assert cron.post("/watches/check-due", headers=AUTH).status_code == 200


def test_the_token_alone_promises_nothing_until_a_scheduled_call_arrives(cron):
    """The token can be set (render.yaml generates it) long before the job
    runs, or after GitHub pauses it: the watchlist says automatic checks are
    on only while scheduled calls are actually arriving."""
    assert config.WATCHER_ENABLED is False
    assert cron.get("/watches").json()["watcher"]["enabled"] is False
    cron.post("/watches/check-due", headers=AUTH)
    body = cron.get("/watches").json()["watcher"]
    assert body["enabled"] is True and body["interval_seconds"] == watchlist.CRON_INTERVAL_SECONDS


def test_a_job_that_stopped_calling_no_longer_counts(cron, monkeypatch):
    cron.post("/watches/check-due", headers=AUTH)
    monkeypatch.setattr(watchlist, "_last_cron_call",
                        watchlist._last_cron_call - 2 * watchlist.CRON_INTERVAL_SECONDS - 1)
    assert cron.get("/watches").json()["watcher"]["enabled"] is False


def test_a_refused_call_is_no_evidence_the_job_runs(cron):
    cron.post("/watches/check-due", headers={"Authorization": "Bearer wrong"})
    assert cron.get("/watches").json()["watcher"]["enabled"] is False


def test_more_watches_than_one_batch_lengthen_the_promised_interval(cron, monkeypatch):
    """Ten watches a call, a call every 15 minutes: with 25 watches each is
    checked about every 45 minutes, and the watchlist must say so, and call
    the checks stale only after three of those."""
    monkeypatch.setattr(config, "WATCH_CRON_BATCH", 10)
    make(25)
    cron.post("/watches/check-due", headers=AUTH)
    body = cron.get("/watches", headers={"X-Exchequer-Owner": ALICE}).json()["watcher"]
    # The watchlist rounds three calls up to four (see the next test); the
    # operator's /health/detail gives the exact figure.
    assert body["interval_seconds"] == 4 * watchlist.CRON_INTERVAL_SECONDS
    assert watchlist.watcher_status()["interval_seconds"] == 3 * watchlist.CRON_INTERVAL_SECONDS
    assert watchlist.schedule() == (True, 3 * watchlist.CRON_INTERVAL_SECONDS)


def _shown(cron, headers=None) -> int:
    cron.post("/watches/check-due", headers=AUTH)
    return cron.get("/watches", headers=headers or {}).json()["watcher"]["interval_seconds"]


def test_the_watchlist_does_not_tell_a_stranger_how_many_watches_the_site_has(cron, monkeypatch):
    """GET /watches is open to anyone. Its interval must not be a count of
    every active watch on the site to within one batch: with no owner key it
    leaves the backlog out, and with one it gives the backlog only to within
    a factor of two (15, 30, 60, 120 minutes and so on)."""
    monkeypatch.setattr(config, "WATCH_CRON_BATCH", 10)
    make(25)
    assert _shown(cron) == watchlist.CRON_INTERVAL_SECONDS
    mine = {"X-Exchequer-Owner": ALICE}
    shown = {_shown(cron, mine)}
    make(10, who="b" * 32)  # 35 watches: four calls, the same bucket as three
    shown.add(_shown(cron, mine))
    assert shown == {4 * watchlist.CRON_INTERVAL_SECONDS}
    make(10, who="c" * 32)  # 45 watches: five calls, the next bucket up
    assert _shown(cron, mine) == 8 * watchlist.CRON_INTERVAL_SECONDS
    assert _shown(cron) == watchlist.CRON_INTERVAL_SECONDS


def test_the_rounding_never_shortens_the_interval_or_touches_the_in_process_watcher(monkeypatch):
    for calls in range(1, 40):
        exact = calls * watchlist.CRON_INTERVAL_SECONDS
        assert exact <= watchlist.rounded_interval(exact) < 2 * exact
    monkeypatch.setattr(config, "WATCHER_ENABLED", True)
    assert watchlist.schedule(backlog="rounded") == (True, config.WATCH_INTERVAL_SECONDS)
