"""POST /api/session and /api/logout: the NCRP number plus the tracking code
gives a short-lived cookie. Wrong codes slow down, per NCRP number and per
connection, and the wait always ends: there is no permanent lockout."""
from __future__ import annotations

import pytest
from conftest import CLIENT, NCRP, call, sign_in, submit

from _lib import limits, web


@pytest.fixture
def clock(monkeypatch):
    now = [1_800_000_000]
    monkeypatch.setattr(web, "now", lambda: now[0])
    return now


def wrong(ncrp=NCRP, client=CLIENT):
    return call("session", body={"ncrp": ncrp, "code": "2222-2222-2222"}, client=client)


def test_the_right_code_gives_a_strict_short_lived_cookie(db):
    code = submit()["tracking_code"]
    res = call("session", body={"ncrp": NCRP, "code": code.lower()})
    assert res.status == 200 and res.body == {"signed_in": True}
    [cookie] = res.cookies
    parts = [p.strip() for p in cookie.split(";")]
    assert parts[0].startswith("__Host-citizen=") and len(parts[0]) > 50
    assert {"HttpOnly", "Secure", "SameSite=Strict", "Path=/"} <= set(parts)
    max_age = int(next(p for p in parts if p.startswith("Max-Age=")).split("=")[1])
    assert 0 < max_age <= 3600
    assert not any(p.lower().startswith("domain") for p in parts)


def test_a_wrong_code_and_an_unknown_ncrp_get_the_same_answer(db):
    submit()
    a = wrong()
    b = wrong(ncrp="39999999999999")
    assert a.status == b.status == 401 and a.body == b.body
    assert not a.cookies and "code" in a.body["error"]


def test_bad_input_is_refused_before_any_check(db):
    for body in ({"ncrp": NCRP}, {"ncrp": NCRP, "code": 5}, {"ncrp": "", "code": "x"},
                 {"ncrp": NCRP, "code": "x", "extra": 1}):
        assert call("session", body=body).status == 400


def test_wrong_codes_for_one_ncrp_slow_down_and_the_wait_grows(db, clock):
    code = submit()["tracking_code"]
    for _ in range(limits.FREE_TRIES["signin-ncrp"]):
        assert wrong(client=f"198.51.100.{clock[0] % 200}").status == 401
        clock[0] += 1
    res = call("session", body={"ncrp": NCRP, "code": code}, client="192.0.2.1")
    assert res.status == 429  # even the right code waits: guessing cannot be told apart
    first_wait = int(res.headers["Retry-After"])
    assert 0 < first_wait <= limits.FIRST_WAIT and "try again" in res.body["error"]
    clock[0] += first_wait
    assert wrong(client="192.0.2.2").status == 401
    second_wait = int(wrong(client="192.0.2.3").headers["Retry-After"])
    assert second_wait > first_wait


def test_the_wait_is_capped_and_never_permanent(db, clock):
    code = submit()["tracking_code"]
    waits = []
    for i in range(40):  # each wrong try as soon as the last wait ends: uncapped, the wait would pass a day
        res = wrong(client=f"192.0.2.{i}")
        if res.status == 429:
            waits.append(int(res.headers["Retry-After"]))
            clock[0] += waits[-1]
    assert waits[0] == limits.FIRST_WAIT and waits == sorted(waits)
    assert waits.count(limits.MAX_WAIT) >= 5 and max(waits) == limits.MAX_WAIT
    # Once the last wait is over, the right code still signs in: the wait always ends.
    assert call("session", body={"ncrp": NCRP, "code": code}, client="192.0.2.251").status == 200


def test_one_connection_trying_many_ncrp_numbers_slows_down_too(db, clock):
    for i in range(limits.FREE_TRIES["signin-client"]):
        assert wrong(ncrp=f"3{i:013d}").status == 401
    assert wrong(ncrp="35555555555555").status == 429


def test_signing_in_clears_the_ncrp_count(db, clock):
    code = submit()["tracking_code"]
    for _ in range(limits.FREE_TRIES["signin-ncrp"] - 1):
        wrong(client="192.0.2.9")
    assert call("session", body={"ncrp": NCRP, "code": code}).status == 200
    for _ in range(limits.FREE_TRIES["signin-ncrp"] - 1):
        assert wrong(client="192.0.2.10").status == 401


def test_each_complaint_under_one_ncrp_signs_in_with_its_own_code(db):
    first = submit()["tracking_code"]
    second = call("complaints", body={"ncrp": NCRP, "story": "a second one"}, client="192.0.2.50")
    cookie_a = sign_in(NCRP, first)
    cookie_b = sign_in(NCRP, second.body["tracking_code"])
    a = call("my-case", method="GET", cookie=cookie_a).body
    b = call("my-case", method="GET", cookie=cookie_b).body
    assert a["reference"] != b["reference"] and b["sent"]["story"] == "a second one"


def test_logout_ends_the_session_and_clears_the_cookie(db):
    cookie = sign_in(NCRP, submit()["tracking_code"])
    assert call("my-case", method="GET", cookie=cookie).status == 200
    res = call("logout", cookie=cookie)
    assert res.status == 200 and "Max-Age=0" in res.cookies[0]
    assert call("my-case", method="GET", cookie=cookie).status == 401
    assert call("logout").status == 200  # signing out twice is fine


def test_a_session_expires(db, clock):
    cookie = sign_in(NCRP, submit()["tracking_code"])
    clock[0] += limits.SESSION_SECONDS + 1
    assert call("my-case", method="GET", cookie=cookie).status == 401


def test_more_complaints_under_one_ncrp_never_shut_out_the_first_code(db, clock):
    first = submit()["tracking_code"]
    n = 1
    while n < limits.CODES_PER_NCRP:  # someone sending more under the same number, day after day
        res = call("complaints", body={"ncrp": NCRP, "story": "spam"}, client=f"198.51.100.{n}")
        if res.status == 429:
            clock[0] += limits.WINDOW + 1
            continue
        assert res.status == 201, res.body
        n += 1
    assert call("my-case", method="GET", cookie=sign_in(NCRP, first, client="192.0.2.77")).status == 200


def test_signing_in_takes_the_same_checks_however_many_complaints_an_ncrp_has(db, clock, monkeypatch):
    from _lib import codes
    runs = []
    real = codes.hashlib.scrypt
    monkeypatch.setattr(codes.hashlib, "scrypt", lambda *a, **k: runs.append(1) or real(*a, **k))
    counts = []
    for i, made in enumerate((0, 1, 3)):
        ncrp = f"3{i:013d}"
        for j in range(made):
            clock[0] += limits.WINDOW + 1
            call("complaints", body={"ncrp": ncrp, "story": "x"}, client=f"198.51.100.{i * 10 + j}")
        runs.clear()
        assert wrong(ncrp=ncrp, client=f"192.0.2.{i}").status == 401
        counts.append(len(runs))
    assert counts[0] == counts[1] == counts[2] == limits.CODES_PER_NCRP
