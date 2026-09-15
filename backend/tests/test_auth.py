"""Officer sign-in: who ran a trace is recorded with it.

The gate is one shared access code. What matters: a wrong code is refused,
a right one admits and records the stated officer, the session cannot be
forged or edited, protected routes refuse without it, and with the variable
unset the gate is simply off so a machine without a .env keeps working.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app


@pytest.fixture
def gated(monkeypatch):
    monkeypatch.setenv("EXCHEQUER_ACCESS_CODE", "cyber-cell-2026")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def open_instance(monkeypatch):
    monkeypatch.delenv("EXCHEQUER_ACCESS_CODE", raising=False)
    with TestClient(app) as c:
        yield c


OFFICER = {"name": "Inspector R. Sharma", "officer_id": "4471", "unit": "Cyber Cell, Bengaluru"}


def test_protected_routes_refuse_without_a_session(gated):
    assert gated.get("/cases").status_code == 401
    assert gated.get("/exchanges").status_code == 401
    assert gated.get("/health").status_code == 200, "readiness stays open"
    assert gated.get("/auth/status").json() == {"required": True, "officer": None}


def test_wrong_code_is_refused_and_right_code_admits(gated):
    bad = gated.post("/auth/login", json={**OFFICER, "access_code": "guess"})
    assert bad.status_code == 401
    assert gated.get("/cases").status_code == 401

    ok = gated.post("/auth/login", json={**OFFICER, "access_code": "cyber-cell-2026"})
    assert ok.status_code == 200
    assert ok.json()["officer"]["name"] == "Inspector R. Sharma"
    assert auth.COOKIE in gated.cookies
    assert gated.get("/cases").status_code == 200
    status = gated.get("/auth/status").json()
    assert status["required"] is True and status["officer"]["officer_id"] == "4471"


def test_logout_ends_the_session(gated):
    gated.post("/auth/login", json={**OFFICER, "access_code": "cyber-cell-2026"})
    gated.post("/auth/logout")
    assert gated.get("/cases").status_code == 401


def test_a_forged_or_edited_token_is_not_a_session(gated, monkeypatch):
    officer = auth.Officer("A", "1", "U", "2026-09-16T00:00:00Z")
    token = auth.issue_token(officer)
    assert auth.read_token(token) == officer
    payload, sig = token.rsplit(".", 1)
    assert auth.read_token(payload + ".AAAA") is None
    assert auth.read_token("x" + token) is None
    # A token minted under a different code is not accepted here.
    monkeypatch.setenv("EXCHEQUER_ACCESS_CODE", "another-code")
    assert auth.read_token(token) is None


def test_sessions_expire():
    officer = auth.Officer("A", "1", "U", "2026-09-16T00:00:00Z")
    token = auth.issue_token(officer, now=1_000_000)
    assert auth.read_token(token, now=1_000_000 + 60) is not None
    assert auth.read_token(token, now=1_000_000 + auth.SESSION_HOURS * 3600 + 1) is None


def test_with_no_access_code_the_gate_is_off(open_instance):
    assert open_instance.get("/auth/status").json() == {"required": False, "officer": None}
    assert open_instance.get("/cases").status_code == 200
    assert open_instance.post("/auth/login", json={**OFFICER, "access_code": "x"}).status_code == 400


def test_the_report_header_names_the_officer():
    import json
    from app.models import Case
    from app.report import build_report, render_text_report

    def stored(result):
        return Case(id="c1", address=result["address"], created_at="2026-09-16T10:00:00+00:00",
                    result_json=json.dumps(result))

    base = {"address": "0x" + "ab" * 20, "chain": "ethereum", "asset": "ETH", "native_symbol": "ETH",
            "direction": "outgoing", "exchange": None, "confidence": None, "flags": [],
            "confidence_detail": {"components": [], "caveats": []}, "trace_path": [], "matches": [],
            "findings": [], "graph": {"nodes": [], "edges": []}, "transfers": []}

    with_officer = dict(base, traced_by={**OFFICER, "signed_in_at": "2026-09-16T09:58:00Z"})
    text = render_text_report(build_report(stored(with_officer)))
    assert "Traced by        : Inspector R. Sharma (ID 4471) · Cyber Cell, Bengaluru" in text

    text = render_text_report(build_report(stored(dict(base, traced_by=None))))
    assert "Traced by        : not recorded (sign-in was off on this instance)" in text
