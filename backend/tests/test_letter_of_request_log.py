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
