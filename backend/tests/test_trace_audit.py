"""Every finished trace is audited (CLAUDE.md rule 5), without its particulars."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import audit, jobs, pipeline
from app.contracts import upgrade
from app.main import app
from app.pipeline import TraceRequest
from app.routes import cases
from app.routes import jobs as job_routes

from conftest import addr

SCAMMER = addr("5ca")
NCRP = "31911250012345"


def finished(**extra):
    return upgrade({
        "address": SCAMMER, "chain": "ethereum", "asset": "ETH", "direction": "outgoing",
        "exchange": "Binance", "exchange_address": addr("b1"), "transfers": [], "matches": [],
        **extra,
    })


@pytest.fixture
def recorded(monkeypatch):
    calls = []
    monkeypatch.setattr(audit, "record", lambda event, **kw: calls.append((event, kw)))
    return calls


def test_a_trace_through_the_api_is_audited_once(monkeypatch, recorded):
    monkeypatch.setattr(pipeline, "run_trace", lambda request, **kw: finished())
    with TestClient(app) as client:
        body = client.post("/trace", json={"address": SCAMMER, "chain": "ethereum"}).json()
    ((event, kw),) = recorded
    assert event == "case.trace" and kw["case_id"] == body["case_id"]
    assert kw["detail"] == {"chain": "ethereum", "asset": "ETH", "direction": "outgoing", "mode": "address",
                            "payments": 0, "saved": True, "exchange_reached": True}


def test_a_background_trace_is_audited_once(monkeypatch, recorded):
    monkeypatch.setattr(pipeline, "run_trace", lambda request, **kw: finished())
    job = jobs.store.create()
    assert cases._running.acquire(blocking=False)  # what admit() holds for the job
    job_routes._run(job, TraceRequest(address=SCAMMER, chain="ethereum"), owner=None)
    ((event, kw),) = recorded
    assert event == "case.trace" and kw["detail"]["saved"] is True


def test_the_audit_names_no_address_and_no_complaint_number(recorded):
    payment = {"tx_hash": "0x" + "aa" * 32, "chain": "ethereum", "asset": "ETH", "amount": 2.0,
               "from": addr("71c"), "to": SCAMMER, "block": 1, "timestamp": 1, "found_by": "victim"}
    cases.record_trace(finished(case_id="c1", intake={"mode": "payment", "payments": [payment], "ncrp_ack": NCRP}))
    ((_, kw),) = recorded
    text = json.dumps(kw)
    assert kw["detail"]["mode"] == "payment" and kw["detail"]["payments"] == 1
    for secret in (SCAMMER, addr("71c"), NCRP, payment["tx_hash"]):
        assert secret not in text


def test_the_real_audit_accepts_what_a_trace_records():
    # audit.record enforces what R24's log can store: a dotted event, JSON detail.
    cases.record_trace(finished(case_id="c2"))
