"""The demo code (app/access.py): on a public deployment, what spends the
provider quota or creates standing work needs the code; reading does not.

Runs against a throwaway SQLite file and a stub pipeline: no network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import access, config, models, ownership, pipeline, rate_limit
from app.main import app

CODE = "river-otter-42"
OWNER = {ownership.OWNER_HEADER: "o" * 32}
ADDRESS = "0x" + "1" * 40

# Every route the code guards, with a body it would otherwise accept.
GUARDED = [
    ("/trace", {"address": ADDRESS, "save": False}),
    ("/trace/jobs", {"address": ADDRESS, "save": False}),
    ("/batches", {"name": "b", "rows": [{"address": ADDRESS}]}),
    ("/watches", {"address": ADDRESS}),
    ("/watches/some-watch/check", None),
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True))
    traced = []
    monkeypatch.setattr(pipeline, "run_trace",
                        lambda request: traced.append(request.address) or {"address": request.address, "chain": "ethereum"})
    monkeypatch.setattr(access, "wrong_codes", rate_limit.SlidingWindowLimiter(10, 3600))
    with TestClient(app) as c:
        c.traced = traced
        yield c


@pytest.fixture
def code_set(monkeypatch):
    monkeypatch.setattr(config, "DEMO_CODE", CODE)


def post(client, path, body, code=None):
    headers = {**OWNER, **({access.CODE_HEADER: code} if code is not None else {})}
    return client.post(path, json=body, headers=headers)


# -- with no code configured, nothing changes -------------------------------------
def test_without_a_configured_code_tracing_stays_open(client):
    assert post(client, "/trace", GUARDED[0][1]).status_code == 200
    assert client.traced == [ADDRESS]


# -- with a code configured -------------------------------------------------------
def test_anonymous_post_trace_is_refused(client, code_set):
    response = post(client, "/trace", GUARDED[0][1])
    assert response.status_code == 403
    assert "demo code" in response.json()["detail"]
    assert client.traced == []  # refused before the route ran


def test_anonymous_post_watches_is_refused(client, code_set):
    assert post(client, "/watches", {"address": ADDRESS}).status_code == 403
    assert client.get("/watches", headers=OWNER).json()["count"] == 0


@pytest.mark.parametrize("path, body", GUARDED)
def test_every_guarded_route_refuses_a_caller_without_the_code(client, code_set, path, body):
    assert post(client, path, body).status_code == 403


def test_a_wrong_code_is_refused_and_says_so(client, code_set):
    response = post(client, "/trace", GUARDED[0][1], code="river-otter-41")
    assert response.status_code == 403 and "not right" in response.json()["detail"]
    assert client.traced == []


def test_the_right_code_lets_the_trace_run(client, code_set):
    assert post(client, "/trace", GUARDED[0][1], code=CODE).status_code == 200
    assert client.traced == [ADDRESS]


@pytest.mark.parametrize("path", ["/health", "/cases", "/demos/recorded", "/exchanges", "/signing-key"])
def test_reading_needs_no_code(client, code_set, path):
    assert client.get(path, headers=OWNER).status_code == 200


def test_a_refusal_still_carries_the_security_headers(client, code_set):
    response = post(client, "/trace", GUARDED[0][1])
    assert "content-security-policy" in response.headers


def test_guessing_the_code_is_cut_off_after_ten_wrong_tries(client, code_set):
    for _ in range(10):
        assert post(client, "/trace", GUARDED[0][1], code="guess").status_code == 403
    blocked = post(client, "/trace", GUARDED[0][1], code=CODE)  # even the right one, for now
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0


# -- watch creation is rate limited, code or not ----------------------------------------
def test_one_client_cannot_create_watches_without_end(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "watches", rate_limit.SlidingWindowLimiter(2, 3600))
    for n in range(2):
        assert post(client, "/watches", {"address": "0x" + str(n + 2) * 40}).status_code == 201
    refused = post(client, "/watches", {"address": "0x" + "9" * 40})
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0
