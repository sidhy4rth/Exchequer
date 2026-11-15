"""A POST /trace whose client hangs up (EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT).

A client that gives up on a trace (check_demos' 400 s timeout, then its
retry) used to leave the trace running to the end, so a retry doubled the
work. With the flag on, the trace stops at its next provider request, keeps
nothing, and the audit says why; background jobs, meant to outlive their
request, are never stopped this way. With the flag off nothing changes.

The provider is faked (a chain of wallets, one transfer each, every read
charged to the case's budget as a real client's is) and the hang-up is an
ASGI http.disconnect sent mid-trace: no network.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import api_budget, audit, config, models, pipeline
from app.etherscan_client import Transaction
from app.main import app
from app.routes import cases

from conftest import addr

DEPTH = 6
WALLETS = [addr(f"c0de{i}") for i in range(DEPTH + 1)]
START = 1_700_000_000


def tx(i):
    src, dst = WALLETS[i], WALLETS[i + 1]
    return Transaction(hash=f"0x{i + 1:064x}", from_address=src, to_address=dst, value_native=1.0,
                       value_wei=10**18, timestamp=START + i * 60, block_number=START // 12 + i,
                       is_error=False, asset="ETH")


class ChainProvider:
    """Each wallet sends its funds on to the next. Every read is charged to
    the case's budget first, the checkpoint every real client passes; the
    second read pauses until the test has hung up (`pause`)."""

    def __init__(self, pause):
        self.pause = pause
        self.reads = []
        self.budget = None  # set by run_trace, as on a real client
        self.started = threading.Event()

    def get_outgoing_transactions(self, address, limit=None):
        self.budget.charge("etherscan", 1)
        self.reads.append(address)
        if len(self.reads) == 2:
            self.started.set()
            self.pause(self.budget)
        i = WALLETS.index(address)
        return [tx(i)] if i < DEPTH else []


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'cases.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    monkeypatch.setattr(cases, "_running", threading.BoundedSemaphore(2))
    monkeypatch.setattr(cases, "HANGUP_POLL_SECONDS", 0.01)
    monkeypatch.setattr(pipeline, "detect_swaps", lambda graph, *a, **k: [])
    return engine


def stored_cases(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM cases")).scalar()


@pytest.fixture
def recorded(monkeypatch):
    calls = []
    monkeypatch.setattr(audit, "record", lambda event, **kw: calls.append((event, kw)))
    return calls


@pytest.fixture
def budgets(monkeypatch):
    """Every TraceBudget a request makes, to read its stopped_by afterwards."""
    made = []
    real = api_budget.TraceBudget.for_request.__func__

    def for_request(cls, *a, **k):
        made.append(real(cls, *a, **k))
        return made[-1]

    monkeypatch.setattr(api_budget.TraceBudget, "for_request", classmethod(for_request))
    return made


def provide(monkeypatch, provider):
    @contextmanager
    def open_source(chain, asset):
        yield provider

    monkeypatch.setattr(pipeline, "open_source", open_source)


def until_cancelled(budget):
    deadline = time.monotonic() + 5
    while not budget.cancelled and time.monotonic() < deadline:
        time.sleep(0.005)


def post_then_hang_up(body, started, hung_up=None):
    """POST /trace over raw ASGI; once the trace is reading (`started`), the
    client disconnects. Returns the response status the server sent (to no one)."""
    payload = json.dumps(body).encode()
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "scheme": "http", "path": "/trace", "raw_path": b"/trace", "query_string": b"", "root_path": "",
             "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                         (b"content-length", str(len(payload)).encode())],
             "client": ("127.0.0.1", 50123), "server": ("testserver", 80)}
    sent = []

    async def drive():
        drop = asyncio.Event()
        first = True

        async def receive():
            nonlocal first
            if first:
                first = False
                return {"type": "http.request", "body": payload, "more_body": False}
            await drop.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        task = asyncio.create_task(app(scope, receive, send))
        assert await asyncio.to_thread(started.wait, 5), "the trace never started reading"
        drop.set()
        if hung_up is not None:
            hung_up.set()
        await asyncio.wait_for(task, 10)

    asyncio.run(drive())
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


REQUEST = {"address": WALLETS[0], "chain": "ethereum", "asset": "ETH", "max_depth": DEPTH, "follow_swaps": False}


@pytest.mark.parametrize("save", [False, True])
def test_a_hang_up_stops_the_trace_at_its_next_read_and_keeps_nothing(store, recorded, budgets, monkeypatch, save):
    monkeypatch.setattr(config, "TRACE_CANCEL_ON_DISCONNECT", True)
    provider = ChainProvider(pause=until_cancelled)
    provide(monkeypatch, provider)

    status = post_then_hang_up({**REQUEST, "save": save}, provider.started)

    assert status == 409
    assert provider.reads == WALLETS[:2]  # the third read was refused at its checkpoint
    (budget,) = budgets
    assert budget.stopped_by == "client_disconnected"
    assert stored_cases(store) == 0
    events = [event for event, _ in recorded]
    assert events == ["case.trace_start", "case.trace_abandoned"]  # never "case.trace"
    assert recorded[1][1]["detail"] == {"chain": "ethereum", "asset": "ETH", "direction": "outgoing",
                                        "mode": "address", "stopped_by": "client_disconnected", "saved": False}
    assert cases._running.acquire(blocking=False) and cases._running.acquire(blocking=False)  # slot freed


def test_with_the_flag_off_a_hang_up_changes_nothing(store, recorded, budgets, monkeypatch):
    monkeypatch.setattr(config, "TRACE_CANCEL_ON_DISCONNECT", False)
    hung_up = threading.Event()

    def after_the_hang_up(budget):
        assert hung_up.wait(5)
        time.sleep(0.2)  # twenty polls' worth: no one is watching

    provider = ChainProvider(pause=after_the_hang_up)
    provide(monkeypatch, provider)

    status = post_then_hang_up(REQUEST, provider.started, hung_up)

    assert status == 200
    assert set(provider.reads) == set(WALLETS[:DEPTH])  # every hop the depth allows (the seed again after)
    (budget,) = budgets
    assert not budget.cancelled and budget.stopped_by is None
    assert stored_cases(store) == 1
    assert [event for event, _ in recorded] == ["case.trace_start", "case.trace"]


def test_the_watch_is_silent_while_the_client_stays(store, recorded, monkeypatch):
    monkeypatch.setattr(config, "TRACE_CANCEL_ON_DISCONNECT", True)
    provider = ChainProvider(pause=lambda budget: time.sleep(0.1))  # ten polls of a live connection
    provide(monkeypatch, provider)

    with TestClient(app) as client:
        response = client.post("/trace", json=REQUEST)

    assert response.status_code == 200 and response.json()["case_id"]
    assert set(provider.reads) == set(WALLETS[:DEPTH])
    assert stored_cases(store) == 1
    assert [event for event, _ in recorded] == ["case.trace_start", "case.trace"]


def test_a_trace_that_finishes_after_a_hang_up_is_still_not_kept(store, recorded, monkeypatch):
    # Some reads swallow a stop (a block's date, a tag lookup) and the stage
    # carries on without them: the result returns, but it is not whole.
    monkeypatch.setattr(config, "TRACE_CANCEL_ON_DISCONNECT", True)
    started = threading.Event()

    def run_trace(request, **kw):
        budget = api_budget.current_budget()
        started.set()
        until_cancelled(budget)
        return {"address": request.address, "chain": "ethereum", "asset": "ETH", "exchange": "Binance"}

    monkeypatch.setattr(pipeline, "run_trace", run_trace)

    assert post_then_hang_up(REQUEST, started) == 409
    assert stored_cases(store) == 0
    assert [event for event, _ in recorded] == ["case.trace_start", "case.trace_abandoned"]


def test_a_background_job_outlives_its_request(store, recorded, budgets, monkeypatch):
    monkeypatch.setattr(config, "TRACE_CANCEL_ON_DISCONNECT", True)
    provider = ChainProvider(pause=lambda budget: time.sleep(0.1))
    provide(monkeypatch, provider)

    with TestClient(app) as client:
        started = client.post("/trace/jobs", json=REQUEST)  # answered at once: the client has left
        assert started.status_code == 202
        deadline = time.monotonic() + 5
        while (job := client.get(f"/trace/jobs/{started.json()['job_id']}").json())["status"] == "running":
            assert time.monotonic() < deadline, "the job did not finish"
            time.sleep(0.05)

    assert job["status"] == "done" and job["result"]["case_id"]
    assert set(provider.reads) == set(WALLETS[:DEPTH])
    (budget,) = budgets
    assert not budget.cancelled
    assert stored_cases(store) == 1


def test_a_hang_up_before_the_trace_starts_stops_it_at_its_first_read():
    watch = cases.HangupWatch()
    watch.hung_up()
    budget = api_budget.TraceBudget(60, 10)
    watch.attach(budget)
    with pytest.raises(api_budget.Cancelled):
        budget.charge("etherscan", 1)
    assert budget.stopped_by == "client_disconnected"


def test_a_detached_watch_leaves_the_budget_alone():
    watch = cases.HangupWatch()
    budget = api_budget.TraceBudget(60, 10)
    watch.attach(budget)
    watch.detach()
    watch.hung_up()  # after the trace returned: its result is already being stored
    assert not budget.cancelled


def test_a_stop_by_the_person_still_records_cancel():
    budget = api_budget.TraceBudget(60, 10)
    budget.cancel()
    with pytest.raises(api_budget.Cancelled):
        budget.sleep(1)
    assert budget.stopped_by == "cancel"


def test_the_flag_is_off_by_default_and_registered():
    assert config.FLAGS["EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT"]["on"] is False
