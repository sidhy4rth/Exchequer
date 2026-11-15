"""A letter of request abroad in the case's requests log (freeze_requests.KINDS, letters_of_request.REQUEST_KIND).

It is its own kind, addressed to the requested country, so the log's tracking
(drafted, sent, acknowledged, ...) works for it as for any letter. What must not
happen: it needing an urgent-freeze sign-off, or the draft reading it as a
request already sent to the exchange.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import freeze_requests as fr
from app import models, ownership
from app.letters_of_request import REQUEST_KIND, draft
from app.main import app

from test_letters_of_request import DETAILS
from test_request_letters import case

OWNER = {ownership.OWNER_HEADER: "a" * 32}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'g.db'}", future=True))
    models.init_db()
    models.save_case("case-1", case()["address"], case())
    return TestClient(app)


def test_the_kind_is_known_and_fits_the_log():
    assert REQUEST_KIND in fr.KINDS
    assert len(REQUEST_KIND) <= models.FreezeRequest.__table__.c.kind.type.length
    assert not fr.needs_signoff(REQUEST_KIND)  # not an urgent freeze letter


def test_a_letter_of_request_moves_through_the_logs_statuses(client):
    made = client.post("/requests", json={"case_id": "case-1", "recipient": "Seychelles", "kind": REQUEST_KIND},
                       headers=OWNER)
    assert made.status_code == 201
    row = made.json()
    assert row["kind"] == REQUEST_KIND and row["recipient"] == "Seychelles" and row["status"] == "drafted"
    assert not row["needs_signoff"] and row["signoff_reason"] is None
    rid = row["request_id"]
    sent = client.patch(f"/requests/{rid}", json={"status": "sent", "reference": "MHA concurrence 1/2026"},
                        headers=OWNER).json()
    assert sent["sent_at"] and sent["reference"] == "MHA concurrence 1/2026"
    ack = client.patch(f"/requests/{rid}", json={"status": "acknowledged"}, headers=OWNER).json()
    assert [e["status"] for e in ack["history"]] == ["drafted", "sent", "acknowledged"]
    listed = client.get("/trace/case-1/requests", headers=OWNER).json()
    assert listed["count"] == 1 and listed["requests"][0]["kind"] == REQUEST_KIND


def test_the_draft_does_not_count_it_as_a_request_to_the_exchange():
    log = [{"recipient": "Seychelles", "kind": REQUEST_KIND, "status": "sent", "sent_at": "2026-10-20T05:00:00+00:00"}]
    text = draft("case-1", case(), DETAILS, log)
    assert "Records preserved: [" in text and "letter-rogatory request" not in text


# -- the statuses a letter of request moves through --------------------------------------------
@pytest.mark.parametrize("status", ["frozen", "awaiting_signoff", "ready"])
def test_a_letter_of_request_is_never_frozen_or_signed_off(client, status):
    # It asks the requested country for help; it freezes nothing itself, and it is not an urgent freeze letter.
    made = client.post("/requests", json={"case_id": "case-1", "recipient": "Seychelles", "kind": REQUEST_KIND},
                       headers=OWNER).json()
    moved = client.patch(f"/requests/{made['request_id']}", json={"status": status}, headers=OWNER)
    assert moved.status_code == 400
    assert client.get("/trace/case-1/requests", headers=OWNER).json()["requests"][0]["status"] == "drafted"
    logged = client.post("/requests", json={"case_id": "case-1", "recipient": "Mauritius", "kind": REQUEST_KIND,
                                            "status": status}, headers=OWNER)
    assert logged.status_code == 400


def test_its_statuses_are_drafted_sent_acknowledged_declined_closed():
    assert fr.statuses_for(REQUEST_KIND) == ("drafted", "sent", "acknowledged", "declined", "closed")
    assert "frozen" in fr.statuses_for("exchange")  # other letters keep theirs


def test_the_row_says_which_statuses_it_may_take(client):
    row = client.post("/requests", json={"case_id": "case-1", "recipient": "Seychelles", "kind": REQUEST_KIND},
                      headers=OWNER).json()
    assert row["statuses"] == list(fr.statuses_for(REQUEST_KIND))


# -- logged once per case and country while it is open ----------------------------------------
def test_logging_the_same_letter_again_returns_the_open_one(client):
    body = {"case_id": "case-1", "recipient": "Seychelles", "kind": REQUEST_KIND}
    first = client.post("/requests", json=body, headers=OWNER)
    assert first.status_code == 201 and not first.json()["already_logged"]
    again = client.post("/requests", json={**body, "recipient": "  seychelles "}, headers=OWNER)  # after a reload
    assert again.status_code == 200
    assert again.json()["request_id"] == first.json()["request_id"] and again.json()["already_logged"]
    assert client.get("/trace/case-1/requests", headers=OWNER).json()["count"] == 1


def test_a_letter_already_sent_is_not_logged_again_either(client):
    body = {"case_id": "case-1", "recipient": "Seychelles", "kind": REQUEST_KIND}
    rid = client.post("/requests", json=body, headers=OWNER).json()["request_id"]
    client.patch(f"/requests/{rid}", json={"status": "sent"}, headers=OWNER)
    assert client.post("/requests", json=body, headers=OWNER).json()["request_id"] == rid


def test_another_country_or_a_closed_letter_logs_a_new_one(client):
    body = {"case_id": "case-1", "recipient": "Seychelles", "kind": REQUEST_KIND}
    rid = client.post("/requests", json=body, headers=OWNER).json()["request_id"]
    other = client.post("/requests", json={**body, "recipient": "Mauritius"}, headers=OWNER)
    assert other.status_code == 201 and other.json()["request_id"] != rid
    for status in ("declined", "closed"):
        client.patch(f"/requests/{rid}", json={"status": status}, headers=OWNER)
    fresh = client.post("/requests", json=body, headers=OWNER)
    assert fresh.status_code == 201 and fresh.json()["request_id"] != rid


def test_other_kinds_of_letter_may_still_be_logged_twice(client):
    body = {"case_id": "case-1", "recipient": "Binance", "kind": "exchange"}
    ids = {client.post("/requests", json=body, headers=OWNER).json()["request_id"] for _ in range(2)}
    assert len(ids) == 2  # unchanged: only a letter of request is one per country


def test_the_audit_log_tells_a_new_letter_from_one_already_logged(client):
    from sqlalchemy import select

    body = {"case_id": "case-1", "recipient": "Seychelles", "kind": REQUEST_KIND}
    client.post("/requests", json=body, headers=OWNER)
    client.post("/requests", json=body, headers=OWNER)
    with models.session() as s:
        actions = [r.action for r in s.scalars(select(models.AuditEvent).where(
            models.AuditEvent.action.like("request.%"))).all()]
    assert actions == ["request.create", "request.create_existing"]
