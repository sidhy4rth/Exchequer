"""Text the store cannot hold is refused at the edge (app/input_rules.py).

psycopg refuses any string holding a NUL, whether it is written or only used
in a WHERE clause, and Postgres enforces VARCHAR lengths; SQLite does
neither, so on production these were 500s the suite never saw
(r2-g2-postgres-prod-divergence-6-3). Runs against a throwaway SQLite file.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import DataError

from app import batches, freeze_requests, input_rules, models, ownership, rate_limit, watchlist
from app.main import app

KEY = "k" * 32
H = {ownership.OWNER_HEADER: KEY}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'i.db'}", future=True))
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    return TestClient(app, raise_server_exceptions=False)


def test_plain_text_keeps_one_visible_line_within_its_length():
    assert input_rules.plain_text("Binance\x00 14\n‮<x>", 200) == "Binance 14 <x>"
    cut = input_rules.plain_text("x" * 300, 200)
    assert len(cut) == 200 and cut.endswith("…")


def test_a_nul_in_a_path_is_a_400(client):
    r = client.get("/trace/abc%00")
    assert r.status_code == 400 and "control characters" in r.json()["detail"]


def test_a_nul_in_a_query_is_a_400(client):
    assert client.get("/cases/correlate?case_id=%00").status_code == 400
    assert client.get("/alerts?unread=%00", headers=H).status_code == 400


def test_a_nul_in_a_watch_note_is_refused_before_anything_is_stored(client):
    r = client.post("/watches", json={"address": "0x" + "7" * 40, "note": "a\x00b"}, headers=H)
    assert r.status_code == 422
    assert watchlist.list_watches(ownership.owner_hash(KEY)) == []
    assert client.post("/alerts/read", json={"alert_ids": ["a\x00"]}, headers=H).status_code == 422


def test_a_nul_in_a_freeze_request_is_refused(client):
    r = client.post("/requests", json={"case_id": "case-1", "recipient": "Bin\x00ance"}, headers=H)
    assert r.status_code == 422
    rid = client.post("/requests", json={"case_id": "case-1", "recipient": "Binance"}, headers=H).json()["request_id"]
    assert client.patch(f"/requests/{rid}", json={"notes": "x\x00"}, headers=H).status_code == 422


def test_a_newline_in_request_notes_is_still_accepted(client):
    rid = client.post("/requests", json={"case_id": "case-1", "recipient": "Binance"}, headers=H).json()["request_id"]
    r = client.patch(f"/requests/{rid}", json={"notes": "line one\nline two\ttabbed"}, headers=H)
    assert r.status_code == 200 and r.json()["notes"] == "line one\nline two\ttabbed"


def test_a_nul_batch_name_costs_no_trace_allowance(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "traces", rate_limit.SlidingWindowLimiter(30, 3600))
    monkeypatch.setattr(batches, "start", lambda *a, **k: None)  # nothing is traced
    before = rate_limit.traces.remaining("testclient")
    r = client.post("/batches", json={"name": "march\x00", "rows": [{"address": "0x" + "1" * 40}]}, headers=H)
    assert r.status_code == 422
    assert rate_limit.traces.remaining("testclient") == before


def test_a_database_data_error_is_a_400_not_a_500(client, monkeypatch):
    def refuse(*a, **k):
        raise DataError("INSERT ...", {}, Exception("value too long for type character varying(200)"))
    monkeypatch.setattr(watchlist, "list_watches", refuse)
    r = client.get("/watches", headers=H)
    assert r.status_code == 400 and "cannot be stored" in r.json()["detail"]


def test_sent_at_with_an_offset_in_seconds_is_stored_in_utc_and_fits(client):
    # 32 characters in, and Python's isoformat used to write 35 back.
    owner = ownership.owner_hash(KEY)
    made = freeze_requests.create(owner, "case-1", "OKX", "exchange", status="sent")
    later = freeze_requests.update(owner, made["request_id"], {"sent_at": "2026-10-13T00:00+05:30:15.123456"})
    limit = models.FreezeRequest.__table__.c.sent_at.type.length
    assert len(later["sent_at"]) <= limit and later["sent_at"].endswith("+00:00")
    assert later["sent_at"] == "2026-10-12T18:29:44+00:00"


@pytest.mark.parametrize("value", ["0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-05:00"])
def test_sent_at_whose_offset_leaves_the_calendar_is_a_400_and_changes_nothing(client, value):
    # A valid date whose offset moves it past year 1 or 9999 used to raise
    # OverflowError in the UTC conversion: a 500 that also lost the status.
    rid = client.post("/requests", json={"case_id": "case-1", "recipient": "Binance"}, headers=H).json()["request_id"]
    r = client.patch(f"/requests/{rid}", json={"status": "sent", "sent_at": value}, headers=H)
    assert r.status_code == 400 and "sent_at" in r.json()["detail"]
    after = client.get("/trace/case-1/requests", headers=H).json()["requests"][0]
    assert after["status"] != "sent"  # nothing in the refused PATCH was written
