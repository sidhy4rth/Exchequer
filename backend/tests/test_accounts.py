"""Officer accounts, units and roles (R23): app/accounts.py, routes/accounts.py.

Admins create accounts; there is no public sign-up. A signed-in officer is
the caller wherever auth.current_user is asked; without a session cookie the
caller is the demo user exactly as before, so the recorded demos and every
current flow keep working. Throwaway SQLite file, stub pipeline: no network.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import accounts, auth, config, log_safety, models, ownership, pipeline, rate_limit
from app.main import app

ADMIN_PW = "admin-password-long-1"
OFFICER_PW = "officer-password-long-2"
CSRF = {accounts.CSRF_HEADER: "1"}
BROWSER = {ownership.OWNER_HEADER: "b" * 32}
SCAMMER = "0x" + "5" * 40
NCRP = "31911250012345"
PAYMENT_CASE = {
    "address": SCAMMER, "chain": "ethereum", "exchange": "Binance",
    "intake": {"mode": "payment", "ncrp_ack": NCRP,
               "payments": [{"tx_hash": "0x" + "c" * 64, "from": "0x" + "a" * 40, "amount": 1.5, "timestamp": 1}]},
}


class Clock:
    def __init__(self) -> None:
        self.at = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.at


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(accounts, "now", c)
    return c


@pytest.fixture
def store(tmp_path, monkeypatch, clock):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'a.db'}", future=True))
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**4)  # the real cost is tested once, below
    for limiter in rate_limit.LOGIN_LIMITS:
        limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        unit = accounts.create_unit("Cyber Cell North")
        other = accounts.create_unit("Cyber Cell South")
        admin, _ = accounts.create_officer("Admin@Example.org", "Asha Admin", unit.id, "admin", password=ADMIN_PW)
        officer, _ = accounts.create_officer("officer@example.org", "Om Officer", unit.id, "officer",
                                             password=OFFICER_PW)
        c.ids = {"unit": unit.id, "other": other.id, "admin": admin.id, "officer": officer.id}
        yield c


def login(client, email, password, headers=None):
    return client.post("/auth/login", json={"email": email, "password": password}, headers={**CSRF, **(headers or {})})


# -- passwords -------------------------------------------------------------------
def test_a_password_hash_is_scrypt_with_its_parameters_and_a_random_salt():
    stored = accounts.hash_password("correct horse battery")
    name, n, r, p, salt, _ = stored.split("$")
    assert (name, n, r, p) == ("scrypt", str(2**15), "8", "1")
    assert accounts.verify_password("correct horse battery", stored)
    assert not accounts.verify_password("correct horse batterz", stored)
    assert accounts.hash_password("correct horse battery").split("$")[4] != salt  # a fresh salt


def test_a_hash_made_with_other_parameters_still_verifies(monkeypatch):
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**4)
    stored = accounts.hash_password("pw-under-test")
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**15)
    assert accounts.verify_password("pw-under-test", stored)
    assert not accounts.verify_password("pw-under-test", "garbage") and not accounts.verify_password("x", "")


# -- sign-in ---------------------------------------------------------------------
def test_signing_in_sets_a_strict_http_only_secure_cookie_and_keeps_only_its_hash(store):
    response = login(store, "  ADMIN@example.org ", ADMIN_PW)
    assert response.status_code == 200 and response.json()["role"] == "admin"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{accounts.COOKIE}=")
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Secure" in cookie
    token = cookie.split(";")[0].split("=", 1)[1]
    with models.session() as s:
        [row] = s.query(models.OfficerSession).all()
    assert row.token_sha256 == hashlib.sha256(token.encode()).hexdigest() and token not in row.token_sha256


def test_on_localhost_the_cookie_is_not_secure(store):
    local = TestClient(app, base_url="http://localhost")
    assert "Secure" not in login(local, "admin@example.org", ADMIN_PW).headers["set-cookie"]


@pytest.mark.parametrize("email,password", [("admin@example.org", "wrong-password-x"),
                                            ("nobody@example.org", ADMIN_PW)])
def test_a_failed_sign_in_says_the_same_thing_whatever_was_wrong(store, email, password):
    response = login(store, email, password)
    assert response.status_code == 401 and "set-cookie" not in response.headers
    assert response.json()["detail"] == accounts.LOGIN_FAILED


def test_a_deactivated_officer_cannot_sign_in(store):
    login(store, "admin@example.org", ADMIN_PW)
    store.patch(f"/admin/officers/{store.ids['officer']}", json={"active": False}, headers=CSRF)
    store.cookies.clear()
    assert login(store, "officer@example.org", OFFICER_PW).json()["detail"] == accounts.LOGIN_FAILED


def test_sign_in_needs_the_request_header(store):
    response = store.post("/auth/login", json={"email": "admin@example.org", "password": ADMIN_PW})
    assert response.status_code == 403 and "set-cookie" not in response.headers


# -- abuse: limits and growing delays, never a lockout ------------------------------
@pytest.fixture
def proxied(monkeypatch):
    """Each X-Real-IP is its own client."""
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(config, "PROXY_CLIENT_FIRST", False)


class Ticks:
    """A stand-in for rate_limit's monotonic clock."""
    def __init__(self) -> None:
        self.at = 1000.0

    def monotonic(self) -> float:
        return self.at


@pytest.fixture
def ticks(monkeypatch):
    t = Ticks()
    monkeypatch.setattr(rate_limit, "time", t)
    return t


def guess_from_many_clients(store, ticks, email, seconds, step=0.25):
    """An attacker on four addresses fails for `email` the moment the
    e-mail-wide delay ends, each address staying under its own limits."""
    sent, end = 0, ticks.at + seconds
    while ticks.at < end:
        if rate_limit.login_email_delay.wait(email) is None:
            login(store, email, "wrong-pw-xyz", {"x-real-ip": f"10.9.0.{sent % 4}"})
            sent += 1
        ticks.at += step
    return sent


def test_failures_spread_over_many_clients_slow_each_client_that_failed(store, proxied):
    clients = [{"x-real-ip": f"10.0.0.{i}"} for i in range(rate_limit.login_email_delay.free + 1)]
    for client in clients:
        assert login(store, "officer@example.org", "wrong-pw-xyz", client).status_code == 401
    slowed = login(store, "officer@example.org", OFFICER_PW, clients[0])
    assert slowed.status_code == 429 and int(slowed.headers["retry-after"]) >= 1
    assert slowed.json()["detail"].startswith("Too many sign-in attempts")


def test_others_failures_never_hold_the_officers_own_sign_in(store, proxied, ticks):
    assert guess_from_many_clients(store, ticks, "officer@example.org", 3600) > 50
    assert rate_limit.login_email_delay.wait("officer@example.org") is not None  # kept running
    # The officer, who has not failed from their own address, gets in first time.
    assert login(store, "officer@example.org", OFFICER_PW, {"x-real-ip": "192.168.7.7"}).status_code == 200


def test_an_officer_who_mistyped_is_held_by_others_only_until_their_own_failure_is_forgotten(
        store, proxied, ticks):
    own = {"x-real-ip": "192.168.7.7"}
    assert login(store, "officer@example.org", "wrong-pw-xyz", own).status_code == 401
    guess_from_many_clients(store, ticks, "officer@example.org", 600)
    assert rate_limit.login_email_delay.wait("officer@example.org") is not None
    assert login(store, "officer@example.org", OFFICER_PW, own).status_code == 429
    guess_from_many_clients(store, ticks, "officer@example.org", rate_limit.login_pair_delay.forget - 600)
    assert login(store, "officer@example.org", OFFICER_PW, own).status_code == 200


def test_changing_a_password_is_not_held_by_others_failures(store, proxied, ticks):
    own = {"x-real-ip": "192.168.7.7"}
    login(store, "officer@example.org", OFFICER_PW, own)
    guess_from_many_clients(store, ticks, "officer@example.org", 600)
    body = {"current_password": OFFICER_PW, "new_password": "another-long-password"}
    assert store.post("/auth/password", headers={**CSRF, **own}, json=body).status_code == 200


def test_a_delay_grows_with_failures_is_capped_and_is_forgotten():
    delay = rate_limit.GrowingDelay(free=2, first=1, cap=8, forget=600)
    waits = []
    for t in range(0, 8):
        delay.failed("k", now=t * 100)
        waits.append(delay.wait("k", now=t * 100))
    assert waits[:2] == [None, None] and waits[2:6] == [1, 2, 4, 8] and waits[6:] == [8, 8]  # capped
    assert delay.wait("k", now=700 + 8) is None  # waited it out
    assert delay.wait("k", now=10_000) is None and delay.failures("k", now=10_000) == 0  # forgotten
    delay.failed("j", now=0)
    delay.failed("j", now=0)
    delay.failed("j", now=0)
    delay.succeeded("j")
    assert delay.wait("j", now=0) is None


def test_one_client_is_limited_across_every_email(store, monkeypatch):
    monkeypatch.setattr(rate_limit.login_clients, "limit", 3)
    for i in range(3):
        login(store, f"guess{i}@example.org", "wrong-pw-xyz")
    assert login(store, "admin@example.org", ADMIN_PW).status_code == 429


def test_one_client_hammering_one_email_is_refused_but_the_officer_still_signs_in(store, monkeypatch, proxied):
    monkeypatch.setattr(rate_limit.login_emails, "limit", 2)
    monkeypatch.setattr(rate_limit.login_pair_delay, "free", 99)
    attacker = {"x-real-ip": "10.1.0.1"}
    for _ in range(2):
        login(store, "admin@example.org", "wrong-pw-xyz", attacker)
    assert login(store, "admin@example.org", ADMIN_PW, attacker).status_code == 429
    # The limit is the attacker's, not the account's: no lockout for the officer.
    assert login(store, "admin@example.org", ADMIN_PW, {"x-real-ip": "10.1.0.9"}).status_code == 200


def test_a_delay_read_survives_its_key_vanishing_meanwhile(monkeypatch):
    delay = rate_limit.GrowingDelay(free=0, first=5, cap=8)
    delay.failed("k", now=0)
    real = delay.failures

    def racing(key, now=None):  # a sign-in for the same key succeeds in between
        count = real(key, now)
        delay.succeeded(key)
        return count

    monkeypatch.setattr(delay, "failures", racing)
    delay.wait("k", now=1)  # no KeyError


def test_a_right_password_clears_the_delay_and_is_not_counted_as_a_failure(store):
    login(store, "admin@example.org", "wrong-pw-xyz")
    assert login(store, "admin@example.org", ADMIN_PW).status_code == 200
    assert rate_limit.login_email_delay.failures("admin@example.org") == 0
    assert rate_limit.login_pair_delay.failures("admin@example.org testclient") == 0


# -- sessions ----------------------------------------------------------------------
def test_me_is_the_officer_when_signed_in_and_the_demo_otherwise(store):
    assert store.get("/auth/me").json() == {"demo": True}
    login(store, "officer@example.org", OFFICER_PW)
    me = store.get("/auth/me").json()
    assert me["email"] == "officer@example.org" and me["role"] == "officer"
    assert me["unit"] == {"id": store.ids["unit"], "name": "Cyber Cell North"} and me["must_change_password"] is False
    assert "password_hash" not in me


def test_a_session_ends_after_twelve_idle_hours(store, clock):
    login(store, "officer@example.org", OFFICER_PW)
    clock.at += timedelta(hours=11)
    assert store.get("/auth/me").json()["role"] == "officer"  # use keeps it alive
    clock.at += timedelta(hours=11, minutes=59)
    assert store.get("/auth/me").json()["role"] == "officer"
    clock.at += timedelta(hours=12, minutes=1)
    assert store.get("/auth/me").json() == {"demo": True}
    with models.session() as s:
        assert s.query(models.OfficerSession).count() == 0  # the dead row is gone


def test_a_session_ends_after_seven_days_however_busy(store, clock):
    login(store, "officer@example.org", OFFICER_PW)
    for _ in range(15):
        clock.at += timedelta(hours=11)
        assert store.get("/auth/me").json()["role"] == "officer"
    clock.at += timedelta(hours=2)  # 6 days 23 hours in: still signed in
    assert store.get("/auth/me").json()["role"] == "officer"
    clock.at += timedelta(hours=1, minutes=1)  # 7 days and a minute: over
    assert store.get("/auth/me").json() == {"demo": True}


def test_logout_deletes_the_session(store):
    login(store, "officer@example.org", OFFICER_PW)
    token = store.cookies.get(accounts.COOKIE)
    assert store.post("/auth/logout", headers=CSRF).status_code == 200
    store.cookies.set(accounts.COOKIE, token)  # an old copy of the cookie is worthless
    assert store.get("/auth/me").json() == {"demo": True}
    with models.session() as s:
        assert s.query(models.OfficerSession).count() == 0


def test_a_forged_cookie_is_the_demo_user(store):
    store.cookies.set(accounts.COOKIE, "not-a-real-token")
    assert store.get("/auth/me").json() == {"demo": True}


# -- password change -------------------------------------------------------------
def test_a_temporary_password_must_be_changed_before_anything_else(store):
    login(store, "admin@example.org", ADMIN_PW)
    made = store.post("/admin/officers", headers=CSRF, json={
        "email": "new@example.org", "name": "Nita New", "unit_id": store.ids["unit"], "role": "officer"}).json()
    temp = made["temporary_password"]
    assert len(temp) >= 16 and store.get("/admin/officers").text.count(temp) == 0  # shown once
    store.cookies.clear()
    assert login(store, "new@example.org", temp).json()["must_change_password"] is True
    assert store.get("/auth/me").json()["must_change_password"] is True
    assert store.get("/cases").status_code == 403  # nothing else until it is changed
    short = store.post("/auth/password", headers=CSRF, json={"current_password": temp, "new_password": "short"})
    assert short.status_code == 422
    wrong = store.post("/auth/password", headers=CSRF, json={"current_password": "nope-nope-nope",
                                                             "new_password": "a-new-long-password"})
    assert wrong.status_code == 401
    ok = store.post("/auth/password", headers=CSRF, json={"current_password": temp,
                                                          "new_password": "a-new-long-password"})
    assert ok.status_code == 200 and store.get("/auth/me").json()["must_change_password"] is False
    assert store.get("/cases").status_code == 200
    store.cookies.clear()
    assert login(store, "new@example.org", "a-new-long-password").status_code == 200


@pytest.mark.parametrize("path", ["/cases", "/requests", "/trace/" + SCAMMER])
def test_an_officer_on_a_temporary_password_opening_an_app_page_gets_the_app(store, tmp_path, monkeypatch, path):
    from app.routes import cases
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><div id=root></div>")
    monkeypatch.setattr(cases, "_INDEX_HTML", index)
    login(store, "admin@example.org", ADMIN_PW)
    temp = store.patch(f"/admin/officers/{store.ids['officer']}", headers=CSRF,
                       json={"reset_password": True}).json()["temporary_password"]
    store.cookies.clear()
    login(store, "officer@example.org", temp)
    page = store.get(path, headers={"sec-fetch-mode": "navigate", "accept": "text/html"})
    assert page.status_code == 200 and "<div id=root>" in page.text  # the app, to change it in
    assert store.get(path, headers={"sec-fetch-mode": "cors"}).status_code == 403  # the data waits


def test_changing_a_password_needs_a_session_and_the_header(store):
    body = {"current_password": OFFICER_PW, "new_password": "another-long-password"}
    assert store.post("/auth/password", headers=CSRF, json=body).status_code == 401
    login(store, "officer@example.org", OFFICER_PW)
    assert store.post("/auth/password", json=body).status_code == 403


# -- admin -------------------------------------------------------------------------
@pytest.mark.parametrize("method,path", [("get", "/admin/units"), ("post", "/admin/units"),
                                         ("get", "/admin/officers"), ("post", "/admin/officers"),
                                         ("patch", "/admin/officers/1")])
def test_admin_routes_are_for_admins_only(store, method, path):
    assert getattr(store, method)(path, headers=CSRF, **({} if method == "get" else {"json": {}})).status_code == 401
    login(store, "officer@example.org", OFFICER_PW)
    assert getattr(store, method)(path, headers=CSRF, **({} if method == "get" else {"json": {}})).status_code == 403


def test_an_admin_makes_units_and_officers_and_changes_them(store, caplog):
    with caplog.at_level(logging.INFO, logger="exchequer.audit"):
        login(store, "admin@example.org", ADMIN_PW)
        assert store.post("/admin/units", json={"name": "Unit X"}).status_code == 403  # no request header
        unit = store.post("/admin/units", headers=CSRF, json={"name": "  Cyber​ Cell East "}).json()
        assert unit["name"] == "Cyber Cell East"
        assert {u["name"] for u in store.get("/admin/units").json()["units"]} >= {"Cyber Cell East"}
        made = store.post("/admin/officers", headers=CSRF, json={
            "email": "S@Example.org", "name": "Sam", "unit_id": unit["id"], "role": "supervisor"}).json()
        assert made["officer"]["email"] == "s@example.org" and made["officer"]["role"] == "supervisor"
        again = store.post("/admin/officers", headers=CSRF, json={
            "email": "s@example.org", "name": "Sam", "unit_id": unit["id"], "role": "officer"})
        assert again.status_code == 409
        bad = store.post("/admin/officers", headers=CSRF, json={
            "email": "t@example.org", "name": "T", "unit_id": unit["id"], "role": "citizen"})
        assert bad.status_code == 422
        changed = store.patch(f"/admin/officers/{made['officer']['id']}", headers=CSRF,
                              json={"role": "officer", "unit_id": store.ids["other"], "reset_password": True}).json()
        assert changed["officer"]["role"] == "officer" and changed["officer"]["unit"]["id"] == store.ids["other"]
        assert changed["officer"]["must_change_password"] is True and len(changed["temporary_password"]) >= 16
    events = " ".join(caplog.messages)
    for event in ("auth.login", "admin.unit_create", "admin.officer_create", "admin.officer_update"):
        assert event in events
    listed = store.get("/admin/officers").json()["officers"]
    assert all("password_hash" not in o and "temporary_password" not in o for o in listed)


def test_the_last_admin_cannot_be_demoted_or_deactivated(store):
    login(store, "admin@example.org", ADMIN_PW)
    for change in ({"role": "officer"}, {"active": False}):
        assert store.patch(f"/admin/officers/{store.ids['admin']}", headers=CSRF, json=change).status_code == 409


@pytest.mark.parametrize("change", [{"reset_password": True}, {"active": False}])
def test_deactivating_or_resetting_an_officer_ends_their_sessions(store, change):
    other = TestClient(app, base_url="https://testserver")
    login(other, "officer@example.org", OFFICER_PW)
    login(store, "admin@example.org", ADMIN_PW)
    assert store.patch(f"/admin/officers/{store.ids['officer']}", headers=CSRF, json=change).status_code == 200
    assert other.get("/auth/me").json() == {"demo": True}
    with models.session() as s:
        assert s.query(models.OfficerSession).filter_by(officer_id=store.ids["officer"]).count() == 0


# -- bootstrap -----------------------------------------------------------------------
BOOT = {"email": "first@example.org", "name": "First Admin", "password": "first-admin-password", "unit": "HQ"}


@pytest.fixture
def empty(tmp_path, monkeypatch, clock):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'e.db'}", future=True))
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**4)
    for limiter in rate_limit.LOGIN_LIMITS:
        limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def test_bootstrap_is_absent_without_a_token(empty, monkeypatch):
    monkeypatch.setattr(config, "BOOTSTRAP_TOKEN", "")
    assert empty.post("/auth/bootstrap", headers=CSRF, json={**BOOT, "token": ""}).status_code == 404


@pytest.mark.parametrize("request_kwargs", [{"json": {**BOOT, "token": "x"}}, {"headers": CSRF},
                                            {"headers": CSRF, "content": b"{not json"}])
def test_bootstrap_is_absent_whatever_is_sent_while_unset_or_once_an_admin_exists(empty, monkeypatch,
                                                                                  request_kwargs):
    monkeypatch.setattr(config, "BOOTSTRAP_TOKEN", "")
    assert empty.post("/auth/bootstrap", **request_kwargs).status_code == 404  # no header, no body, bad JSON
    monkeypatch.setattr(config, "BOOTSTRAP_TOKEN", "boot-token-0123456789abcdef")
    unit = accounts.create_unit("HQ")
    accounts.create_officer("a@example.org", "A", unit.id, "admin", password=ADMIN_PW)
    assert empty.post("/auth/bootstrap", **request_kwargs).status_code == 404


def test_bootstrap_checks_its_body_once_open(empty, monkeypatch):
    monkeypatch.setattr(config, "BOOTSTRAP_TOKEN", "boot-token-0123456789abcdef")
    assert empty.post("/auth/bootstrap", headers=CSRF, json={"token": "x"}).status_code == 422
    assert empty.post("/auth/bootstrap", headers=CSRF, content=b"{not json").status_code == 422


def test_bootstrap_makes_the_first_admin_once(empty, monkeypatch):
    monkeypatch.setattr(config, "BOOTSTRAP_TOKEN", "boot-token-0123456789abcdef")
    assert empty.post("/auth/bootstrap", headers=CSRF, json={**BOOT, "token": "wrong-token"}).status_code == 403
    made = empty.post("/auth/bootstrap", headers=CSRF, json={**BOOT, "token": "boot-token-0123456789abcdef"})
    assert made.status_code == 200 and made.json()["role"] == "admin" and made.json()["unit"]["name"] == "HQ"
    again = empty.post("/auth/bootstrap", headers=CSRF, json={**BOOT, "token": "boot-token-0123456789abcdef"})
    assert again.status_code == 404  # an admin exists: the route is gone
    assert login(empty, "first@example.org", "first-admin-password").status_code == 200


def test_bootstrap_needs_the_request_header(empty, monkeypatch):
    monkeypatch.setattr(config, "BOOTSTRAP_TOKEN", "boot-token-0123456789abcdef")
    assert empty.post("/auth/bootstrap", json={**BOOT, "token": "boot-token-0123456789abcdef"}).status_code == 403


def test_the_bootstrap_token_never_reaches_the_logs(monkeypatch):
    monkeypatch.setattr(config, "BOOTSTRAP_TOKEN", "boot-token-0123456789abcdef")
    assert "boot-token" not in log_safety.redact("token=boot-token-0123456789abcdef")


# -- no secret is logged -----------------------------------------------------------
def test_sign_in_logs_no_password_token_or_cookie(store, caplog):
    with caplog.at_level(logging.DEBUG):
        response = login(store, "admin@example.org", ADMIN_PW)
        login(store, "admin@example.org", "wrong-password-q")
        store.post("/auth/logout", headers=CSRF)
    token = response.headers["set-cookie"].split(";")[0].split("=", 1)[1]
    text = " ".join(r.getMessage() for r in caplog.records)
    assert ADMIN_PW not in text and "wrong-password-q" not in text and token not in text
    assert "auth.login" in text and "auth.logout" in text
    assert "exchequer_session=<redacted>" in log_safety.redact(f"cookie: exchequer_session={token}")


# -- the caller --------------------------------------------------------------------
def test_without_a_session_the_caller_is_the_same_demo_user(store):
    mini = FastAPI()

    @mini.get("/whoami")
    def whoami(user: auth.CurrentUser):
        return user.__dict__

    probe = TestClient(mini, base_url="https://testserver")
    demo = probe.get("/whoami", headers=BROWSER).json()
    assert demo == auth.User(id=f"demo-{ownership.owner_hash('b' * 32)[:12]}", role="officer", unit=auth.DEMO_UNIT,
                             owner_hash=ownership.owner_hash("b" * 32)).__dict__
    login(store, "officer@example.org", OFFICER_PW)
    probe.cookies.set(accounts.COOKIE, store.cookies.get(accounts.COOKIE))
    officer = probe.get("/whoami", headers=BROWSER).json()
    assert officer["demo"] is False and officer["officer_id"] == store.ids["officer"]
    assert officer["unit_id"] == store.ids["unit"] and officer["unit"] == "Cyber Cell North"
    assert officer["owner_hash"] == ownership.owner_hash("b" * 32)  # the browser's own cases stay its own


# -- unit-scoped cases -------------------------------------------------------------
@pytest.fixture
def traced(store, monkeypatch):
    """A payment case traced by the officer, signed in on their own browser."""
    monkeypatch.setattr(pipeline, "run_trace", lambda request: dict(PAYMENT_CASE))
    login(store, "officer@example.org", OFFICER_PW)
    case_id = store.post("/trace", json={"address": SCAMMER, "case_ref": "FIR 12/2026"},
                         headers=BROWSER).json()["case_id"]
    store.cookies.clear()
    return case_id


def test_a_case_traced_signed_in_carries_the_officer_and_unit(store, traced):
    case = models.get_case(traced)
    assert (case.officer_id, case.unit_id) == (store.ids["officer"], store.ids["unit"])


def test_an_officer_of_the_same_unit_reads_and_lists_the_case_in_full(store, traced):
    colleague = TestClient(app, base_url="https://testserver")
    login(colleague, "admin@example.org", ADMIN_PW)  # same unit, another browser
    elsewhere = {ownership.OWNER_HEADER: "z" * 32}
    assert colleague.get(f"/trace/{traced}", headers=elsewhere).json()["intake"]["ncrp_ack"] == NCRP
    assert traced in {c["case_id"] for c in colleague.get("/cases", headers=elsewhere).json()["cases"]}
    assert "c" * 64 in colleague.get(f"/trace/{traced}/report", headers=elsewhere).text  # the payment's hash


def test_an_officer_of_another_unit_and_a_stranger_get_the_redacted_copy(store, traced):
    login(store, "admin@example.org", ADMIN_PW)
    store.patch(f"/admin/officers/{store.ids['officer']}", headers=CSRF, json={"unit_id": store.ids["other"]})
    store.cookies.clear()
    elsewhere = {ownership.OWNER_HEADER: "z" * 32}
    login(store, "officer@example.org", OFFICER_PW)  # now in the other unit
    for client in (store, TestClient(app, base_url="https://testserver")):
        body = client.get(f"/trace/{traced}", headers=elsewhere).json()
        assert body["intake"]["ncrp_ack"] is None
        assert "c" * 64 not in client.get(f"/trace/{traced}/report", headers=elsewhere).text
        assert traced not in {c["case_id"] for c in client.get("/cases", headers=elsewhere).json()["cases"]}


def test_the_browser_that_traced_it_still_owns_it_signed_out(store, traced):
    assert store.get(f"/trace/{traced}", headers=BROWSER).json()["intake"]["ncrp_ack"] == NCRP


def test_a_demo_trace_stores_no_officer_or_unit(store, monkeypatch):
    monkeypatch.setattr(pipeline, "run_trace", lambda request: dict(PAYMENT_CASE))
    case_id = store.post("/trace", json={"address": SCAMMER}, headers=BROWSER).json()["case_id"]
    case = models.get_case(case_id)
    assert (case.officer_id, case.unit_id) == (None, None)
