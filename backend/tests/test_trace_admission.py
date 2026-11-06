"""Who may start a trace now (app/routes/cases.py admit/release).

The server runs at most TRACE_MAX_RUNNING traces. One connection used to be
able to hold every one of those slots for as long as its traces ran, and a
visitor turned away because the server was full was still charged a trace
from their hourly allowance. Now one connection holds at most
TRACES_RUNNING_PER_CLIENT slots, and the allowance is charged only once a
slot is actually taken.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import config, rate_limit
from app.routes import cases


def http(ip: str) -> SimpleNamespace:
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(config, "TRACE_MAX_RUNNING", 4)
    monkeypatch.setattr(config, "TRACES_RUNNING_PER_CLIENT", 2)
    monkeypatch.setattr(cases, "_running", threading.BoundedSemaphore(4))
    monkeypatch.setattr(cases, "_running_by_client", {})
    monkeypatch.setattr(rate_limit, "traces", rate_limit.SlidingWindowLimiter(30, 3600))


def refused(ip: str) -> HTTPException:
    with pytest.raises(HTTPException) as exc:
        cases.admit(http(ip))
    assert exc.value.status_code == 429
    return exc.value


def test_one_connection_cannot_take_every_slot():
    slots = [cases.admit(http("10.0.0.1")) for _ in range(2)]
    assert "this connection" in refused("10.0.0.1").detail.lower()
    # The other two slots are still there for everyone else.
    other = [cases.admit(http("10.0.0.2")), cases.admit(http("10.0.0.3"))]
    for slot in slots + other:
        cases.release(slot)


def test_a_finished_trace_gives_the_connection_its_slot_back():
    first = cases.admit(http("10.0.0.1"))
    second = cases.admit(http("10.0.0.1"))
    cases.release(first)
    third = cases.admit(http("10.0.0.1"))
    for slot in (second, third):
        cases.release(slot)
    assert cases._running_by_client == {}


def test_being_turned_away_while_the_server_is_full_costs_nothing(monkeypatch):
    monkeypatch.setattr(rate_limit, "traces", rate_limit.SlidingWindowLimiter(3, 3600))
    busy = [cases.admit(http(f"10.0.1.{i}")) for i in range(4)]
    for _ in range(5):
        assert "already running" in refused("10.0.0.9").detail
    for slot in busy:
        cases.release(slot)
    # All three of this connection's hourly traces are still there.
    slots = [cases.admit(http("10.0.0.9")) for _ in range(2)]
    cases.release(slots[0])
    slots.append(cases.admit(http("10.0.0.9")))
    for slot in slots[1:]:
        cases.release(slot)


def test_over_the_hourly_limit_gives_the_slot_straight_back(monkeypatch):
    monkeypatch.setattr(rate_limit, "traces", rate_limit.SlidingWindowLimiter(1, 3600))
    cases.release(cases.admit(http("10.0.0.1")))
    assert "in the last hour" in refused("10.0.0.1").detail
    # Neither the server-wide slot nor the connection's count leaked.
    assert cases._running_by_client == {}
    slots = [cases.admit(http(f"10.0.2.{i}")) for i in range(4)]
    for slot in slots:
        cases.release(slot)
