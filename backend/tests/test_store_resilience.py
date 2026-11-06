"""A finished trace is never thrown away because the store hiccuped
(routes/cases.py store_result, routes/jobs.py _run).

By the time the store is asked anything, the provider calls are spent. A
count query that failed before the save (Neon suspended, a pool timeout, a
SQLite lock) used to escape: POST /trace answered 500, a job ended "failed",
and the officer was told to trace again and spend the quota twice.

Runs against a throwaway SQLite file and a stub pipeline: no network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from app import config, models, ownership, pipeline
from app.main import app
from app.pipeline import TraceRequest
from app.routes import cases

OWNER = {ownership.OWNER_HEADER: "o" * 32}
ADDRESS = "0x" + "1" * 40


def _down(*_args, **_kwargs):
    raise OperationalError("SELECT count(*) FROM cases", {}, Exception("server closed the connection"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))
    monkeypatch.setattr(pipeline, "run_trace", lambda request: {"address": request.address, "chain": "ethereum"})
    monkeypatch.setattr(config, "MAX_STORED_CASES", 5000)
    monkeypatch.setattr(config, "MAX_CASES_PER_OWNER", 200)
    with TestClient(app) as c:
        yield c


def _job(client, body):
    started = client.post("/trace/jobs", json=body, headers=OWNER)
    assert started.status_code == 202
    for _ in range(200):
        job = client.get(f"/trace/jobs/{started.json()['job_id']}").json()
        if job["status"] != "running":
            return job
    raise AssertionError("job never finished")


@pytest.mark.parametrize("count", ["case_count", "case_count_for"])
def test_a_failing_count_still_saves_and_returns_the_trace(client, monkeypatch, count):
    monkeypatch.setattr(models, count, _down)
    response = client.post("/trace", json={"address": ADDRESS}, headers=OWNER)
    assert response.status_code == 200
    assert response.json()["case_id"]  # the save itself worked


def test_a_store_that_is_down_still_returns_the_trace_with_a_warning(client, monkeypatch):
    monkeypatch.setattr(models, "case_count", _down)
    monkeypatch.setattr(models, "case_count_for", _down)
    monkeypatch.setattr(models, "save_case", _down)
    response = client.post("/trace", json={"address": ADDRESS}, headers=OWNER)
    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] is None
    assert any("could not be saved" in w for w in body["warnings"])


def test_a_failing_count_still_finishes_the_job_done(client, monkeypatch):
    monkeypatch.setattr(models, "case_count", _down)
    monkeypatch.setattr(models, "save_case", _down)
    job = _job(client, {"address": ADDRESS})
    assert job["status"] == "done"
    assert job["result"]["address"] == ADDRESS
    assert any("could not be saved" in w for w in job["result"]["warnings"])


def test_a_failing_audit_does_not_fail_the_job(client, monkeypatch):
    def broken(_payload):
        raise RuntimeError("audit sink down")
    monkeypatch.setattr(cases, "record_trace", broken)
    job = _job(client, {"address": ADDRESS})
    assert job["status"] == "done" and job["result"]["case_id"]


def test_a_failing_audit_does_not_fail_post_trace(client, monkeypatch):
    def broken(_payload):
        raise RuntimeError("audit sink down")
    monkeypatch.setattr(cases, "record_trace", broken)
    response = client.post("/trace", json={"address": ADDRESS}, headers=OWNER)
    assert response.status_code == 200 and response.json()["case_id"]


def test_store_result_itself_never_raises_on_a_count_error(tmp_path, monkeypatch):
    """The batch runner calls store_result directly; a row whose trace finished
    must not be marked failed because the count could not be read."""
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'b.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(config, "MAX_STORED_CASES", 5000)
    monkeypatch.setattr(models, "case_count", _down)
    stored = cases.store_result({"address": ADDRESS}, TraceRequest(address=ADDRESS), "a" * 64)
    assert stored["case_id"]
