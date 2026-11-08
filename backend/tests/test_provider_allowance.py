"""The site's provider allowance per UTC day (r1-providers-2, the period part).

A case's request budget bounds one trace, not a burst of them: 30 traces an
hour from one connection, 120 from the site, plus watch checks and warm-ups,
could still spend Etherscan's 100k calls or NodeReal's month in hours. One
meter per provider credential now counts every network request in the
process, trace or not, refuses past the day's allowance (and past one
connection's share of it), and /health/detail shows what was spent.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import api_budget, config, pipeline
from app.api_budget import BudgetSpent, TraceBudget, UnitMeter
from app.etherscan_client import EtherscanClient
from app.pipeline import TraceRequest, run_trace

from test_request_budget import SEED, _etherscan

KEY = "k"


def _meter() -> UnitMeter:
    return api_budget.get_meter("etherscan", api_budget.credential(KEY))


def test_the_meter_starts_again_at_midnight_utc():
    now = [86400 * 20_000 + 86_000.0]  # 23:53 UTC
    meter = UnitMeter("etherscan", 3, clock=lambda: now[0])
    for _ in range(3):
        assert meter.charge(1) is None
    assert meter.charge(1) == "site" and meter.spent()
    assert 0 < meter.seconds_to_reset() <= 401
    now[0] += 500  # 00:01 UTC
    assert not meter.spent() and meter.charge(1) is None
    assert meter.stats()["used"] == 1


def test_one_connection_may_spend_only_its_share():
    meter = UnitMeter("etherscan", 100, client_share=0.25)
    for _ in range(25):
        assert meter.charge(1, client="a") is None
    assert meter.charge(1, client="a") == "client"
    assert meter.charge(1, client="b") is None  # another connection still traces
    assert meter.charge(1) is None  # and a watch check (no connection) too


def test_a_read_outside_any_trace_still_counts(monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 1000)
    calls: list = []
    client = _etherscan(calls)  # no budget: a watch check, a script
    client.get_outgoing_transactions(SEED)
    assert _meter().stats()["used"] == len(calls) == 1


def test_a_spent_allowance_refuses_the_request_without_sending_it(monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 1)
    calls: list = []
    client = _etherscan(calls)
    client.get_outgoing_transactions(SEED)
    with pytest.raises(BudgetSpent) as exc:
        client.get_outgoing_transactions("0x" + "77" * 20)
    assert exc.value.scope == "site" and len(calls) == 1


@pytest.fixture
def etherscan_source(monkeypatch):
    calls: list = []

    @contextmanager
    def open_source(chain, asset):
        client = EtherscanClient(api_key=KEY, chain_id=1, min_interval=0.0, include_internal=False,
                                 client=_etherscan(calls)._client)
        yield client
    monkeypatch.setattr(pipeline, "open_source", open_source)
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", KEY)
    return calls


def test_a_new_trace_is_refused_once_the_day_is_spent(etherscan_source, monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 5)
    for _ in range(5):
        _meter().charge(1)
    with pytest.raises(HTTPException) as exc:
        run_trace(TraceRequest(address=SEED, chain="ethereum", follow_swaps=False))
    assert exc.value.status_code == 503
    assert "allowance for this site is used up" in exc.value.detail and "00:00 UTC" in exc.value.detail
    assert int(exc.value.headers["Retry-After"]) > 0
    assert etherscan_source == []


def test_a_trace_running_into_the_days_end_stops_and_says_so(etherscan_source, monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 8)
    r = run_trace(TraceRequest(address=SEED, chain="ethereum", max_depth=6, follow_swaps=False),
                  budget=TraceBudget(60, 10))
    assert len(etherscan_source) <= 8
    assert r["stopped_by"] == "budget"
    assert any("Etherscan allowance for this site today reached" in t for t in r["truncation_reasons"])


def test_a_connection_past_its_share_is_told_so(etherscan_source, monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 100)
    monkeypatch.setattr(config, "PROVIDER_CLIENT_SHARE_PERCENT", 1)  # one request each
    _meter().charge(1, client="1.2.3.4")
    with pytest.raises(HTTPException) as exc:
        run_trace(TraceRequest(address=SEED, chain="ethereum", follow_swaps=False),
                  budget=TraceBudget(60, 10, client="1.2.3.4"))
    assert exc.value.status_code == 429 and "share of today's Etherscan allowance" in exc.value.detail


def test_health_detail_shows_the_days_spend_and_never_the_key(monkeypatch):
    monkeypatch.setattr(config, "HEALTH_TOKEN", "t" * 32)
    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 1000)
    secret = "SECRETKEY123"
    api_budget.get_meter("etherscan", api_budget.credential(secret)).charge(3)
    with TestClient(pipeline_app()) as client:
        body = client.get("/health/detail", headers={"authorization": "Bearer " + "t" * 32}).json()
    meters = body["api_budget"]["meters"]
    (name, meter), = [(n, m) for n, m in meters.items() if n.startswith("etherscan:")]
    assert meter["used"] == 3 and meter["limit"] == 1000 and meter["resets_at"].endswith("Z")
    assert secret not in str(body)


def test_a_batch_on_a_spent_chain_is_refused_before_it_starts(monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", KEY)
    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 1)
    _meter().charge(1)
    with TestClient(pipeline_app()) as client:
        r = client.post("/batches", json={"rows": [{"address": SEED, "chain": "ethereum"}]},
                        headers={"x-exchequer-owner": "o" * 43})
    assert r.status_code == 503 and "allowance" in r.json()["detail"]


def pipeline_app():
    from app.main import app
    return app


def test_to_a_script_a_spent_allowance_is_a_quota_error(monkeypatch):
    # Importers catch EtherscanError per address and read the answer as unknown.
    from app.etherscan_client import ProviderQuotaError

    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 1)
    _meter().charge(1)
    with pytest.raises(ProviderQuotaError):
        _etherscan([]).get_outgoing_transactions(SEED)


# -- the day's count survives a restart (8 Nov check) ----------------------------
@pytest.fixture
def stored_meters(tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    from app import models
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'm.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(config, "PERSIST_METERS", True)
    monkeypatch.setattr(config, "METER_SAVE_SECONDS", 30)
    monkeypatch.setattr(config, "ETHERSCAN_CALLS_PER_DAY", 100)
    monkeypatch.setattr(config, "PROVIDER_CLIENT_SHARE_PERCENT", 25)
    api_budget.reset()
    yield models
    api_budget.reset()


def restart() -> None:
    """What the free host does after 15 idle minutes: the process, and every count in memory, is gone."""
    api_budget.flush_meters()
    api_budget.reset()


def test_a_restart_does_not_start_the_day_again(stored_meters):
    """The probe: the site ceiling lived only in memory, so each wake of the
    free instance began the day at zero and the month could be drained a day's
    allowance per wake."""
    for _ in range(100):
        api_budget.spend("etherscan", api_budget.credential(KEY), 1, None)
    restart()
    with pytest.raises(BudgetSpent) as stopped:
        api_budget.spend("etherscan", api_budget.credential(KEY), 1, None)
    assert stopped.value.scope == "site"
    assert _meter().stats()["used"] == 100


def test_a_connections_share_survives_a_restart_too(stored_meters):
    budget = TraceBudget(60, 0, client="10.0.0.66")
    for _ in range(25):
        api_budget.spend("etherscan", api_budget.credential(KEY), 1, budget)
    restart()
    with pytest.raises(BudgetSpent) as stopped:
        api_budget.spend("etherscan", api_budget.credential(KEY), 1, TraceBudget(60, 0, client="10.0.0.66"))
    assert stopped.value.scope == "client"
    api_budget.spend("etherscan", api_budget.credential(KEY), 1, TraceBudget(60, 0, client="10.0.0.5"))
    # The store keeps a hash of each connection, never its address.
    with stored_meters.session() as s:
        row = s.query(stored_meters.ProviderMeter).one()
    assert "10.0.0" not in row.clients_json and row.used >= 25


def test_the_watch_part_survives_a_restart(stored_meters, monkeypatch):
    monkeypatch.setattr(config, "WATCH_SHARE_PERCENT", 20)
    api_budget.reset()
    with api_budget.charged_to(None, watch=True):
        for _ in range(20):
            api_budget.spend("etherscan", api_budget.credential(KEY), 1, None)
    restart()
    with api_budget.charged_to(None, watch=True), pytest.raises(BudgetSpent) as stopped:
        api_budget.spend("etherscan", api_budget.credential(KEY), 1, None)
    assert stopped.value.scope == "watch"


def test_the_count_is_written_at_most_every_few_seconds(stored_meters, monkeypatch):
    writes = []
    real = api_budget._store_meter
    monkeypatch.setattr(api_budget, "_store_meter", lambda *a: writes.append(1) or real(*a))
    now = [1_800_000_000.0]
    meter = UnitMeter("etherscan", 1000, clock=lambda: now[0], name="etherscan:test")
    for _ in range(50):
        meter.charge(1)
        meter.save_if_due()
    assert writes == []
    now[0] += 31
    meter.charge(1)
    meter.save_if_due()
    assert len(writes) == 1


def test_a_store_that_cannot_be_reached_leaves_the_meter_counting(monkeypatch):
    from app import models
    from sqlalchemy import create_engine
    monkeypatch.setattr(config, "PERSIST_METERS", True)
    monkeypatch.setattr(models, "_engine", create_engine("sqlite:////nonexistent/dir/x.db", future=True))
    api_budget.reset()
    meter = _meter()  # the read fails: memory only
    assert meter.charge(1) is None
    meter.save_if_due(force=True)  # so does the write, quietly
    assert meter.stats()["used"] == 1
    api_budget.reset()


def test_the_store_never_lowers_a_count_another_process_wrote(stored_meters):
    day = int(__import__("time").time() // 86400)
    assert api_budget._store_meter("etherscan:x", {"day": day, "used": 50, "requests": 50, "refused": 0,
                                                   "shares": {}})
    assert api_budget._store_meter("etherscan:x", {"day": day, "used": 10, "requests": 10, "refused": 0,
                                                   "shares": {}})
    with stored_meters.session() as s:
        assert s.get(stored_meters.ProviderMeter, ("etherscan:x", day)).used == 50


def test_a_meter_takes_up_the_stored_count_once_it_can_write(stored_meters, monkeypatch):
    """A meter made while the store was unreachable starts at zero; its first
    write that succeeds also reads back what the store held."""
    day = int(__import__("time").time() // 86400)
    name = f"etherscan:{api_budget.credential(KEY)}"
    assert api_budget._store_meter(name, {"day": day, "used": 90, "requests": 90, "refused": 0, "shares": {}})
    with monkeypatch.context() as m:
        m.setattr(api_budget, "_load_meter", lambda meter: None)
        meter = _meter()  # as if the read had failed
    assert meter.stats()["used"] == 0
    meter.charge(1)
    meter.save_if_due(force=True)
    assert meter.stats()["used"] == 90  # never below the stored count
