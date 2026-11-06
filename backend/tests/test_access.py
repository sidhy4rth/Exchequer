"""The demo code (app/access.py): on a public deployment, what spends the
provider quota or creates standing work needs the code; reading does not.

Runs against a throwaway SQLite file and a stub pipeline: no network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import access, config, models, ownership, pipeline, rate_limit
from app.main import app

CODE = "river-otter-42"
OWNER = {ownership.OWNER_HEADER: "o" * 32}
ADDRESS = "0x" + "1" * 40

# Every route the code guards, with a body it would otherwise accept.
GUARDED = [
    ("/trace", {"address": ADDRESS, "save": False}),
    ("/trace/jobs", {"address": ADDRESS, "save": False}),
    ("/batches", {"name": "b", "rows": [{"address": ADDRESS}]}),
    ("/watches", {"address": ADDRESS}),
    ("/watches/some-watch/check", None),
    ("/requests", {"case_id": "case-1", "recipient": "Binance"}),
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True))
    traced = []
    monkeypatch.setattr(pipeline, "run_trace",
                        lambda request: traced.append(request.address) or {"address": request.address, "chain": "ethereum"})
    monkeypatch.setattr(access, "wrong_codes",
                        rate_limit.SlidingWindowLimiter(access.wrong_codes.limit, access.wrong_codes.window))
    with TestClient(app) as c:
        c.traced = traced
        yield c


@pytest.fixture
def code_set(monkeypatch):
    monkeypatch.setattr(config, "DEMO_CODE", CODE)


def post(client, path, body, code=None):
    headers = {**OWNER, **({access.CODE_HEADER: code} if code is not None else {})}
    return client.post(path, json=body, headers=headers)


# -- with no code configured, nothing changes -------------------------------------
def test_without_a_configured_code_tracing_stays_open(client):
    assert post(client, "/trace", GUARDED[0][1]).status_code == 200
    assert client.traced == [ADDRESS]


# -- with a code configured -------------------------------------------------------
def test_anonymous_post_trace_is_refused(client, code_set):
    response = post(client, "/trace", GUARDED[0][1])
    assert response.status_code == 403
    assert "access code" in response.json()["detail"]
    assert client.traced == []  # refused before the route ran


def test_anonymous_post_watches_is_refused(client, code_set):
    assert post(client, "/watches", {"address": ADDRESS}).status_code == 403
    assert client.get("/watches", headers=OWNER).json()["count"] == 0


@pytest.mark.parametrize("path, body", GUARDED)
def test_every_guarded_route_refuses_a_caller_without_the_code(client, code_set, path, body):
    assert post(client, path, body).status_code == 403


def test_a_wrong_code_is_refused_and_says_so(client, code_set):
    response = post(client, "/trace", GUARDED[0][1], code="river-otter-41")
    assert response.status_code == 403 and "not right" in response.json()["detail"]
    assert client.traced == []


def test_the_right_code_lets_the_trace_run(client, code_set):
    assert post(client, "/trace", GUARDED[0][1], code=CODE).status_code == 200
    assert client.traced == [ADDRESS]


@pytest.mark.parametrize("path", ["/health", "/cases", "/demos/recorded", "/exchanges", "/signing-key"])
def test_reading_needs_no_code(client, code_set, path):
    assert client.get(path, headers=OWNER).status_code == 200


def test_a_refusal_still_carries_the_security_headers(client, code_set):
    response = post(client, "/trace", GUARDED[0][1])
    assert "content-security-policy" in response.headers


def test_guessing_the_code_is_cut_off_after_ten_wrong_tries(client, code_set):
    for _ in range(10):
        assert post(client, "/trace", GUARDED[0][1], code="guess").status_code == 403
    # Even the right code: answering it differently while locked out would
    # turn the lockout into an unlimited guessing oracle. A pass gets through.
    blocked = post(client, "/trace", GUARDED[0][1], code=CODE)
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    assert int(blocked.headers["retry-after"]) <= 900  # a prank lasts minutes, not an hour


# -- the pass: a browser that entered the code is never locked out by others -------------
def get_pass(client):
    body = post(client, "/access/check", None, code=CODE).json()
    assert body["ok"] is True and body["expires_in"] > 0
    return body["pass"]


def with_pass(client, path, body, token):
    return client.post(path, json=body, headers={**OWNER, access.PASS_HEADER: token})


def test_checking_the_right_code_returns_a_pass_that_unlocks_tracing(client, code_set):
    token = get_pass(client)
    assert CODE not in token
    assert with_pass(client, "/trace", GUARDED[0][1], token).status_code == 200
    assert client.traced == [ADDRESS]


def test_a_browser_holding_a_pass_is_not_locked_out_by_wrong_guesses_on_its_connection(client, code_set):
    token = get_pass(client)
    for _ in range(10):
        post(client, "/access/check", None, code="guess")
    assert post(client, "/trace", GUARDED[0][1], code=CODE).status_code == 429  # no oracle
    assert with_pass(client, "/trace", GUARDED[0][1], token).status_code == 200


@pytest.mark.parametrize("tamper", [
    lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),
    lambda t: t.replace("v1.", "v1.9", 1),
    lambda t: "v1.99999999999.x.y",
    lambda t: "garbage",
    lambda t: t + "." + "a" * 5000,
])
def test_a_tampered_pass_is_refused_and_counts_no_guess(client, code_set, tamper):
    token = tamper(get_pass(client))
    for _ in range(12):
        refused = with_pass(client, "/trace", GUARDED[0][1], token)
        assert refused.status_code == 403
    assert refused.headers.get("x-exchequer-demo-pass-invalid") == "1"
    assert access.wrong_codes.remaining(rate_limit.client_ip({}, "testclient")) == 10
    assert client.traced == []


def test_an_expired_pass_is_refused(client, code_set, monkeypatch):
    token = get_pass(client)
    later = access.time.time() + config.DEMO_PASS_SECONDS + 1
    monkeypatch.setattr(access.time, "time", lambda: later)
    assert with_pass(client, "/trace", GUARDED[0][1], token).status_code == 403


def test_a_pass_from_an_old_code_is_refused(client, code_set, monkeypatch):
    token = get_pass(client)
    monkeypatch.setattr(config, "DEMO_CODE", "a-new-code-after-the-event")
    assert with_pass(client, "/trace", GUARDED[0][1], token).status_code == 403


def test_rotating_the_leftmost_forwarded_entry_does_not_reset_the_guess_limit(client, code_set, monkeypatch):
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(config, "PROXY_CLIENT_FIRST", True)
    monkeypatch.setattr(config, "CLIENT_IP_HEADER", "cf-connecting-ip")
    for n in range(11):
        headers = {access.CODE_HEADER: "guess", "cf-connecting-ip": "49.36.1.1",
                   "x-forwarded-for": f"10.9.{n}.1, 49.36.1.1, 104.22.17.40"}
        status = client.post("/access/check", headers=headers).status_code
    assert status == 429
    # ...and nobody can lock out another address by writing it there.
    victim = {access.CODE_HEADER: "guess", "cf-connecting-ip": "49.36.7.7",
              "x-forwarded-for": "49.36.1.1, 49.36.7.7, 104.22.17.40"}
    assert client.post("/access/check", headers=victim).status_code == 403


# -- watch creation is rate limited, code or not ----------------------------------------
def test_one_client_cannot_create_watches_without_end(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "watches", rate_limit.SlidingWindowLimiter(2, 3600))
    for n in range(2):
        assert post(client, "/watches", {"address": "0x" + str(n + 2) * 40}).status_code == 201
    refused = post(client, "/watches", {"address": "0x" + "9" * 40})
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0


# -- what the console asks before showing the trace form ------------------------------
def test_the_console_can_ask_whether_a_code_is_needed(client, monkeypatch):
    assert client.get("/access").json() == {"demo_code_required": False}
    monkeypatch.setattr(config, "DEMO_CODE", CODE)
    assert client.get("/access").json() == {"demo_code_required": True}


def test_checking_a_code_goes_through_the_same_gate(client, code_set):
    assert post(client, "/access/check", None).status_code == 403
    assert post(client, "/access/check", None, code="nope").status_code == 403
    assert post(client, "/access/check", None, code=CODE).json()["ok"] is True


def test_checking_codes_counts_towards_the_guess_limit(client, code_set):
    for _ in range(10):
        post(client, "/access/check", None, code="guess")
    assert post(client, "/access/check", None, code=CODE).status_code == 429
