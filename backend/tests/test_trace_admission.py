"""Who may start a trace now (app/routes/cases.py admit/release).

The server runs at most TRACE_MAX_RUNNING traces. One connection used to be
able to hold every one of those slots for as long as its traces ran, and a
visitor turned away because the server was full was still charged a trace
from their hourly allowance. Now one connection holds at most
TRACES_RUNNING_PER_CLIENT slots, and the allowance is charged only once a
slot is actually taken.

Two connections (or one and its batch) could still fill every slot and keep
re-filling them (8 Nov check). Now the last free slot is only for a
connection with nothing running, and a connection may hold slots for
TRACE_SLOT_MINUTES_PER_HOUR in any hour.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import config, rate_limit
from app.routes import batches as batch_routes
from app.routes import cases


def http(ip: str) -> SimpleNamespace:
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(config, "TRACE_MAX_RUNNING", 4)
    monkeypatch.setattr(config, "TRACES_RUNNING_PER_CLIENT", 2)
    monkeypatch.setattr(config, "TRACE_RESERVED_SLOTS", 1)
    monkeypatch.setattr(config, "TRACE_SLOT_MINUTES_PER_HOUR", 20)
    monkeypatch.setattr(cases, "_running", threading.BoundedSemaphore(4))
    monkeypatch.setattr(cases, "_running_by_client", {})
    monkeypatch.setattr(cases, "_slot_clock", cases.SlotClock())
    monkeypatch.setattr(batch_routes, "_batch_slots", threading.BoundedSemaphore(1))
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


def test_two_connections_and_a_batch_leave_a_slot_for_a_newcomer():
    """The 8 Nov probe: one connection's two traces, its batch row and one
    trace from a second connection held all four slots, and a presenter got
    "4 traces are already running". The last free slot is now only for a
    connection with nothing running."""
    attacker = [cases.admit(http("10.0.0.66")), cases.admit(http("10.0.0.66"))]
    assert "this connection" in refused("10.0.0.66").detail.lower()
    # Its batch row would take the last slot but one: refused, it waits.
    assert batch_routes._acquire("10.0.0.66") is False
    second = cases.admit(http("10.0.0.77"))
    # The second connection may not take the last slot either.
    assert "kept for someone" in refused("10.0.0.77").detail
    presenter = cases.admit(http("10.0.0.5"))
    for slot in attacker + [second, presenter]:
        cases.release(slot)
    assert cases._running_by_client == {}


def test_a_batch_row_counts_against_its_connection():
    assert batch_routes._acquire("10.0.0.8") is True
    cases.admit(http("10.0.0.8"))  # one live trace beside the batch row
    assert "this connection" in refused("10.0.0.8").detail.lower()
    cases.release("10.0.0.8")
    batch_routes._release("10.0.0.8")
    assert cases._running_by_client == {}


def test_a_connection_that_held_slots_for_its_minutes_waits(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(cases, "_slot_clock", cases.SlotClock(clock=lambda: now[0]))
    slot = cases.admit(http("10.0.0.1"))
    now[0] += 19 * 60
    second = cases.admit(http("10.0.0.1"))  # 19 minutes held so far: still allowed
    now[0] += 60
    cases.release(slot)
    cases.release(second)
    assert "minutes in the last hour" in refused("10.0.0.1").detail
    cases.release(cases.admit(http("10.0.0.2")))  # another connection is not affected
    now[0] += 3600  # an hour later the minutes have run out of the window
    cases.release(cases.admit(http("10.0.0.1")))


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
