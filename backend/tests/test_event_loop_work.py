"""Heavy request work stays off the event loop.

The site serves every visitor from one event loop on about a tenth of a CPU.
Two routes did their heavy part on that loop, so one big request stalled
everyone: GET /trace/{id} let FastAPI walk a stored case (it can be ~20 MB)
through jsonable_encoder, and POST /verify parsed up to 2 MB of pasted text
inside an async handler.
"""
from __future__ import annotations

import asyncio

import fastapi.routing
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import models, signing
from app.main import app
from app.routes import verify as verify_route


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'e.db'}", future=True))
    models.init_db()
    return TestClient(app)


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def test_reading_a_case_does_not_re_encode_it(client, monkeypatch):
    result = {"address": "0xseed", "trace_path": [{"address": f"0x{i:040x}", "depth": i % 6} for i in range(500)]}
    models.save_case("case-big", "0xseed", result)

    def refuse(*_a, **_k):
        raise AssertionError("the stored case went through jsonable_encoder on the event loop")
    monkeypatch.setattr(fastapi.routing, "jsonable_encoder", refuse)
    response = client.get("/trace/case-big")
    assert response.status_code == 200
    assert response.json() == result


def test_a_missing_case_is_still_a_json_404(client):
    response = client.get("/trace/no-such-case")
    assert response.status_code == 404 and "No case" in response.json()["detail"]


def test_verifying_runs_off_the_event_loop(client, monkeypatch):
    seen = []
    real = signing.verify_report

    def spy(text):
        seen.append(_on_event_loop())
        return real(text)
    monkeypatch.setattr(verify_route, "verify_report", spy)
    response = client.post("/verify", content=b"EXCHEQUER CASE REPORT\nnot sealed\n")
    assert response.status_code == 200 and response.json()["sealed"] is False
    assert seen == [False]
