"""The owner's console switch (EXCHEQUER_CONSOLE, app/access.py).

"open", the default, leaves the site as it is: the demo code (when set)
guards live work and anyone may read. "officers" closes every live or
spending action to a signed-in officer session; a demo code no longer opens
them. Recorded demos, /verify and every read of open data stay open in both.

Throwaway SQLite file, stub pipeline: no network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import access, accounts, config, models, ownership, pipeline, rate_limit
from app.main import app

CODE = "Qm7v-Kp2xL9tRw4ZsY8nHa"
OWNER = {ownership.OWNER_HEADER: "s" * 32}
CSRF = {accounts.CSRF_HEADER: "1"}
OFFICER_PW = "officer-password-long-2"
ADDRESS = "0x" + "1" * 40
REFUSAL = "Sign in as an officer to trace live."

# Every live or spending route, with a body it would otherwise accept.
OFFICER_ONLY = [
    ("POST", "/trace", {"address": ADDRESS, "save": False}),
    ("POST", "/trace/jobs", {"address": ADDRESS, "save": False}),
    ("DELETE", "/trace/jobs/some-job", None),
    ("POST", "/batches", {"name": "b", "rows": [{"address": ADDRESS}]}),
    ("POST", "/watches", {"address": ADDRESS}),
    ("POST", "/watches/some-watch/check", None),
    ("POST", "/requests", {"case_id": "case-1", "recipient": "Binance"}),
    ("POST", "/payments/search", {"chain": "ethereum", "asset": "ETH", "wallet": ADDRESS, "amount": "1",
                                  "from": 1_700_000_000, "to": 1_700_003_600}),
    ("POST", "/trace/some-case/recheck", None),
    # Added by the sign-off branch; guarded here by path so it is closed the
    # moment it lands.
    ("POST", "/requests/some-request/signoff", None),
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**4)
    monkeypatch.setattr(pipeline, "run_trace", lambda request: {"address": request.address, "chain": "ethereum"})
    monkeypatch.setattr(access, "wrong_codes",
                        rate_limit.SlidingWindowLimiter(access.wrong_codes.limit, access.wrong_codes.window))
    for limiter in rate_limit.LOGIN_LIMITS:
        limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        unit = accounts.create_unit("Cyber Cell North")
        accounts.create_officer("officer@example.org", "Om Officer", unit.id, "officer", password=OFFICER_PW)
        yield c


@pytest.fixture
def officers(monkeypatch):
    monkeypatch.setattr(config, "CONSOLE", "officers")


def sign_in(client):
    signed = client.post("/auth/login", json={"email": "officer@example.org", "password": OFFICER_PW}, headers=CSRF)
    assert signed.status_code == 200


def call(client, method, path, body, extra=None):
    return client.request(method, path, json=body, headers={**OWNER, **(extra or {})})


def officer_refusal(response):
    return response.status_code == 403 and response.json().get("detail") == REFUSAL


# -- the setting --------------------------------------------------------------------
@pytest.mark.parametrize("raw, mode", [("", "open"), ("open", "open"), ("officers", "officers"),
                                       (" Officers ", "officers"), ("closed", "open")])
def test_the_console_is_open_unless_the_owner_says_officers(raw, mode):
    assert config.console_mode({"EXCHEQUER_CONSOLE": raw}) == mode
    assert config.console_mode({}) == "open"


def test_an_unknown_setting_is_reported_at_start(monkeypatch, caplog):
    monkeypatch.setenv("EXCHEQUER_CONSOLE", "officer")
    with caplog.at_level("WARNING", logger="app.access"):
        access.report_at_startup()
    assert any("EXCHEQUER_CONSOLE" in r.getMessage() for r in caplog.records)


def test_a_public_site_closed_to_officers_is_not_reported_open(monkeypatch, caplog):
    monkeypatch.setattr(config, "PUBLIC_HOST", True)
    monkeypatch.setattr(config, "CONSOLE", "officers")
    with caplog.at_level("WARNING", logger="app.access"):
        access.report_at_startup()
    assert not any("THIS PUBLIC SITE IS OPEN" in r.getMessage() for r in caplog.records)


# -- open (the default): nothing changes ---------------------------------------------
@pytest.mark.parametrize("method, path, body", OFFICER_ONLY)
def test_open_mode_never_asks_for_an_officer(client, method, path, body):
    assert config.CONSOLE == "open"
    assert not officer_refusal(call(client, method, path, body))


def test_open_mode_with_a_code_still_takes_the_code(client, monkeypatch):
    monkeypatch.setattr(config, "DEMO_CODE", CODE)
    assert call(client, "POST", "/trace", OFFICER_ONLY[0][2]).status_code == 403
    assert call(client, "POST", "/trace", OFFICER_ONLY[0][2], {access.CODE_HEADER: CODE}).status_code == 200


# -- officers ---------------------------------------------------------------------------
@pytest.mark.parametrize("method, path, body", OFFICER_ONLY)
def test_officers_mode_refuses_every_live_route_without_a_session(client, officers, method, path, body):
    assert officer_refusal(call(client, method, path, body))


@pytest.mark.parametrize("method, path, body", OFFICER_ONLY)
def test_a_demo_code_does_not_open_officer_only_routes(client, officers, monkeypatch, method, path, body):
    monkeypatch.setattr(config, "DEMO_CODE", CODE)
    assert officer_refusal(call(client, method, path, body, {access.CODE_HEADER: CODE}))
    token = call(client, "POST", "/access/check", None, {access.CODE_HEADER: CODE}).json()["pass"]
    assert officer_refusal(call(client, method, path, body, {access.PASS_HEADER: token}))


@pytest.mark.parametrize("method, path, body", OFFICER_ONLY)
def test_a_signed_in_officer_passes_every_live_route(client, officers, monkeypatch, method, path, body):
    monkeypatch.setattr(config, "DEMO_CODE", CODE)  # an officer needs no code
    sign_in(client)
    # CSRF: the sign-off also asks for the header a signed-in session's writes carry.
    response = call(client, method, path, body, CSRF)
    assert not officer_refusal(response) and response.status_code != 403


def test_a_forged_session_is_refused(client, officers):
    client.cookies.set(accounts.COOKIE, "not-a-real-token")
    assert officer_refusal(call(client, "POST", "/trace", OFFICER_ONLY[0][2]))


def test_an_officer_on_a_temporary_password_is_refused(client, officers):
    sign_in(client)
    officer_id = client.get("/auth/me").json()["id"]
    accounts.change_officer(officer_id, reset_password=True)
    temp_session = accounts.start_session(officer_id)
    client.cookies.set(accounts.COOKIE, temp_session)
    # Refused by the switch itself, not only by the account's own check.
    assert officer_refusal(call(client, "POST", "/trace", OFFICER_ONLY[0][2]))
    assert client.get("/access").json()["officer"] is False
    assert not access.is_officer(temp_session)


@pytest.mark.parametrize("path", ["/health", "/demos/recorded", "/cases", "/exchanges", "/signing-key",
                                  "/access"])
@pytest.mark.parametrize("mode", ["open", "officers"])
def test_reading_and_demos_stay_open_in_both_modes(client, monkeypatch, path, mode):
    monkeypatch.setattr(config, "CONSOLE", mode)
    assert client.get(path, headers=OWNER).status_code == 200


@pytest.mark.parametrize("mode", ["open", "officers"])
def test_a_recorded_demo_opens_in_both_modes(client, monkeypatch, mode):
    monkeypatch.setattr(config, "CONSOLE", mode)
    demos = client.get("/demos/recorded").json()["demos"]
    assert demos
    assert client.get(f"/demos/recorded/{demos[0]['demo']}", headers=OWNER).status_code == 200


@pytest.mark.parametrize("mode", ["open", "officers"])
def test_verify_stays_open_in_both_modes(client, monkeypatch, mode):
    monkeypatch.setattr(config, "CONSOLE", mode)
    assert not officer_refusal(client.post("/verify", content=b"nothing signed here"))


# -- what the console and the monitors are told --------------------------------------
def test_access_says_the_mode_and_whether_the_caller_is_an_officer(client, monkeypatch):
    assert client.get("/access").json() == {"demo_code_required": False, "console": "open", "officer": False}
    monkeypatch.setattr(config, "CONSOLE", "officers")
    assert client.get("/access").json() == {"demo_code_required": False, "console": "officers", "officer": False}
    sign_in(client)
    assert client.get("/access").json()["officer"] is True


@pytest.mark.parametrize("mode", ["open", "officers"])
def test_health_reports_the_mode(client, monkeypatch, mode):
    monkeypatch.setattr(config, "CONSOLE", mode)
    body = client.get("/health").json()
    assert body["console"] == mode and body["access"] == "open"
