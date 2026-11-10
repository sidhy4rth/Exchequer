"""The officers' complaints queue (routes/complaints.py): read the citizen
tables through this app's own connection, change a complaint's status,
reply, and link a stored case.

What must hold: a list never shows a whole NCRP number, nothing logs one
or a phone number, an officer's reply is the only thing written back where
the citizen reads, and every action is in the audit trail.
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import audit, config, models
from app.complaints import Complaint, ComplaintMessage, ComplaintPayment
from app.main import app

NCRP = "31234567890123"
MOBILE = "9876543210"
WALLET = "TJ" + "a" * 32
HASH = "ab" * 32


def add(cid: str, ref: str, at: str, *, status: str = "received", match: str | None = None,
        payments: list[tuple[str, str]] = ()) -> None:
    details = {"name": "A Citizen", "mobile": MOBILE, "story": "They promised returns on a trading app.",
               "app": "QuickTrade", "started": "", "link": "", "contacts": "", "upi": ""}
    with models.session() as s:
        s.add(Complaint(id=cid, reference=ref, ncrp=NCRP, status=status, details_json=json.dumps(details),
                        wallet_match=match, created_at=at, updated_at=at))
        for n, (amount, token) in enumerate(payments):
            s.add(ComplaintPayment(id=f"{cid}-{n}", complaint_id=cid, tx_hash=HASH, amount=amount, token=token,
                                   network="Tron (TRC20)", paid_at="2026-11-01 10:30", wallet=WALLET))
        s.commit()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'q.db'}", future=True))
    models.init_db()
    add("c1", "EXQ-OLDER1", "2026-11-01T05:00:00+00:00", payments=[("1200", "USDT"), ("800.5", "USDT")])
    add("c2", "EXQ-NEWER2", "2026-11-02T05:00:00+00:00", status="investigating", match="case,complaint",
        payments=[("0.5", "ETH"), ("100", "USDT")])
    add("c3", "EXQ-EMPTY3", "2026-11-03T05:00:00+00:00")
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


def test_the_queue_lists_newest_first_with_the_ncrp_masked(client):
    body = client.get("/complaints").json()
    assert [c["reference"] for c in body["complaints"]] == ["EXQ-EMPTY3", "EXQ-NEWER2", "EXQ-OLDER1"]
    older = body["complaints"][2]
    assert older["ncrp"] == "••••0123"
    assert older["payments"] == 2
    assert older["totals"] == [{"token": "USDT", "amount": "2000.5"}]
    assert older["received_at"] == "2026-11-01T05:00:00+00:00"
    assert older["status"] == "received"
    assert older["in_other_complaints"] is False
    newer = body["complaints"][1]
    assert newer["in_other_complaints"] is True and newer["in_stored_case"] is True
    assert newer["totals"] == [{"token": "ETH", "amount": "0.5"}, {"token": "USDT", "amount": "100"}]
    text = json.dumps(body)
    assert NCRP not in text and MOBILE not in text  # a list masks both and leaves the phone out


def test_the_queue_filters_by_status(client):
    rows = client.get("/complaints?status=investigating").json()["complaints"]
    assert [c["reference"] for c in rows] == ["EXQ-NEWER2"]
    assert client.get("/complaints?status=nonsense").status_code == 422


def test_the_queue_says_how_many_there_are_and_pages_to_older_ones(client):
    # A queue longer than one page must never drop the older complaints
    # without a sign: the total comes back with each page, and the next page
    # starts where the last one stopped.
    first = client.get("/complaints?limit=2").json()
    assert first["total"] == 3 and first["count"] == 2
    assert [c["reference"] for c in first["complaints"]] == ["EXQ-EMPTY3", "EXQ-NEWER2"]
    rest = client.get("/complaints?limit=2&offset=2").json()
    assert rest["total"] == 3 and [c["reference"] for c in rest["complaints"]] == ["EXQ-OLDER1"]
    assert client.get("/complaints?status=received&limit=1").json()["total"] == 2
    assert client.get("/complaints?offset=-1").status_code == 422


def test_a_complaint_opens_with_what_the_citizen_sent(client):
    body = client.get("/complaints/EXQ-OLDER1").json()
    assert body["ncrp"] == NCRP and body["details"]["mobile"] == MOBILE
    assert body["details"]["story"].startswith("They promised")
    assert body["payments"][0] == {"hash": HASH, "amount": "1200", "token": "USDT", "network": "Tron (TRC20)",
                                   "paid_at": "2026-11-01 10:30", "wallet": WALLET}
    assert body["messages"] == [] and body["case_id"] is None
    assert client.get("/complaints/NOPE").status_code == 404


def test_a_browser_opening_the_queue_gets_the_app_not_the_json(client, monkeypatch, tmp_path):
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><title>app</title>")
    from app.routes import cases
    monkeypatch.setattr(cases, "_INDEX_HTML", index)
    for path in ("/complaints", "/complaints/EXQ-OLDER1"):
        page = client.get(path, headers={"Sec-Fetch-Mode": "navigate"})
        assert page.headers["content-type"].startswith("text/html"), path


def test_status_changes_and_is_audited(client, recorded):
    changed = client.post("/complaints/EXQ-OLDER1/status", json={"status": "with_cell"})
    assert changed.status_code == 200 and changed.json()["status"] == "with_cell"
    assert client.get("/complaints/EXQ-OLDER1").json()["status"] == "with_cell"
    assert client.post("/complaints/EXQ-OLDER1/status", json={"status": "solved"}).status_code == 422
    assert ("complaint.status", None, {"reference": "EXQ-OLDER1", "status": "with_cell"}) in recorded


def test_an_officers_reply_is_stored_where_the_citizen_reads_it(client, recorded):
    sent = client.post("/complaints/EXQ-OLDER1/messages", json={"body": "  We have written to the exchange.\n"})
    assert sent.status_code == 201
    with models.session() as s:
        rows = s.scalars(select(ComplaintMessage).where(ComplaintMessage.complaint_id == "c1")).all()
    assert [(m.sender, m.body) for m in rows] == [("officer", "We have written to the exchange.")]
    thread = client.get("/complaints/EXQ-OLDER1").json()["messages"]
    assert [(m["from"], m["body"]) for m in thread] == [("officer", "We have written to the exchange.")]
    assert client.post("/complaints/EXQ-OLDER1/messages", json={"body": "   "}).status_code == 400
    assert client.post("/complaints/EXQ-OLDER1/messages", json={"body": "x" * 2001}).status_code == 422
    # The record says a reply went, never what it said.
    assert ("complaint.message", None, {"reference": "EXQ-OLDER1", "characters": 32}) in recorded


def test_a_stored_case_can_be_linked(client, recorded):
    models.save_case("case-9", WALLET, {"chain": "tron"})
    linked = client.post("/complaints/EXQ-OLDER1/link-case", json={"case_id": "case-9"})
    assert linked.status_code == 200
    assert client.get("/complaints/EXQ-OLDER1").json()["case_id"] == "case-9"
    assert client.post("/complaints/EXQ-OLDER1/link-case", json={"case_id": "missing"}).status_code == 404
    assert ("complaint.link_case", "case-9", {"reference": "EXQ-OLDER1"}) in recorded


def test_every_read_is_audited_by_reference_only(client, recorded):
    client.get("/complaints?status=received")
    client.get("/complaints/EXQ-OLDER1")
    assert recorded == [("complaint.list", None, {"status": "received"}),
                        ("complaint.read", None, {"reference": "EXQ-OLDER1"})]


def test_nothing_logs_an_ncrp_or_phone_number(client, caplog):
    caplog.set_level(logging.DEBUG)
    client.get("/complaints")
    client.get("/complaints/EXQ-OLDER1")
    client.post("/complaints/EXQ-OLDER1/messages", json={"body": "Call us"})
    assert NCRP not in caplog.text and MOBILE not in caplog.text


def test_a_public_site_shows_the_queue_to_no_one_until_officers_sign_in(client, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_HOST", True)
    for method, path, body in [("get", "/complaints", None), ("get", "/complaints/EXQ-OLDER1", None),
                               ("post", "/complaints/EXQ-OLDER1/status", {"status": "closed"}),
                               ("post", "/complaints/EXQ-OLDER1/messages", {"body": "hi"}),
                               ("post", "/complaints/EXQ-OLDER1/link-case", {"case_id": "x"})]:
        answer = getattr(client, method)(path, **({"json": body} if body else {}))
        assert answer.status_code == 403, path
        assert NCRP not in answer.text
