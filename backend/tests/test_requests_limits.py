"""Freeze-request writes are bounded (app/freeze_requests.py, routes/requests.py).

POST and PATCH /requests used to take unlimited writes from anyone: owner keys
cost nothing, any demo case id would do, and every status change appended to a
history that was rewritten in full on each update. On the free database that
is a way to fill the store. Now: the demo code guards POST, each connection
gets an hourly write allowance, each browser and the whole store have a row
cap, and a request keeps only its newest history entries.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import access, config, models, ownership, rate_limit
from app import freeze_requests as fr
from app.main import app

ALICE, BOB = "a" * 32, "b" * 32


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True))
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    monkeypatch.setattr(rate_limit, "request_writes", rate_limit.SlidingWindowLimiter(1000, 3600))
    return TestClient(app)


def h(key):
    return {ownership.OWNER_HEADER: key}


def new(client, key=ALICE):
    return client.post("/requests", json={"case_id": "case-1", "recipient": "Binance"}, headers=h(key))


def test_history_keeps_only_the_newest_entries(client):
    rid = new(client).json()["request_id"]
    for i in range(fr.HISTORY_MAX + 40):
        client.patch(f"/requests/{rid}", json={"status": "sent" if i % 2 == 0 else "drafted"}, headers=h(ALICE))
    history = client.get("/requests", headers=h(ALICE)).json()["requests"][0]["history"]
    assert len(history) == fr.HISTORY_MAX
    assert history[-1]["status"] == "drafted"  # the newest change survives


def test_one_browser_cannot_log_more_than_its_cap(client, monkeypatch):
    monkeypatch.setattr(fr, "MAX_PER_OWNER", 3)
    assert [new(client).status_code for _ in range(3)] == [201, 201, 201]
    refused = new(client)
    assert refused.status_code == 400 and "requests" in refused.json()["detail"]
    assert new(client, BOB).status_code == 201  # another browser is not affected


def test_the_store_as_a_whole_has_a_cap(client, monkeypatch):
    monkeypatch.setattr(fr, "MAX_TOTAL", 2)
    assert new(client, ALICE).status_code == 201
    assert new(client, BOB).status_code == 201
    assert new(client, "c" * 32).status_code == 400


def test_writes_from_one_connection_are_limited_per_hour(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "request_writes", rate_limit.SlidingWindowLimiter(3, 3600))
    rid = new(client).json()["request_id"]  # 1
    assert client.patch(f"/requests/{rid}", json={"status": "sent"}, headers=h(ALICE)).status_code == 200  # 2
    assert new(client, BOB).status_code == 201  # 3: a fresh owner key does not reset it
    limited = new(client, "c" * 32)
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    assert client.patch(f"/requests/{rid}", json={"status": "drafted"}, headers=h(ALICE)).status_code == 429
    # Reading is never limited.
    assert client.get("/requests", headers=h(ALICE)).status_code == 200


def test_logging_a_request_needs_the_demo_code_when_one_is_set(client, monkeypatch):
    monkeypatch.setattr(config, "DEMO_CODE", "river-otter-42")
    monkeypatch.setattr(access, "wrong_codes", rate_limit.SlidingWindowLimiter(10, 3600))
    assert access.is_guarded("POST", "/requests")
    assert new(client).status_code == 403
    ok = client.post("/requests", json={"case_id": "case-1", "recipient": "Binance"},
                     headers={**h(ALICE), access.CODE_HEADER: "river-otter-42"})
    assert ok.status_code == 201


def test_a_bad_request_never_loads_the_case(client):
    # Validation comes first, and the existence check reads only the id: a
    # stream of rejected requests must not pull a stored case (possibly
    # megabytes) from the metered database each time.
    from sqlalchemy import event
    statements = []
    event.listen(models._engine, "before_cursor_execute",
                 lambda conn, cursor, sql, *a: statements.append(sql))
    bad = client.post("/requests", json={"case_id": "case-1", "recipient": "  "}, headers=h(ALICE))
    assert bad.status_code == 400
    ok = new(client)
    assert ok.status_code == 201
    assert not [s for s in statements if "result_json" in s]
