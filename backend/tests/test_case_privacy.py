"""A case link opens the case; the complaint's particulars stay with the
browser that traced it (app/case_privacy.py).

The case id is printed in every letter and report, which go to exchanges and
to Tether, and holding it is what opens the case. That must keep working --
a letter's reference has to lead back to the evidence. But a payment-mode
case also holds the victim's NCRP acknowledgement number and the wallet they
paid from, and those were returned to anyone with the id. Now only the
owner's browser gets them; everyone else gets the same case with those two
fields empty and a note saying so.

Throwaway SQLite file and a stub pipeline: no network.
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import jobs, models, ownership, pipeline
from app.main import app

OWNER_KEY = "o" * 32
OWNER = {ownership.OWNER_HEADER: OWNER_KEY}
OTHER = {ownership.OWNER_HEADER: "x" * 32}
NCRP = "31911250012345"
PAYER = "0x71c0" + "ab" * 16 + "9f3e"
SCAMMER = "0x" + "5" * 40
PAYMENT_CASE = {
    "address": SCAMMER, "chain": "ethereum", "exchange": "Binance", "exchange_address": "0x" + "e" * 40,
    "intake": {"mode": "payment", "ncrp_ack": NCRP,
               "payments": [{"tx_hash": "0x" + "c" * 64, "from": PAYER, "amount": 1.5, "timestamp": 1}]},
}
ADDRESS_CASE = {"address": SCAMMER, "chain": "ethereum", "exchange": "Binance"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'p.db'}", future=True))
    with TestClient(app) as c:
        owner_hash = hashlib.sha256(OWNER_KEY.encode()).hexdigest()
        models.save_case("pay-case", SCAMMER, PAYMENT_CASE, owner_hash=owner_hash)
        models.save_case("addr-case", SCAMMER, ADDRESS_CASE, owner_hash=owner_hash)
        yield c


@pytest.mark.parametrize("headers", [{}, OTHER])
def test_a_case_link_still_opens_but_without_the_particulars(client, headers):
    response = client.get("/trace/pay-case", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["exchange"] == "Binance"  # the letter's reference still leads to the evidence
    assert body["intake"]["ncrp_ack"] is None
    assert all(p["from"] is None for p in body["intake"]["payments"])
    assert body["intake"]["payments"][0]["amount"] == 1.5
    assert body["redacted"] == ["intake.ncrp_ack", "intake.victim_address", "intake.payments[].from"]
    assert NCRP not in response.text and PAYER not in response.text


def test_the_owner_still_sees_everything(client):
    body = client.get("/trace/pay-case", headers=OWNER).json()
    assert body["intake"]["ncrp_ack"] == NCRP
    assert body["intake"]["payments"][0]["from"] == PAYER
    assert "redacted" not in body


def test_an_address_case_is_returned_as_stored_to_anyone(client):
    assert client.get("/trace/addr-case").json() == ADDRESS_CASE


def test_the_stored_case_is_never_changed(client):
    client.get("/trace/pay-case")
    assert models.get_case("pay-case").result["intake"]["ncrp_ack"] == NCRP


@pytest.mark.parametrize("path", [
    "/trace/pay-case/report?format=json", "/trace/pay-case/report?format=text",
    "/trace/pay-case/graph?format=csv", "/trace/pay-case/graph?format=graphml",
    "/trace/pay-case/letter?to=exchange",
])
def test_exports_never_carry_the_ncrp_number(client, path):
    response = client.get(path)
    assert NCRP not in response.text


def test_a_finished_job_is_redacted_for_anyone_but_its_owner(client, monkeypatch):
    monkeypatch.setattr(pipeline, "run_trace", lambda request: dict(PAYMENT_CASE))
    started = client.post("/trace/jobs", json={"address": SCAMMER}, headers=OWNER).json()
    for _ in range(200):
        mine = client.get(f"/trace/jobs/{started['job_id']}", headers=OWNER).json()
        if mine["status"] != jobs.RUNNING:
            break
    assert mine["status"] == "done"
    assert mine["result"]["intake"]["ncrp_ack"] == NCRP
    for headers in ({}, OTHER):
        theirs = client.get(f"/trace/jobs/{started['job_id']}", headers=headers)
        assert theirs.json()["result"]["intake"]["ncrp_ack"] is None
        assert NCRP not in theirs.text and PAYER not in theirs.text


def test_the_victims_own_wallet_is_a_particular_too():
    # The complaint may give the victim's own paying wallet (intake.victim_address,
    # to check each payment's sender); it is as personal as the payer.
    from app.case_privacy import for_reader
    case = {**PAYMENT_CASE, "intake": {**PAYMENT_CASE["intake"], "victim_address": PAYER}}
    seen = for_reader(case, "owner-hash", "someone-else")
    assert seen["intake"]["victim_address"] is None and PAYER not in str(seen)
    assert for_reader(case, "owner-hash", "owner-hash")["intake"]["victim_address"] == PAYER
