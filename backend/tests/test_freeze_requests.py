"""Freeze-request tracking (app/freeze_requests.py, app/routes/requests.py)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import freeze_requests as fr
from app import models, ownership
from app.main import app

ALICE, BOB = "a" * 32, "b" * 32


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True))
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    return TestClient(app)


def h(key):
    return {ownership.OWNER_HEADER: key}


def test_a_request_moves_through_its_statuses_with_history(client):
    made = client.post("/requests", json={"case_id": "case-1", "recipient": "Binance", "kind": "exchange",
                                          "address": "0xdep", "asset": "ETH"}, headers=h(ALICE))
    assert made.status_code == 201 and made.json()["status"] == "drafted"
    rid = made.json()["request_id"]
    sent = client.patch(f"/requests/{rid}", json={"status": "sent", "reference": "FIR 12/2026"}, headers=h(ALICE)).json()
    assert sent["sent_at"] and sent["reference"] == "FIR 12/2026" and sent["days_waiting"] == 0
    frozen = client.patch(f"/requests/{rid}", json={"status": "frozen", "amount_frozen": 9.5,
                                                    "note": "Binance froze the deposit"}, headers=h(ALICE)).json()
    assert [e["status"] for e in frozen["history"]] == ["drafted", "sent", "frozen"]
    assert frozen["history"][-1]["note"] == "Binance froze the deposit"
    assert frozen["amount_frozen"] == 9.5
    assert client.get("/requests?open=true", headers=h(ALICE)).json()["count"] == 0
    assert client.get("/trace/case-1/requests", headers=h(ALICE)).json()["count"] == 1


def test_requests_belong_to_their_browser(client):
    rid = client.post("/requests", json={"case_id": "case-1", "recipient": "Tether", "kind": "tether"},
                      headers=h(ALICE)).json()["request_id"]
    assert client.get("/trace/case-1/requests", headers=h(BOB)).json()["count"] == 0
    assert client.patch(f"/requests/{rid}", json={"status": "sent"}, headers=h(BOB)).status_code == 404
    assert client.delete(f"/requests/{rid}", headers=h(BOB)).status_code == 404
    assert client.delete(f"/requests/{rid}", headers=h(ALICE)).status_code == 200


def test_bad_input(client):
    assert client.post("/requests", json={"case_id": "nope", "recipient": "X"}, headers=h(ALICE)).status_code == 400
    assert client.post("/requests", json={"case_id": "case-1", "recipient": "X", "kind": "bank"},
                       headers=h(ALICE)).status_code == 400
    assert client.post("/requests", json={"case_id": "case-1", "recipient": "X"}).status_code == 400  # no key
    rid = client.post("/requests", json={"case_id": "case-1", "recipient": "X"}, headers=h(ALICE)).json()["request_id"]
    assert client.patch(f"/requests/{rid}", json={"status": "lost"}, headers=h(ALICE)).status_code == 400
    assert client.patch(f"/requests/{rid}", json={"amount_frozen": -1}, headers=h(ALICE)).status_code == 400
    assert client.patch(f"/requests/{rid}", json={"sent_at": "yesterday"}, headers=h(ALICE)).status_code == 400


def test_a_request_with_no_reply_for_a_week_is_flagged(client):
    r = fr.create(ownership.owner_hash(ALICE), "case-1", "OKX", "exchange", status="sent")
    later = fr.update(ownership.owner_hash(ALICE), r["request_id"], {"sent_at": "2026-01-01"})
    assert later["days_waiting"] >= 7 and later["follow_up"] is True
