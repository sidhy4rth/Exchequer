"""Recorded demos: served from the data file, never from the case store."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import models
from app.main import app
from app.routes import demos


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_every_demo_in_the_expectations_has_a_recording():
    expected = json.loads((demos.RECORDED_DEMOS_PATH.parent / "demo_expectations.json").read_text())
    recorded = {row["demo"]: row for row in json.loads(demos.RECORDED_DEMOS_PATH.read_text())}
    assert set(recorded) == {d["demo"] for d in expected}
    for d in expected:
        result = recorded[d["demo"]]["result"]
        for key in ("address", "chain", "asset", "max_depth", "direction"):
            assert result[key] == d[key], (d["demo"], key)


def test_recordings_carry_no_api_key():
    text = demos.RECORDED_DEMOS_PATH.read_text().lower()
    assert "apikey" not in text and "api_key=" not in text


def test_list_recorded(client):
    body = client.get("/demos/recorded").json()
    assert [d["demo"] for d in body["demos"]] == list(range(1, 13))
    assert all(d["recorded_at"] for d in body["demos"])


def test_get_recorded_is_a_case_without_a_case_id(client):
    body = client.get("/demos/recorded/9").json()
    assert body["recorded_demo"] == 9
    assert body["case_id"] is None
    assert body["created_at"]
    assert body["graph"]["nodes"]


def test_unknown_demo_is_404(client):
    assert client.get("/demos/recorded/99").status_code == 404


def test_opening_a_recording_stores_nothing(client):
    before = len(models.all_cases())
    client.get("/demos/recorded/1")
    assert len(models.all_cases()) == before
