"""Background traces (app/jobs.py, app/routes/jobs.py)."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import models, ownership, pipeline, progress
from app.main import app
from app.routes import cases

OWNER = "c" * 32
ADDR = "0x" + "2" * 40


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'cases.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    monkeypatch.setattr(cases, "_running", threading.BoundedSemaphore(2))
    with TestClient(app) as c:
        yield c


def wait_done(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/trace/jobs/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def fake_trace(request):
    progress.report(stage="walking", hop=1, level_size=3, level_read=0)
    progress.report(level_read=3)
    return {"address": request.address, "chain": "ethereum", "exchange": "Binance"}


def test_a_job_runs_in_the_background_and_stores_the_case(client, monkeypatch):
    monkeypatch.setattr(pipeline, "run_trace", fake_trace)
    started = client.post("/trace/jobs", json={"address": ADDR},
                          headers={ownership.OWNER_HEADER: OWNER})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    assert started.json()["events_url"] == f"/trace/jobs/{job_id}/events"

    done = wait_done(client, job_id)
    assert done["status"] == "done" and done["result"]["exchange"] == "Binance"
    case_id = done["case_id"]
    assert client.get(f"/trace/{case_id}").status_code == 200
    # Stored under the starting browser's key, like POST /trace.
    listed = client.get("/cases", headers={ownership.OWNER_HEADER: OWNER}).json()["cases"]
    assert case_id in {c["case_id"] for c in listed}


def test_progress_is_streamed_as_server_sent_events(client, monkeypatch):
    gate = threading.Event()

    def slow(request):
        progress.report(stage="walking", hop=1, level_size=2, level_read=1)
        gate.wait(5)
        return {"address": request.address, "chain": "ethereum"}

    monkeypatch.setattr(pipeline, "run_trace", slow)
    job_id = client.post("/trace/jobs", json={"address": ADDR}).json()["job_id"]
    threading.Timer(0.5, gate.set).start()
    with client.stream("GET", f"/trace/jobs/{job_id}/events") as stream:
        text = "".join(stream.iter_text())
    assert "event: progress" in text
    assert '"stage": "walking"' in text
    assert "event: done" in text


def test_a_failed_trace_ends_the_job_with_the_error_and_frees_the_slot(client, monkeypatch):
    def boom(request):
        raise HTTPException(status_code=502, detail="provider down")

    monkeypatch.setattr(pipeline, "run_trace", boom)
    for _ in range(3):  # more than the two slots: each failure gave its slot back
        job_id = client.post("/trace/jobs", json={"address": ADDR}).json()["job_id"]
        done = wait_done(client, job_id)
        assert done["status"] == "failed"
        assert done["error"] == {"status_code": 502, "detail": "provider down"}


def test_an_unexpected_crash_is_reported_without_internals(client, monkeypatch):
    def crash(request):
        raise RuntimeError("secret internal path /data/x")

    monkeypatch.setattr(pipeline, "run_trace", crash)
    job_id = client.post("/trace/jobs", json={"address": ADDR}).json()["job_id"]
    done = wait_done(client, job_id)
    assert done["error"]["status_code"] == 500 and "/data" not in done["error"]["detail"]


def test_a_full_server_refuses_a_job_at_once(client, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(pipeline, "run_trace", lambda r: gate.wait(5) or {"address": r.address})
    try:
        assert client.post("/trace/jobs", json={"address": ADDR}).status_code == 202
        assert client.post("/trace/jobs", json={"address": ADDR}).status_code == 202
        busy = client.post("/trace/jobs", json={"address": ADDR})
        assert busy.status_code == 429
    finally:
        gate.set()


def test_an_unknown_job_is_a_404(client):
    assert client.get("/trace/jobs/nope").status_code == 404
    assert client.get("/trace/jobs/nope/events").status_code == 404


def test_progress_outside_a_job_is_a_no_op():
    progress.report(stage="walking")  # nobody listening: must not raise
