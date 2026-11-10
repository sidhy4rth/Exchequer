"""A complaint belongs to no unit until an officer claims it for theirs
(routes/complaints.py POST /complaints/{ref}/claim). A signed-in officer's
queue is then their unit's complaints and the unclaimed ones; another
unit's are not there. A demo caller (where the queue opens to one: never on
a public site) keeps the demo queue as it was, and cannot claim.

Throwaway SQLite file; no network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import accounts, audit, models, rate_limit
from app.complaints import ComplaintClaim
from app.main import app

from test_complaint_queue import add

CSRF = {accounts.CSRF_HEADER: "1"}
PASSWORD = "officer-password-long-2"


@pytest.fixture
def units(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True))
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**4)
    for limiter in rate_limit.LOGIN_LIMITS:
        limiter.reset()
    models.init_db()
    add("c1", "EXQ-FIRST01", "2026-11-01T05:00:00+00:00")
    add("c2", "EXQ-SECOND2", "2026-11-02T05:00:00+00:00")
    north, south = accounts.create_unit("Cyber Cell North"), accounts.create_unit("Cyber Cell South")
    for email, unit in (("asha@north.in", north), ("ravi@north.in", north), ("neha@south.in", south)):
        accounts.create_officer(email, email.split("@")[0].title(), unit.id, "officer", password=PASSWORD)
    return north, south


def officer(email: str) -> TestClient:
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=CSRF).status_code == 200
    return client


def listed(client: TestClient) -> dict[str, dict | None]:
    return {c["reference"]: c["unit"] for c in client.get("/complaints").json()["complaints"]}


def test_a_complaint_comes_in_unclaimed_and_every_unit_sees_it(units):
    assert listed(officer("asha@north.in")) == {"EXQ-SECOND2": None, "EXQ-FIRST01": None}
    assert listed(officer("neha@south.in")) == {"EXQ-SECOND2": None, "EXQ-FIRST01": None}


def test_a_claimed_complaint_is_its_units_alone(units):
    north, _ = units
    asha = officer("asha@north.in")
    claimed = asha.post("/complaints/EXQ-FIRST01/claim")
    assert claimed.status_code == 200
    assert claimed.json() == {"reference": "EXQ-FIRST01", "unit": {"id": north.id, "name": "Cyber Cell North"}}
    assert listed(asha)["EXQ-FIRST01"] == {"id": north.id, "name": "Cyber Cell North"}
    assert listed(officer("ravi@north.in"))["EXQ-FIRST01"]["name"] == "Cyber Cell North"  # the whole unit
    neha = officer("neha@south.in")
    assert listed(neha) == {"EXQ-SECOND2": None}
    assert neha.get("/complaints/EXQ-FIRST01").status_code == 404
    for path, body in (("status", {"status": "closed"}), ("messages", {"body": "Hello"}), ("claim", None)):
        assert neha.post(f"/complaints/EXQ-FIRST01/{path}", json=body).status_code == 404
    assert asha.get("/complaints/EXQ-FIRST01").json()["unit"]["id"] == north.id


def test_an_officer_claims_before_acting(units):
    asha = officer("asha@north.in")
    for path, body in (("status", {"status": "with_cell"}), ("messages", {"body": "We have it."})):
        refused = asha.post(f"/complaints/EXQ-FIRST01/{path}", json=body)
        assert refused.status_code == 409 and refused.json()["detail"] == "Claim this complaint for your unit first."
    assert asha.post("/complaints/EXQ-FIRST01/claim").status_code == 200
    assert asha.post("/complaints/EXQ-FIRST01/claim").status_code == 200  # again: still theirs
    assert asha.post("/complaints/EXQ-FIRST01/status", json={"status": "with_cell"}).status_code == 200
    assert asha.post("/complaints/EXQ-FIRST01/messages", json={"body": "We have it."}).status_code == 201


def test_a_demo_caller_keeps_the_demo_queue_and_cannot_claim(units):
    officer("asha@north.in").post("/complaints/EXQ-FIRST01/claim")
    demo = TestClient(app)
    assert set(listed(demo)) == {"EXQ-FIRST01", "EXQ-SECOND2"}
    assert demo.get("/complaints/EXQ-SECOND2").status_code == 200
    assert demo.post("/complaints/EXQ-SECOND2/status", json={"status": "with_cell"}).status_code == 200
    refused = demo.post("/complaints/EXQ-SECOND2/claim")
    assert refused.status_code == 403 and "Sign in as an officer" in refused.json()["detail"]
    with models.session() as s:
        assert [c.complaint_id for c in s.scalars(select(ComplaintClaim))] == ["c1"]


def test_a_claim_is_audited_with_the_unit(units, monkeypatch):
    north, _ = units
    calls = []
    monkeypatch.setattr(audit, "record", lambda event, *, case_id=None, detail=None: calls.append((event, detail)))
    officer("asha@north.in").post("/complaints/EXQ-FIRST01/claim")
    assert ("complaint.claim", {"reference": "EXQ-FIRST01", "unit_id": north.id}) in calls
