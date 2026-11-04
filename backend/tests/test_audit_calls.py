"""Every export, letter and freeze request records itself (CLAUDE.md rule 5).

Each call goes through to the real audit.record, so a badly named event fails here
rather than when R24's log starts refusing it. What must also hold: a request that
did nothing records nothing, and the record never carries an officer's notes.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import audit, models, ownership
from app.main import app

KEY = {ownership.OWNER_HEADER: "a" * 32}
CASE = {
    "address": "0xseed", "chain": "ethereum", "chain_name": "Ethereum Mainnet", "asset": "ETH",
    "direction": "outgoing", "graph": {"nodes": [{"id": "0xseed"}], "edges": []}, "confidence_detail": {},
    "exchange": "Binance", "exchange_address": "0xdep", "exchange_label": "Binance 14",
    "trace_path": [{"address": "0xseed", "depth": 0}], "risk_matches": [], "follow_ons": [],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'a.db'}", future=True))
    models.init_db()
    models.save_case("case-1", "0xseed", CASE)
    return TestClient(app)


@pytest.fixture
def recorded(monkeypatch):
    calls: list[tuple] = []
    real = audit.record

    def record(event, *, case_id=None, detail=None):
        real(event, case_id=case_id, detail=detail)
        calls.append((event, case_id, detail))

    monkeypatch.setattr(audit, "record", record)
    return calls


@pytest.mark.parametrize("url, call", [
    ("/trace/case-1/report", ("case.report_export", "case-1", {"format": "json"})),
    ("/trace/case-1/report?format=text", ("case.report_export", "case-1", {"format": "text"})),
    ("/trace/case-1/report?format=pdf", ("case.report_export", "case-1", {"format": "pdf"})),
    ("/trace/case-1/graph", ("case.graph_export", "case-1", {"format": "graphml"})),
    ("/trace/case-1/graph?format=csv", ("case.graph_export", "case-1", {"format": "csv"})),
    ("/trace/case-1/letters", ("case.letters_list", "case-1", None)),
    ("/trace/case-1/letter?to=exchange", ("case.letter_draft", "case-1", {"to": "exchange", "format": "text"})),
    ("/trace/case-1/requests", ("request.list", "case-1", None)),
    ("/requests?open=true", ("request.list", None, {"open": True})),
])
def test_each_read_records_its_event(client, recorded, url, call):
    assert client.get(url, headers=KEY).status_code == 200
    assert recorded == [call]


def test_a_request_records_its_whole_life_without_the_officers_words(client, recorded):
    made = client.post("/requests", json={"case_id": "case-1", "recipient": "Binance", "kind": "exchange"},
                       headers=KEY)
    assert made.status_code == 201
    rid = made.json()["request_id"]
    changed = client.patch(f"/requests/{rid}", json={"status": "sent", "notes": "spoke to the officer on duty"},
                           headers=KEY)
    assert changed.status_code == 200
    assert client.delete(f"/requests/{rid}", headers=KEY).json() == {"deleted": rid}

    assert recorded == [
        ("request.create", "case-1", {"kind": "exchange", "status": "drafted"}),
        ("request.update", "case-1", {"request_id": rid, "fields": ["notes", "status"]}),
        ("request.delete", None, {"request_id": rid}),
    ]


@pytest.mark.parametrize("method, url, body", [
    ("get", "/trace/nope/report", None),
    ("get", "/trace/nope/graph", None),
    ("get", "/trace/nope/letters", None),
    ("get", "/trace/nope/letter?to=exchange", None),
    ("post", "/requests", {"case_id": "nope", "recipient": "X"}),
    ("patch", "/requests/nope", {"status": "sent"}),
    ("delete", "/requests/nope", None),
])
def test_what_did_nothing_records_nothing(client, recorded, method, url, body):
    response = getattr(client, method)(url, headers=KEY, **({"json": body} if body else {}))
    assert response.status_code in (400, 404)
    assert recorded == []


def test_a_letter_the_case_cannot_support_records_nothing(client, recorded):
    assert client.get("/trace/case-1/letter?to=tether", headers=KEY).status_code == 400
    assert recorded == []


def test_no_owner_key_still_gets_the_same_answers(client, recorded):
    """B-1 changes who is asked, not what they get: these are the responses from before it."""
    assert client.get("/requests").json() == {"count": 0, "requests": []}
    assert client.get("/trace/case-1/requests").json() == {"count": 0, "requests": []}
    refused = client.post("/requests", json={"case_id": "case-1", "recipient": "X"})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "This browser sent no owner key, so it has no requests."
    assert client.delete("/requests/any").status_code == 400
    assert [c[0] for c in recorded] == ["request.list", "request.list"]


def test_exports_keep_their_download_names(client):
    assert client.get("/trace/case-1/report?format=text").headers["content-disposition"] == \
        'attachment; filename="exchequer-case-1.txt"'
    assert client.get("/trace/case-1/graph?format=csv").headers["content-type"].startswith("text/csv")
    assert client.get("/trace/case-1/letter?to=exchange").headers["content-disposition"] == \
        'attachment; filename="exchequer-case-1-request-exchange.txt"'
