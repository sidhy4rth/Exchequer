"""A background trace job no page is watching (EXCHEQUER_JOB_STOP_UNWATCHED, #302).

A job whose tab was closed used to run to the end and save a case nobody saw.
With the flag on, once its last progress stream closes a clock starts; a job
still unwatched after config.JOB_UNWATCHED_GRACE_SECONDS stops as a Stop
stops it, keeps nothing and is audited as abandoned. A reload (a new stream)
or a status poll inside the grace keeps it going. With the flag off nothing
changes. The clock and the timer are faked: no test waits out a grace.
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import api_budget, audit, config, models, ownership, pipeline
from app.main import app
from app.routes import cases
from app.routes import jobs as job_routes

OWNER = "o" * 32
ADDR = "0x" + "2" * 40
GRACE = config.JOB_UNWATCHED_GRACE_SECONDS
REAL_SCHEDULE = job_routes._schedule


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A client, a fake clock and the timers the routes asked for (not yet run)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'cases.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    monkeypatch.setattr(cases, "_running", threading.BoundedSemaphore(2))
    monkeypatch.setattr(job_routes, "_streams", {})
    # A stream ends by itself at once, as one whose tab closed does.
    monkeypatch.setattr(job_routes, "STREAM_MAX_SECONDS", 0.05)
    clock, timers = Clock(), []
    monkeypatch.setattr(job_routes, "_clock", clock)
    monkeypatch.setattr(job_routes, "_schedule", lambda delay, callback: timers.append((delay, callback)))
    recorded, real = [], audit.record

    def record(event, *, case_id=None, detail=None):
        real(event, case_id=case_id, detail=detail)
        recorded.append((event, detail))
    monkeypatch.setattr(audit, "record", record)
    saved, real_store = [], cases.store_result

    def store_result(payload, *a, **k):
        saved.append(payload)
        return real_store(payload, *a, **k)
    monkeypatch.setattr(cases, "store_result", store_result)
    with TestClient(app) as client:
        yield client, clock, timers, recorded, saved


def start(client, monkeypatch, go):
    """A trace that reads (and checks for a stop) until `go`, then returns whole."""
    def trace(request, seed_window=None, budget=None):
        budget = budget or api_budget.current_budget()
        for _ in range(250):
            if go.is_set():
                return {"address": request.address, "chain": "ethereum", "exchange": "Binance"}
            budget.sleep(0.02)
        raise AssertionError("never released")
    monkeypatch.setattr(pipeline, "run_trace", trace)
    return client.post("/trace/jobs", json={"address": ADDR}, headers={ownership.OWNER_HEADER: OWNER}).json()["job_id"]


def close_a_stream(client, job_id):
    with client.stream("GET", f"/trace/jobs/{job_id}/events") as stream:
        assert stream.status_code == 200
        "".join(stream.iter_text())


def run_timers(timers):
    due, timers[:] = list(timers), []
    for _, callback in due:
        callback()


def wait_done(client, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        body = client.get(f"/trace/jobs/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def slots_free():
    return cases._running.acquire(blocking=False) and cases._running.acquire(blocking=False)


def test_a_job_nobody_watches_after_its_stream_closed_stops_and_keeps_nothing(env, monkeypatch):
    client, clock, timers, recorded, saved = env
    monkeypatch.setattr(config, "JOB_STOP_UNWATCHED", True)
    go = threading.Event()
    job_id = start(client, monkeypatch, go)
    close_a_stream(client, job_id)  # the tab closes
    assert [delay for delay, _ in timers] == [GRACE]
    clock.now += GRACE - 1
    run_timers(timers)  # early (a timer may run late, never early; this checks the clock all the same)
    assert not job_routes.jobs.store.get(job_id).budget.cancelled
    assert [delay for delay, _ in timers] == [pytest.approx(1)]
    clock.now += 1
    run_timers(timers)
    go.set()  # even a trace that returns after the stop is not kept
    job = wait_done(client, job_id)
    assert job["status"] == "failed" and job["error"] == {"status_code": 409, "detail": cases.ABANDONED_DETAIL}
    assert job["case_id"] is None and saved == []
    assert client.get("/cases", headers={ownership.OWNER_HEADER: OWNER}).json()["cases"] == []
    assert slots_free()
    abandoned = [d for e, d in recorded if e == "case.trace_abandoned"]
    assert abandoned == [{"chain": None, "asset": None, "direction": "outgoing", "mode": "address",
                          "stopped_by": "client_disconnected", "saved": False}]
    assert not [e for e, _ in recorded if e in ("case.trace", "case.trace_stopped")]


def test_a_reload_inside_the_grace_reattaches_and_the_job_is_saved(env, monkeypatch):
    client, clock, timers, recorded, saved = env
    monkeypatch.setattr(config, "JOB_STOP_UNWATCHED", True)
    monkeypatch.setattr(job_routes, "STREAM_MAX_SECONDS", 900.0)
    go = threading.Event()
    job_id = start(client, monkeypatch, go)
    job_routes._streams[job_id] = {"old": time.monotonic()}  # the stream from before the reload
    job = job_routes.jobs.store.get(job_id)
    job_routes._close_stream(job_id, "old")
    job_routes._unwatched(job)  # what the stream's end does
    assert len(timers) == 1
    reloaded = threading.Thread(target=close_a_stream, args=(client, job_id))
    reloaded.start()  # the reloaded page's stream, open until the job ends
    deadline = time.monotonic() + 2
    while not job_routes._streams.get(job_id) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert job_routes._streams.get(job_id)
    clock.now += 2 * GRACE
    run_timers(timers)
    assert not job.budget.cancelled and timers == []  # watched: no stop, no new timer
    go.set()
    reloaded.join(3)
    assert wait_done(client, job_id)["status"] == "done"
    assert len(saved) == 1 and timers == []  # a stream that ends with its job starts no clock
    assert not [e for e, _ in recorded if e == "case.trace_abandoned"]


def test_a_page_that_polls_after_its_stream_closed_keeps_the_job(env, monkeypatch):
    client, clock, timers, _, saved = env
    monkeypatch.setattr(config, "JOB_STOP_UNWATCHED", True)
    go = threading.Event()
    job_id = start(client, monkeypatch, go)
    close_a_stream(client, job_id)
    clock.now += GRACE - 5
    client.get(f"/trace/jobs/{job_id}")  # the page's polling fallback
    clock.now += 5
    run_timers(timers)
    assert not job_routes.jobs.store.get(job_id).budget.cancelled
    assert [delay for delay, _ in timers] == [pytest.approx(GRACE - 5)]  # counts from the poll
    go.set()
    assert wait_done(client, job_id)["status"] == "done" and len(saved) == 1


def test_a_job_whose_client_never_opened_a_stream_is_never_stopped(env, monkeypatch):
    client, clock, timers, _, saved = env
    monkeypatch.setattr(config, "JOB_STOP_UNWATCHED", True)
    go = threading.Event()
    job_id = start(client, monkeypatch, go)
    clock.now += 10 * GRACE
    client.get(f"/trace/jobs/{job_id}")
    assert timers == [] and job_routes.jobs.store.get(job_id).unwatched_since is None
    go.set()
    assert wait_done(client, job_id)["status"] == "done" and len(saved) == 1


def test_flag_off_a_closed_stream_changes_nothing(env, monkeypatch):
    client, clock, timers, recorded, saved = env
    assert config.JOB_STOP_UNWATCHED is False  # off by default
    go = threading.Event()
    job_id = start(client, monkeypatch, go)
    close_a_stream(client, job_id)
    clock.now += 10 * GRACE
    client.get(f"/trace/jobs/{job_id}")
    job = job_routes.jobs.store.get(job_id)
    assert timers == [] and job.unwatched_since is None and not job.abandoned
    go.set()
    done = wait_done(client, job_id)
    assert done["status"] == "done" and done["error"] is None and len(saved) == 1
    assert set(done) == {"job_id", "status", "progress", "elapsed", "case_id", "error", "result"}
    assert not [e for e, _ in recorded if e == "case.trace_abandoned"]


def test_flag_on_a_stop_still_ends_as_a_stop(env, monkeypatch):
    client, _, _, recorded, saved = env
    monkeypatch.setattr(config, "JOB_STOP_UNWATCHED", True)
    go = threading.Event()
    job_id = start(client, monkeypatch, go)
    close_a_stream(client, job_id)
    assert client.delete(f"/trace/jobs/{job_id}", headers={ownership.OWNER_HEADER: OWNER}).status_code == 202
    job = wait_done(client, job_id)
    assert job["error"] == {"status_code": 409, "detail": "The trace was stopped by the person who started it."}
    assert saved == [] and slots_free()
    assert [d for e, d in recorded if e == "case.trace_stopped"] == [{"job_id": job_id, "was_running": True}]
    assert not [e for e, _ in recorded if e == "case.trace_abandoned"]


def test_the_timer_runs_on_the_event_loop(env, monkeypatch):
    # The real _schedule, with a short grace: the stop comes from the loop itself.
    client, _, _, recorded, saved = env
    monkeypatch.setattr(config, "JOB_STOP_UNWATCHED", True)
    monkeypatch.setattr(config, "JOB_UNWATCHED_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(job_routes, "_clock", time.monotonic)
    monkeypatch.setattr(job_routes, "_schedule", REAL_SCHEDULE)
    job_id = start(client, monkeypatch, threading.Event())
    close_a_stream(client, job_id)
    job = job_routes.jobs.store.get(job_id)  # read in place: a status poll would count as watching
    deadline = time.monotonic() + 3
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    job = client.get(f"/trace/jobs/{job_id}").json()
    assert job["error"]["detail"] == cases.ABANDONED_DETAIL and saved == [] and slots_free()
    assert [e for e, _ in recorded if e == "case.trace_abandoned"] == ["case.trace_abandoned"]

