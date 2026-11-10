"""Second-officer sign-off on an urgent freeze letter (app/freeze_requests.py).

An urgent freeze letter asks an exchange or Tether to hold money now, before
any formal request, so a forged one is the cheapest fake police request
there is. It is ready only once a second, signed-in officer of the same unit
approves it: drafted -> awaiting_signoff -> ready, and only then sent. The
drafter cannot approve their own letter, nor can a demo caller or an admin.
Throwaway SQLite file, no network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import accounts, audit, models, ownership, rate_limit
from app import freeze_requests as fr
from app.auth import User
from app.main import app
from app.request_letters import BLANK, draft

from test_freeze_letters import usdt_case

PW = "officer-password-long-2"
CSRF = {accounts.CSRF_HEADER: "1"}
OWN_BROWSER, OTHER_BROWSER = "a" * 32, "b" * 32
AT = "2026-11-10T09:00:00+00:00"  # 14:30 in India


def browser(key):
    return {ownership.OWNER_HEADER: key}


@pytest.fixture
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(audit, "record", lambda event, *, case_id=None, detail=None: seen.append((event, case_id, detail)))
    return seen


@pytest.fixture
def unit(tmp_path, monkeypatch):
    """Cyber Cell North: Asha drafts, Bina (officer) and Chand (supervisor)
    may approve, Dev is its admin; Esha works in Cyber Cell South. The case
    was traced by Asha, signed in on her own browser."""
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**4)
    monkeypatch.setattr(fr, "_now", lambda: AT)
    for limiter in rate_limit.LOGIN_LIMITS:
        limiter.reset()
    rate_limit.request_writes.reset()
    models.init_db()
    north, south = accounts.create_unit("Cyber Cell North"), accounts.create_unit("Cyber Cell South")
    people = {}
    for key, name, unit_id, role in [("asha", "Asha Rao", north.id, "officer"), ("bina", "Bina Iyer", north.id, "officer"),
                                     ("chand", "Chand Pal", north.id, "supervisor"), ("dev", "Dev Admin", north.id, "admin"),
                                     ("esha", "Esha Sen", south.id, "officer")]:
        officer, _ = accounts.create_officer(f"{key}@example.org", name, unit_id, role, password=PW)
        people[key] = officer.id
    models.save_case("case-1", usdt_case()["address"], usdt_case(), owner_hash=ownership.owner_hash(OWN_BROWSER),
                     officer_id=people["asha"], unit_id=north.id)
    return people


def signed_in(who):
    client = TestClient(app, base_url="https://testserver")
    if who != "demo":
        assert client.post("/auth/login", json={"email": f"{who}@example.org", "password": PW}, headers=CSRF).status_code == 200
    client.headers.update(browser(OWN_BROWSER if who in ("asha", "demo") else OTHER_BROWSER))
    return client


def drafted(client, kind="exchange-freeze", ask=True):
    made = client.post("/requests", json={"case_id": "case-1", "recipient": "Binance", "kind": kind})
    assert made.status_code == 201 and made.json()["status"] == "drafted"
    rid = made.json()["request_id"]
    if ask:
        asked = client.patch(f"/requests/{rid}", json={"status": "awaiting_signoff"})
        assert asked.status_code == 200 and asked.json()["status"] == "awaiting_signoff"
    return rid


def sign(client, rid):
    return client.post(f"/requests/{rid}/signoff", headers=CSRF)


# -- the state machine -------------------------------------------------------------
@pytest.mark.parametrize("kind", ["exchange-freeze", "tether-freeze", "instant-freeze"])
def test_every_urgent_freeze_kind_needs_a_sign_off_and_no_other_does(kind):
    assert fr.needs_signoff(kind)
    assert not any(fr.needs_signoff(k) for k in ("exchange", "tether", "other", "instant"))


def test_an_urgent_letter_moves_drafted_awaiting_ready_then_sent(unit, events):
    asha = signed_in("asha")
    rid = drafted(asha)
    done = sign(signed_in("bina"), rid)
    assert done.status_code == 200 and done.json()["status"] == "ready"
    assert done.json()["signoff"] == {"by": "Bina Iyer", "at": AT}
    sent = asha.patch(f"/requests/{rid}", json={"status": "sent"})
    assert sent.status_code == 200 and sent.json()["sent_at"]
    assert [h["status"] for h in sent.json()["history"]] == ["drafted", "awaiting_signoff", "ready", "sent"]
    # Each step is audited, the sign-off by request id with no name in it.
    assert [e[0] for e in events if e[0].startswith("request.")] == [
        "request.create", "request.signoff_ask", "request.signoff", "request.update"]
    assert ("request.signoff", "case-1", {"request_id": rid}) in events


@pytest.mark.parametrize("status", ["sent", "acknowledged", "frozen", "declined", "ready"])
def test_an_urgent_letter_cannot_skip_its_sign_off(unit, status):
    asha = signed_in("asha")
    for rid in (drafted(asha, ask=False), drafted(asha, kind="tether-freeze")):
        refused = asha.patch(f"/requests/{rid}", json={"status": status})
        assert refused.status_code == 400 and "second officer" in refused.json()["detail"]
    made = asha.post("/requests", json={"case_id": "case-1", "recipient": "Binance", "kind": "exchange-freeze", "status": status})
    assert made.status_code == 400 and "second officer" in made.json()["detail"]


def test_an_urgent_letter_can_be_withdrawn_or_closed_before_its_sign_off(unit):
    asha = signed_in("asha")
    rid = drafted(asha)
    assert asha.patch(f"/requests/{rid}", json={"status": "drafted"}).json()["status"] == "drafted"
    assert asha.patch(f"/requests/{rid}", json={"status": "closed"}).json()["status"] == "closed"


def test_other_letters_have_no_sign_off_states(unit):
    asha = signed_in("asha")
    rid = drafted(asha, kind="exchange", ask=False)
    refused = asha.patch(f"/requests/{rid}", json={"status": "awaiting_signoff"})
    assert refused.status_code == 400 and "only an urgent freeze letter" in refused.json()["detail"].lower()
    assert asha.patch(f"/requests/{rid}", json={"status": "sent"}).status_code == 200
    assert sign(signed_in("bina"), rid).status_code == 400


def test_only_a_letter_awaiting_its_sign_off_can_be_signed(unit):
    asha, bina = signed_in("asha"), signed_in("bina")
    rid = drafted(asha, ask=False)
    early = sign(bina, rid)
    assert early.status_code == 409 and "not waiting" in early.json()["detail"]
    asha.patch(f"/requests/{rid}", json={"status": "awaiting_signoff"})
    assert sign(bina, rid).status_code == 200
    assert sign(signed_in("chand"), rid).status_code == 409  # signed once is enough


# -- who may sign ------------------------------------------------------------------
@pytest.mark.parametrize("who", ["bina", "chand"])
def test_another_officer_or_supervisor_of_the_unit_signs_it_off(unit, who):
    assert sign(signed_in(who), drafted(signed_in("asha"))).json()["status"] == "ready"


@pytest.mark.parametrize("who,code,reason", [
    ("asha", 403, "you drafted this letter"),
    ("dev", 403, "only an officer or a supervisor"),
    ("esha", 403, "only an officer of the unit that drafted"),
    ("demo", 403, "demo"),
])
def test_the_drafter_an_admin_another_unit_and_a_demo_caller_cannot(unit, events, who, code, reason):
    rid = drafted(signed_in("asha"))
    refused = sign(signed_in(who), rid)
    assert refused.status_code == code and reason in refused.json()["detail"].lower()
    assert signed_in("asha").get("/trace/case-1/requests").json()["requests"][0]["status"] == "awaiting_signoff"
    assert any(e[0] == "request.signoff_refused" for e in events)


def test_a_letter_drafted_without_signing_in_cannot_be_put_up_for_sign_off(unit, events):
    # No unit's officer could ever sign it, so the ask is refused up front
    # rather than leaving a row that waits for good.
    demo = signed_in("demo")
    rid = drafted(demo, ask=False)
    asked = demo.patch(f"/requests/{rid}", json={"status": "awaiting_signoff"})
    assert asked.status_code == 400 and "without signing in" in asked.json()["detail"]
    made = demo.post("/requests", json={"case_id": "case-1", "recipient": "Tether", "kind": "tether-freeze",
                                        "status": "awaiting_signoff"})
    assert made.status_code == 400 and "sign in" in made.json()["detail"].lower()
    assert not any(e[0] == "request.signoff_ask" for e in events)
    # The Letters tab is told why before anyone presses anything.
    seen = demo.get("/trace/case-1/requests").json()
    assert "sign in" in seen["ask_reason"].lower()
    assert "without signing in" in seen["requests"][0]["ask_reason"]
    officer = signed_in("asha").get("/trace/case-1/requests").json()
    assert officer["ask_reason"] is None


def test_a_demo_drafter_of_a_row_with_no_unit_is_told_to_sign_in_and_draft_again():
    # The row's missing unit is the real reason, not that the caller is a demo user.
    row = models.FreezeRequest(kind="exchange-freeze", status="awaiting_signoff", unit_id=None, officer_id=None)
    code, reason = fr.refusal(row, User(id="demo-x", role="investigator", unit="demo", owner_hash="h"))
    assert code == 403 and "without signing in" in reason and "draft it again" in reason


def test_an_ask_made_while_logging_the_letter_is_audited_as_an_ask(unit, events):
    asha = signed_in("asha")
    made = asha.post("/requests", json={"case_id": "case-1", "recipient": "Binance", "kind": "exchange-freeze",
                                        "status": "awaiting_signoff"})
    assert made.status_code == 201
    rid = made.json()["request_id"]
    assert ("request.signoff_ask", "case-1", {"request_id": rid}) in events
    # Asked again while it already waits: nothing moved, so no second ask.
    again = asha.patch(f"/requests/{rid}", json={"status": "awaiting_signoff"})
    assert again.status_code == 200
    assert [e[0] for e in events if e[0] == "request.signoff_ask"] == ["request.signoff_ask"]


def test_a_sign_off_needs_the_request_header(unit):
    rid = drafted(signed_in("asha"))
    assert signed_in("bina").post(f"/requests/{rid}/signoff").status_code == 403
    assert sign(signed_in("bina"), "no-such-request").status_code == 404


# -- what each caller sees ---------------------------------------------------------
def test_the_unit_sees_a_letter_awaiting_sign_off_and_who_may_sign_it(unit):
    rid = drafted(signed_in("asha"))
    own = signed_in("asha").get("/trace/case-1/requests").json()["requests"]
    assert own[0]["mine"] is True and own[0]["can_sign_off"] is False
    assert "you drafted" in own[0]["signoff_reason"].lower()
    seen = signed_in("bina").get("/trace/case-1/requests").json()["requests"]
    assert [r["request_id"] for r in seen] == [rid]
    assert seen[0]["mine"] is False and seen[0]["can_sign_off"] is True and seen[0]["signoff_reason"] is None
    assert signed_in("esha").get("/trace/case-1/requests").json()["count"] == 0
    assert TestClient(app).get("/trace/case-1/requests", headers=browser(OTHER_BROWSER)).json()["count"] == 0
    # Another officer of the unit sees it, but only the drafter's browser changes it.
    assert signed_in("bina").patch(f"/requests/{rid}", json={"notes": "x"}).status_code == 404
    # Signed, it stays in the unit's view, with who approved it.
    sign(signed_in("chand"), rid)
    [after] = signed_in("bina").get("/trace/case-1/requests").json()["requests"]
    assert after["status"] == "ready" and after["signoff"] == {"by": "Chand Pal", "at": AT}


# -- the letter's text -------------------------------------------------------------
def test_the_letter_says_it_awaits_approval_until_it_is_signed():
    text = draft("case-1", usdt_case(), "exchange-freeze")
    assert "Awaiting a second officer's approval" in text and "Approved by" not in text
    assert "second officer" not in draft("case-1", usdt_case(), "exchange")


def test_the_signed_letter_names_the_second_officer_with_a_rank_blank_and_ist_time():
    text = draft("case-1", usdt_case(), "tether-freeze", approval={"by": "Bina Iyer", "at": AT})
    assert f"Approved by a second officer: Bina Iyer, {BLANK} (rank), 10 Nov 2026, 14:30 IST" in text
    assert "Awaiting" not in text


def test_the_letter_route_reads_the_sign_off_for_the_drafter_and_the_signer(unit):
    asha, bina = signed_in("asha"), signed_in("bina")

    def letter(client):
        return client.get("/trace/case-1/letter?to=exchange-freeze").text
    assert "Awaiting a second officer's approval" in letter(asha)
    rid = drafted(asha)
    assert "Awaiting a second officer's approval" in letter(asha)
    sign(bina, rid)
    for client in (asha, bina):
        assert "Approved by a second officer: Bina Iyer" in letter(client)
    assert "Approved by" not in signed_in("esha").get("/trace/case-1/letter?to=exchange-freeze").text
    assert "Approved by" not in asha.get("/trace/case-1/letter?to=tether-freeze").text  # another letter
