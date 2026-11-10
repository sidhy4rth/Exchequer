"""A case reference on every live action by a signed-in officer, and each
officer's own hourly and daily limits (case_refs.py, rate_limit.py).

A signed-in officer starts a live trace, a batch, a watch, a payment search
or a recheck only under a case reference (an FIR, NCRP or GD number). It is
kept like the NCRP number: in the case's intake, withheld from other readers,
never in a URL or a log line; the audit trail gets it masked. Demo callers
are unchanged. Throwaway SQLite file, stub pipeline: no network.
"""
from __future__ import annotations

import logging
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import (accounts, audit, case_refs, config, models, ownership, payment_search, pipeline, rate_limit,
                 second_provider, watchlist)
from app.main import app
from app.routes import batches as batch_routes

OFFICER_PW = "officer-password-long-2"
ADMIN_PW = "admin-password-long-1"
CSRF = {accounts.CSRF_HEADER: "1"}
BROWSER = {ownership.OWNER_HEADER: "b" * 32}
ELSEWHERE = {ownership.OWNER_HEADER: "z" * 32}
SCAMMER = "0x" + "5" * 40
REF = "FIR 0457/2026"
CASE = {"address": SCAMMER, "chain": "ethereum", "asset": "ETH", "exchange": "Binance", "direction": "outgoing"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True))
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**4)
    monkeypatch.setattr(pipeline, "run_trace", lambda request: dict(CASE))
    monkeypatch.setattr(watchlist, "chain_head", lambda *a, **k: None)  # never a real provider
    for limiter in rate_limit.LOGIN_LIMITS:
        limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        unit = accounts.create_unit("Cyber Cell North")
        other = accounts.create_unit("Cyber Cell South")
        admin, _ = accounts.create_officer("admin@example.org", "Asha Admin", unit.id, "admin", password=ADMIN_PW)
        officer, _ = accounts.create_officer("officer@example.org", "Om Officer", unit.id, "officer",
                                             password=OFFICER_PW)
        c.ids = {"unit": unit.id, "other": other.id, "admin": admin.id, "officer": officer.id}
        yield c
    # A batch a test started runs on in its own thread. Let it end here, while
    # this store is still the store: one left running would write into the
    # next test's store (before it has its tables) and, still active for this
    # browser, refuse that test's batch with a 429.
    assert wait_for(lambda: not batch_routes._active), "a batch thread outlived its test"


def wait_for(cond, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def sign_in(client, email="officer@example.org", password=OFFICER_PW):
    assert client.post("/auth/login", json={"email": email, "password": password}, headers=CSRF).status_code == 200
    return client


def trace(client, **body):
    return client.post("/trace", json={"address": SCAMMER, **body}, headers=BROWSER)


@pytest.fixture
def audited(monkeypatch):
    calls = []
    real = audit.record
    monkeypatch.setattr(audit, "record", lambda event, **kw: (calls.append((event, kw)), real(event, **kw)))
    return calls


# -- the reference itself --------------------------------------------------------------
@pytest.mark.parametrize("raw, kept", [("FIR 0457/2026", "FIR 0457/2026"), ("  gd  12-2026 ", "gd 12-2026"),
                                       ("31911250012345", "31911250012345"), ("", None), (None, None)])
def test_a_reference_is_read_as_entered_with_its_spacing_tidied(raw, kept):
    assert case_refs.shape(raw) == kept


@pytest.mark.parametrize("raw", ["FIR", "no digits here", "FIR 1<script>", "x" * 41, "FIR 12\n34"])
def test_a_reference_that_is_not_one_is_refused(raw):
    with pytest.raises(ValueError, match="FIR, NCRP or GD number"):
        case_refs.shape(raw)


def test_the_masked_reference_shows_only_its_last_three_characters():
    assert case_refs.mask(REF) == "****026"
    assert case_refs.mask("GD 12") == "****"
    assert case_refs.mask(None) is None


# -- required for officers, unchanged for demo -------------------------------------------
def test_an_officer_cannot_start_a_live_trace_without_a_case_reference(store):
    sign_in(store)
    for path in ("/trace", "/trace/jobs"):
        response = store.post(path, json={"address": SCAMMER}, headers=BROWSER)
        assert response.status_code == 400
        assert "case reference" in response.json()["detail"]
    assert rate_limit.traces.remaining("testclient") == config.TRACES_PER_HOUR_PER_CLIENT  # nothing charged


def test_an_officers_reference_is_kept_with_the_case_and_withheld_from_strangers(store):
    sign_in(store)
    body = trace(store, case_ref=REF).json()
    assert body["intake"]["case_ref"] == REF
    case_id = body["case_id"]
    assert store.get(f"/trace/{case_id}", headers=BROWSER).json()["intake"]["case_ref"] == REF
    stranger = TestClient(app, base_url="https://testserver").get(f"/trace/{case_id}", headers=ELSEWHERE).json()
    assert stranger["intake"]["case_ref"] is None and "intake.case_ref" in stranger["redacted"]


def test_a_demo_trace_needs_no_reference_and_keeps_none_it_is_sent(store):
    assert trace(store).status_code == 200
    body = trace(store, case_ref=REF).json()
    assert (body.get("intake") or {}).get("case_ref") is None  # no police reference on an anonymous trace


def test_a_malformed_reference_is_refused_without_being_echoed(store):
    sign_in(store)
    response = trace(store, case_ref="<b>FIR 12</b>")
    assert response.status_code == 422 and "<b>" not in response.text


def test_an_officer_needs_a_reference_for_a_batch_a_watch_a_search_and_a_recheck(store):
    sign_in(store)
    models.save_case("mine", SCAMMER, dict(CASE), owner_hash=ownership.owner_hash("b" * 32))
    row = {"address": SCAMMER, "chain": "ethereum", "asset": "ETH", "direction": "outgoing", "depth": 1}
    search = {"chain": "ethereum", "asset": "ETH", "wallet": SCAMMER, "amount": "1.5",
              "from": "2026-11-01T00:00:00+05:30", "to": "2026-11-02T00:00:00+05:30"}
    for path, body in (("/batches", {"rows": [row]}), ("/watches", {"address": SCAMMER, "chain": "ethereum"}),
                       ("/payments/search", search), ("/trace/mine/recheck", None)):
        response = store.post(path, json=body, headers=BROWSER)
        assert response.status_code == 400, path
        assert "case reference" in response.json()["detail"], path


def test_a_demo_watch_needs_no_reference(store):
    assert store.post("/watches", json={"address": SCAMMER, "chain": "ethereum"}, headers=BROWSER).status_code == 201


def test_an_officer_watch_or_recheck_of_their_own_case_uses_its_reference(store, monkeypatch, audited):
    sign_in(store)
    case_id = trace(store, case_ref=REF).json()["case_id"]
    watch = store.post("/watches", json={"address": SCAMMER, "chain": "ethereum", "case_id": case_id}, headers=BROWSER)
    assert watch.status_code == 201
    monkeypatch.setattr(second_provider, "cited_transfers", lambda result: ("ethereum", [{"hash": "0x" + "c" * 64}]))
    monkeypatch.setattr(second_provider, "rereadable", lambda chain, cited: True)
    monkeypatch.setattr(second_provider, "allowance_spent", lambda chain, client: None)
    monkeypatch.setattr(second_provider, "recheck", lambda result, client: {
        "checked": 1, "cited": 1, "counts": {"matches": 1, "error": 0}, "transfers": []})
    assert store.post(f"/trace/{case_id}/recheck", headers=BROWSER).status_code == 200
    masked = {event: kw.get("detail", {}).get("case_ref") for event, kw in audited}
    assert masked["case.trace"] == masked["watch.create"] == masked["case.recheck"] == "****026"


def test_an_officer_search_with_a_reference_is_audited_masked(store, monkeypatch, audited):
    sign_in(store)
    monkeypatch.setattr(payment_search, "search", lambda *a, **k: {"matches": [], "scanned": 0, "complete": True})
    response = store.post("/payments/search", headers=BROWSER, json={
        "chain": "ethereum", "asset": "ETH", "wallet": SCAMMER, "amount": "1.5", "case_ref": REF,
        "from": "2026-11-01T00:00:00+05:30", "to": "2026-11-02T00:00:00+05:30"})
    assert response.status_code == 200
    assert [kw["detail"]["case_ref"] for event, kw in audited if event == "payment.search"] == ["****026"]


def test_the_reference_never_reaches_a_log_line(store, caplog):
    caplog.set_level(logging.DEBUG)
    sign_in(store)
    trace(store, case_ref=REF)
    assert "audit case.trace" in caplog.text
    assert "0457" not in caplog.text and REF not in caplog.text


# -- per-officer limits -------------------------------------------------------------------
@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(config, "OFFICER_LIMITS", {"trace": (2, 3), "watch": (1, 5), "recheck": (1, 5), "check": (3, 9)})


def test_an_officer_is_held_to_their_own_hourly_trace_limit(store, small):
    sign_in(store)
    assert [trace(store, case_ref=REF).status_code for _ in range(2)] == [200, 200]
    refused = trace(store, case_ref=REF)
    assert refused.status_code == 429 and int(refused.headers["Retry-After"]) > 0
    assert refused.json()["detail"].startswith("You have started 2 live traces in the last hour")
    colleague = sign_in(TestClient(app, base_url="https://testserver"), "admin@example.org", ADMIN_PW)
    assert colleague.post("/trace", json={"address": SCAMMER, "case_ref": REF}, headers=ELSEWHERE).status_code == 200


def test_an_officer_is_held_to_their_own_daily_limit(store, monkeypatch):
    monkeypatch.setattr(config, "OFFICER_LIMITS", {**config.OFFICER_LIMITS, "trace": (10, 2)})
    sign_in(store)
    assert [trace(store, case_ref=REF).status_code for _ in range(3)] == [200, 200, 429]
    assert "in the last 24 hours" in trace(store, case_ref=REF).json()["detail"]


def test_demo_callers_are_held_only_by_the_connection_and_site_limits(store, small):
    assert [trace(store).status_code for _ in range(4)] == [200] * 4


def test_a_batch_counts_each_row_against_the_officers_limit(store, small):
    sign_in(store)
    rows = [{"address": "0x" + c * 40, "chain": "ethereum", "asset": "ETH", "direction": "outgoing", "depth": 1}
            for c in "123"]
    refused = store.post("/batches", json={"rows": rows, "case_ref": REF}, headers=BROWSER)
    assert refused.status_code == 429
    assert "needs 3 live traces" in refused.json()["detail"] and "2 more" in refused.json()["detail"]


def test_an_officer_is_held_to_their_own_watch_limit(store, small):
    sign_in(store)
    watch = {"address": SCAMMER, "chain": "ethereum", "case_ref": REF}
    assert store.post("/watches", json=watch, headers=BROWSER).status_code == 201
    refused = store.post("/watches", json={**watch, "address": "0x" + "6" * 40}, headers=BROWSER)
    assert refused.status_code == 429 and "You have created 1 watch in the last hour" in refused.json()["detail"]


def test_a_refusal_further_down_gives_back_the_officers_share():
    officer = rate_limit.OfficerCharge("officer-1", "trace", 5, 5)
    rate_limit.officer_hour["trace"].reset()
    rate_limit.officer_day["trace"].reset()
    full = rate_limit.SlidingWindowLimiter(1, 3600)
    full.check("c")
    assert rate_limit.charge(full, rate_limit.SlidingWindowLimiter(9, 3600), "c", officer=officer)[1] == "client"
    assert rate_limit.officer_hour["trace"].remaining("officer-1", limit=5) == 5
    assert rate_limit.officer_day["trace"].remaining("officer-1", limit=5) == 5


# -- the admin's per-unit override ----------------------------------------------------------
def limits_url(store, unit="unit"):
    return f"/admin/units/{store.ids[unit]}/limits"


def test_an_admin_reads_a_units_limits_and_the_defaults(store, small):
    sign_in(store, "admin@example.org", ADMIN_PW)
    body = store.get(limits_url(store)).json()
    assert body["unit"] == {"id": store.ids["unit"], "name": "Cyber Cell North"}
    assert body["defaults"]["trace"] == {"per_hour": 2, "per_day": 3}
    assert body["limits"]["trace"] == {"per_hour": 2, "per_day": 3, "set_for_unit": False}


def test_an_admins_override_holds_that_units_officers_only(store, small, audited):
    sign_in(store, "admin@example.org", ADMIN_PW)
    response = store.put(limits_url(store), headers=CSRF, json={"trace": {"per_hour": 1, "per_day": 4}})
    assert response.status_code == 200
    assert response.json()["limits"]["trace"] == {"per_hour": 1, "per_day": 4, "set_for_unit": True}
    assert ("admin.unit_limits", {"detail": {"by": store.ids["admin"], "unit_id": store.ids["unit"],
                                             "set": ["trace"]}}) in audited
    store.cookies.clear()
    sign_in(store)
    assert [trace(store, case_ref=REF).status_code for _ in range(2)] == [200, 429]
    sign_in(store, "admin@example.org", ADMIN_PW)
    store.patch(f"/admin/officers/{store.ids['officer']}", headers=CSRF, json={"unit_id": store.ids["other"]})
    sign_in(store)  # now in the other unit: the default of 2 an hour, one already spent
    assert trace(store, case_ref=REF).status_code == 200


def test_clearing_an_override_brings_back_the_default(store, small):
    sign_in(store, "admin@example.org", ADMIN_PW)
    store.put(limits_url(store), headers=CSRF, json={"trace": {"per_hour": 1, "per_day": 4}})
    body = store.put(limits_url(store), headers=CSRF, json={"trace": None}).json()
    assert body["limits"]["trace"] == {"per_hour": 2, "per_day": 3, "set_for_unit": False}


@pytest.mark.parametrize("body", [{"trace": {"per_hour": 0, "per_day": 4}}, {"trace": {"per_hour": 5, "per_day": 4}},
                                  {"spend": {"per_hour": 1, "per_day": 1}}, {"trace": {"per_hour": 1}}])
def test_an_override_that_makes_no_sense_is_refused(store, body):
    sign_in(store, "admin@example.org", ADMIN_PW)
    assert store.put(limits_url(store), headers=CSRF, json=body).status_code == 422


def test_only_an_admin_sets_limits_and_only_with_the_request_header(store):
    assert store.get(limits_url(store)).status_code == 401
    sign_in(store)
    assert store.get(limits_url(store)).status_code == 403
    assert store.put(limits_url(store), headers=CSRF, json={}).status_code == 403
    store.cookies.clear()
    sign_in(store, "admin@example.org", ADMIN_PW)
    assert store.put(limits_url(store), json={}).status_code == 403  # no X-Exchequer-Request
    assert store.put("/admin/units/999/limits", headers=CSRF, json={}).status_code == 404


# -- fix round 1 --------------------------------------------------------------------------
def wait_batch(client, batch_id):
    for _ in range(200):
        body = client.get(f"/batches/{batch_id}", headers=BROWSER).json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("batch did not finish")


def test_each_batch_row_keeps_its_own_reference(store, audited):
    sign_in(store)
    rows = [{"address": "0x" + c * 40, "chain": "ethereum", "asset": "ETH", "reference": ref}
            for c, ref in (("1", "NCRP-2026-0001"), ("2", "NCRP-2026-0002"), ("3", ""))]
    refused = store.post("/batches", json={"rows": rows}, headers=BROWSER)  # row 3 has none of its own
    assert refused.status_code == 400 and "1 row has no case reference of its own" in refused.json()["detail"]
    started = store.post("/batches", json={"rows": rows, "case_ref": REF}, headers=BROWSER)
    assert started.status_code == 202
    done = wait_batch(store, started.json()["batch_id"])
    kept = [store.get(f"/trace/{r['case_id']}", headers=BROWSER).json()["intake"]["case_ref"] for r in done["rows"]]
    assert kept == ["NCRP-2026-0001", "NCRP-2026-0002", REF]  # the batch's own only for the row without
    masked = sorted(kw["detail"]["case_ref"] for event, kw in audited if event == "case.trace")
    assert masked == ["****001", "****002", "****026"]


def test_a_batch_whose_rows_all_carry_a_reference_needs_no_batch_reference(store):
    sign_in(store)
    rows = [{"address": "0x" + c * 40, "chain": "ethereum", "reference": f"GD {c}/2026"} for c in "12"]
    assert store.post("/batches", json={"rows": rows}, headers=BROWSER).status_code == 202


def test_a_demo_batch_keeps_no_reference_from_its_rows(store):
    rows = [{"address": "0x" + "1" * 40, "chain": "ethereum", "reference": "NCRP-2026-0001"}]
    started = store.post("/batches", json={"rows": rows}, headers=BROWSER)
    done = wait_batch(store, started.json()["batch_id"])
    case = store.get(f"/trace/{done['rows'][0]['case_id']}", headers=BROWSER).json()
    assert (case.get("intake") or {}).get("case_ref") is None


def test_a_recheck_never_runs_under_a_reference_the_officer_cannot_read(store, monkeypatch):
    demo = sorted(ownership.demo_addresses())[0]
    # A public case (a demo address, no owner) that the other unit traced under its reference.
    models.save_case("theirs", demo, {**CASE, "address": demo, "intake": {"mode": "address", "case_ref": REF}},
                     unit_id=store.ids["other"])
    monkeypatch.setattr(second_provider, "cited_transfers", lambda result: ("ethereum", [{"hash": "0x" + "c" * 64}]))
    monkeypatch.setattr(second_provider, "rereadable", lambda chain, cited: True)
    monkeypatch.setattr(second_provider, "allowance_spent", lambda chain, client: None)
    monkeypatch.setattr(second_provider, "recheck", lambda result, client: {
        "checked": 1, "cited": 1, "counts": {"matches": 1, "error": 0}, "transfers": []})
    sign_in(store)
    refused = store.post("/trace/theirs/recheck", headers=BROWSER)
    assert refused.status_code == 400 and "case reference" in refused.json()["detail"]
    assert store.post("/trace/theirs/recheck", json={"case_ref": "GD 77/2026"}, headers=BROWSER).status_code == 200


def test_an_officers_manual_watch_checks_count_against_their_own_limit(store, monkeypatch):
    monkeypatch.setattr(config, "OFFICER_LIMITS", {**config.OFFICER_LIMITS, "watch": (5, 5), "check": (1, 5)})
    monkeypatch.setattr(watchlist, "check_watch", lambda watch_id, *a, **k: 0)
    sign_in(store)
    ids = [store.post("/watches", json={"address": "0x" + c * 40, "chain": "ethereum", "case_ref": REF},
                      headers=BROWSER).json()["watch_id"] for c in "12"]
    assert store.post(f"/watches/{ids[0]}/check", headers=BROWSER).status_code == 200
    refused = store.post(f"/watches/{ids[1]}/check", headers=BROWSER)
    assert refused.status_code == 429 and "Retry-After" in refused.headers
    assert refused.json()["detail"].startswith("You have made 1 manual check in the last hour")


def test_an_admin_can_set_a_units_manual_check_limit(store):
    sign_in(store, "admin@example.org", ADMIN_PW)
    body = store.put(limits_url(store), headers=CSRF, json={"check": {"per_hour": 3, "per_day": 9}}).json()
    assert body["limits"]["check"] == {"per_hour": 3, "per_day": 9, "set_for_unit": True}
