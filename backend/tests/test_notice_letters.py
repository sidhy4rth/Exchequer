"""Bank and telecom notices (app/notice_letters.py, POST /trace/{id}/notice).

After an exchange replies, the officer's next letters go to the bank its payouts
reached and to the operator of the phone number on the account. These drafts
follow the exchange letters' rules: facts only from the case and from what the
officer typed, the legal provision a marked blank, "not valid until signed",
and the urgent hold behind a second officer's sign-off. A bank hold is an
attachment of money, so it is refused without the Magistrate's order it rests
on. Account and phone numbers are personal data: they go into the letter and
nowhere else -- not the URL, the file name, the audit row or the logs.
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import freeze_requests, models, ownership
from app.main import app
from app.notice_letters import BANK_FREEZE, BANK_INFO, NOTICES, TELECOM, NoticeError, draft, fingerprint, inr
from app.request_letters import AWAITING, BLANK, NOT_VALID

from test_request_letters import case

ACCOUNT, IFSC, PHONE = "123456789012", "SBIN0001234", "9876543210"
SOURCE = "Binance reply ref LE-2026-0042 dated 10 Nov 2026"
ORDER = "Order 17/2026 dated 11 Nov 2026, JMFC Court, Bengaluru"


def bank(**over):
    details = {"bank": "State Bank of India", "account": ACCOUNT, "ifsc": IFSC, "source": SOURCE,
               "period_from": "2026-10-01", "period_to": "2026-11-10"}
    details.update(over)
    return details


def hold(**over):
    """A bank hold's details, as the officer types them (the period is not part of a hold)."""
    details = {"bank": "State Bank of India", "account": ACCOUNT, "ifsc": IFSC, "source": SOURCE, "order": ORDER,
               "amount": "2,50,000"}
    details.update(over)
    return details


def telecom(**over):
    details = {"operator": "Example Telecom Ltd", "phone": PHONE, "source": SOURCE,
               "period_from": "2026-10-01", "period_to": "2026-11-10"}
    details.update(over)
    return details


def flat(text):
    return " ".join(text.split())


# -- the bank information notice ----------------------------------------------------------
def test_the_bank_notice_names_the_account_and_why_the_officer_is_asking():
    text = draft("case-1", case(), BANK_INFO, bank())
    for fact in (ACCOUNT, IFSC, "State Bank of India", SOURCE, "01 Oct 2026", "10 Nov 2026"):
        assert fact in text
    assert NOT_VALID in text
    assert "statement" in text and "KYC" in text


def test_the_bank_notice_leaves_the_legal_provision_to_the_officer():
    text = flat(draft("case-1", case(), BANK_INFO, bank()))
    assert f"In exercise of the powers under {BLANK}" in text
    assert "officer to confirm" in text


def test_the_bank_notice_ties_itself_to_the_case_and_the_exchange_it_reached():
    text = flat(draft("case-1", case(), BANK_INFO, bank()))
    assert "Exchequer case case-1" in text and "f" * 64 in text
    assert "traces the complainant's funds on chain to Binance" in text


def test_a_case_that_reached_no_exchange_names_none():
    text = draft("case-1", case(exchange=None, exchange_label=None, exchange_address=None), BANK_INFO, bank())
    assert "traces the complainant's funds" not in text and ACCOUNT in text


# -- the urgent bank hold ---------------------------------------------------------------
def test_a_bank_hold_is_refused_without_the_magistrates_order():
    with pytest.raises(NoticeError, match="Magistrate"):
        draft("case-1", case(), BANK_FREEZE, bank())
    with pytest.raises(NoticeError, match="Magistrate"):
        draft("case-1", case(), BANK_FREEZE, bank(order="   "))


def test_a_bank_hold_quotes_the_order_and_waits_for_a_second_officer():
    text = draft("case-1", case(), BANK_FREEZE, bank(order=ORDER))
    assert ORDER in text and ACCOUNT in text and IFSC in text
    assert AWAITING in text and NOT_VALID in text
    assert f"Under {BLANK}" in text


def test_a_signed_off_bank_hold_says_who_approved_it():
    approval = {"by": "SI Rao", "at": "2026-11-12T05:30:00+00:00"}
    text = draft("case-1", case(), BANK_FREEZE, bank(order=ORDER), approval)
    assert AWAITING not in text and "Approved by a second officer: SI Rao" in text


def test_the_hold_amount_is_the_officers_or_a_blank():
    assert f"Amount    : {BLANK}" in draft("case-1", case(), BANK_FREEZE, bank(order=ORDER))
    assert "INR 2,50,000.00" in draft("case-1", case(), BANK_FREEZE, bank(order=ORDER, amount=250000))
    assert "INR 2,50,000.00" in draft("case-1", case(), BANK_FREEZE, bank(order=ORDER, amount="2,50,000"))
    for bad in (-5, 0, True, "nan", "1e400", "about a lakh"):
        with pytest.raises(NoticeError):
            draft("case-1", case(), BANK_FREEZE, bank(order=ORDER, amount=bad))


@pytest.mark.parametrize("value, text", [(1, "1.00"), (999.5, "999.50"), (1000, "1,000.00"), (250000, "2,50,000.00"),
                                         (12345678.5, "1,23,45,678.50")])
def test_rupees_are_grouped_the_indian_way(value, text):
    assert inr(value) == text


# -- the telecom notice -----------------------------------------------------------------
def test_the_telecom_notice_asks_for_the_subscriber_and_the_records_for_the_period():
    text = draft("case-1", case(), TELECOM, telecom())
    for fact in (PHONE, "Example Telecom Ltd", SOURCE, "01 Oct 2026", "10 Nov 2026", NOT_VALID):
        assert fact in text
    assert "subscriber" in text.lower() and "CDR" in text and "IPDR" in text


# -- what the officer types is checked, never guessed ------------------------------------
@pytest.mark.parametrize("to, details", [
    (BANK_INFO, bank(ifsc="SBIN1001234")),  # the fifth character of an IFSC is 0
    (BANK_INFO, bank(ifsc="")),
    (BANK_INFO, bank(account="12-34")),
    (BANK_INFO, bank(bank="")),
    (BANK_INFO, bank(source="")),
    (BANK_INFO, bank(period_from="2026-11-10", period_to="2026-10-01")),
    (BANK_INFO, bank(period_from="yesterday")),
    (TELECOM, telecom(phone="12345")),
    (TELECOM, telecom(operator="")),
])
def test_missing_or_malformed_details_are_refused(to, details):
    with pytest.raises(NoticeError):
        draft("case-1", case(), to, details)


def test_a_phone_number_is_accepted_with_a_country_code_and_spaces():
    assert PHONE in draft("case-1", case(), TELECOM, telecom(phone="+91 98765 43210"))


def test_typed_text_cannot_add_lines_to_the_letter():
    text = draft("case-1", case(), BANK_INFO, bank(source="ref 1\nTo        : Someone else"))
    assert "\nTo        : Someone else" not in text


def test_an_unknown_notice_is_refused():
    with pytest.raises(NoticeError):
        draft("case-1", case(), "exchange", bank())


def test_the_notices_can_be_logged_as_requests_and_only_the_hold_needs_a_sign_off():
    assert set(NOTICES) <= set(freeze_requests.KINDS)
    assert "bank" not in freeze_requests.KINDS  # test_freeze_requests keeps "bank" as an unknown kind
    assert [freeze_requests.needs_signoff(n) for n in (BANK_FREEZE, BANK_INFO, TELECOM)] == [True, False, False]


# -- the route --------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'n.db'}", future=True))
    models.init_db()
    models.save_case("case-1", case()["address"], case())
    return TestClient(app)


OWNER = {ownership.OWNER_HEADER: "a" * 32}


def test_the_route_returns_the_draft_as_a_download_named_without_personal_data(client):
    r = client.post("/trace/case-1/notice", json={"to": BANK_INFO, **bank()}, headers=OWNER)
    assert r.status_code == 200 and ACCOUNT in r.text
    disposition = r.headers["content-disposition"]
    assert ACCOUNT not in disposition and IFSC not in disposition and BANK_INFO in disposition
    assert r.headers["cache-control"] == "no-store"


def test_account_and_phone_numbers_stay_out_of_the_audit_log_and_the_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    client.post("/trace/case-1/notice", json={"to": BANK_INFO, **bank()}, headers=OWNER)
    client.post("/trace/case-1/notice", json={"to": TELECOM, **telecom()}, headers=OWNER)
    with models.session() as s:
        rows = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "case.notice_draft")).all()
    assert [json.loads(r.detail) for r in rows] == [{"to": BANK_INFO}, {"to": TELECOM}]
    for secret in (ACCOUNT, IFSC, PHONE, SOURCE):
        assert secret not in caplog.text


def test_the_route_refuses_bad_details_and_an_unknown_case(client):
    assert client.post("/trace/case-1/notice", json={"to": BANK_FREEZE, **bank()}, headers=OWNER).status_code == 400
    assert client.post("/trace/case-1/notice", json={"to": "bank", **bank()}, headers=OWNER).status_code == 400
    assert client.post("/trace/nope/notice", json={"to": BANK_INFO, **bank()}, headers=OWNER).status_code == 404


def test_the_route_shows_a_bank_hold_as_awaiting_sign_off(client):
    r = client.post("/trace/case-1/notice", json={"to": BANK_FREEZE, **bank(order=ORDER)}, headers=OWNER)
    assert r.status_code == 200 and AWAITING in r.text


# -- the whole flow, two officers of one unit (test_freeze_signoff's unit) ---------------
from test_freeze_signoff import drafted, sign, signed_in, unit  # noqa: E402,F401 -- the fixture is used by name


def test_a_bank_hold_becomes_ready_only_once_a_second_officer_signs_it_off(unit):  # noqa: F811 -- the imported fixture
    asha, bina = signed_in("asha"), signed_in("bina")
    notice = {"to": BANK_FREEZE, **bank(order=ORDER)}
    rid = drafted(asha, kind=BANK_FREEZE, details=bank(order=ORDER))
    assert AWAITING in asha.post("/trace/case-1/notice", json=notice).text
    assert sign(asha, rid, bank(order=ORDER)).status_code == 403  # never the drafter
    assert sign(bina, rid, bank(order=ORDER)).status_code == 200
    text = asha.post("/trace/case-1/notice", json=notice).text
    assert AWAITING not in text and "Approved by a second officer: Bina Iyer" in text


@pytest.mark.parametrize("kind", [BANK_INFO, TELECOM])
def test_an_information_notice_is_logged_and_sent_without_a_sign_off(unit, kind):  # noqa: F811 -- the imported fixture
    asha = signed_in("asha")
    rid = drafted(asha, kind=kind, ask=False)
    assert asha.patch(f"/requests/{rid}", json={"status": "sent"}).json()["status"] == "sent"



# -- a sign-off covers the exact details the second officer approved (#132) -------------
OTHER_ACCOUNT, OTHER_ORDER = "998877665544", "Order 18/2026 dated 12 Nov 2026, JMFC Court, Bengaluru"


def notice_for(client, details):
    r = client.post("/trace/case-1/notice", json={"to": BANK_FREEZE, **details})
    assert r.status_code == 200, r.text
    return r.text


@pytest.mark.parametrize("changed", [{"account": OTHER_ACCOUNT}, {"ifsc": "HDFC0000001"}, {"amount": "9,00,000"},
                                     {"amount": ""}, {"order": OTHER_ORDER}, {"bank": "HDFC Bank"},
                                     {"source": "WazirX reply dated 12 Nov 2026"}])
def test_a_sign_off_on_one_set_of_details_does_not_approve_a_hold_with_others(unit, changed):  # noqa: F811
    asha, bina = signed_in("asha"), signed_in("bina")
    rid = drafted(asha, kind=BANK_FREEZE, details=hold())
    assert sign(bina, rid, hold()).status_code == 200
    assert "Approved by a second officer: Bina Iyer" in notice_for(asha, hold())
    other = notice_for(asha, hold(**changed))  # the bug: this used to print the approval too
    assert AWAITING in other and "Approved by" not in other


def test_the_approved_details_still_print_the_approval_however_they_are_typed(unit):  # noqa: F811
    asha, bina = signed_in("asha"), signed_in("bina")
    rid = drafted(asha, kind=BANK_FREEZE, details=hold(ifsc=" sbin0001234 ", account="1234 5678 9012"))
    assert sign(bina, rid, hold(amount="250000")).status_code == 200
    for typed in (hold(), hold(amount=250000), hold(amount="2,50,000.00"), hold(amount="250 000"),
                  hold(ifsc="sbin0001234", account=" 123456789012")):
        assert "Approved by a second officer: Bina Iyer" in notice_for(asha, typed)


def test_the_fingerprint_is_of_the_letter_s_details_after_its_own_normalisation():
    one = fingerprint("case-1", BANK_FREEZE, hold())
    assert len(one) == 64 and int(one, 16) >= 0
    for same in (hold(ifsc=" sbin0001234 "), hold(account="1234 5678 9012"),
                 hold(amount=250000), hold(amount=250000.0), hold(amount="250000.00"), hold(period_from="2026-10-01")):
        assert fingerprint("case-1", BANK_FREEZE, same) == one
    for other in (hold(account=OTHER_ACCOUNT), hold(amount="2,50,001"), hold(amount=None), hold(order=OTHER_ORDER)):
        assert fingerprint("case-1", BANK_FREEZE, other) != one
    assert fingerprint("case-2", BANK_FREEZE, hold()) != one  # bound to the case too
    assert fingerprint("case-1", BANK_INFO, bank()) is None  # only the hold waits for a sign-off
    with pytest.raises(NoticeError):
        fingerprint("case-1", BANK_FREEZE, hold(order=""))


def test_the_hold_prints_the_fingerprint_its_sign_off_covers():
    text = draft("case-1", case(), BANK_FREEZE, hold())
    assert f"Details fingerprint: {fingerprint('case-1', BANK_FREEZE, hold())[:16]}" in text


def test_a_hold_is_put_up_for_sign_off_only_with_its_details(unit):  # noqa: F811
    asha = signed_in("asha")
    rid = drafted(asha, kind=BANK_FREEZE, ask=False)
    for change in ({"status": "awaiting_signoff"}, {"status": "awaiting_signoff", "details": hold(order="")},
                   {"status": "awaiting_signoff", "details": hold(account="12ab")}):
        assert asha.patch(f"/requests/{rid}", json=change).status_code == 400
    made = asha.post("/requests", json={"case_id": "case-1", "recipient": "SBI", "kind": BANK_FREEZE,
                                        "status": "awaiting_signoff"})
    assert made.status_code == 400
    made = asha.post("/requests", json={"case_id": "case-1", "recipient": "SBI", "kind": BANK_FREEZE,
                                        "status": "awaiting_signoff", "details": hold()})
    assert made.status_code == 201 and made.json()["fingerprint"] == fingerprint("case-1", BANK_FREEZE, hold())[:16]


def test_the_second_officer_signs_off_only_the_details_put_up(unit):  # noqa: F811
    asha, bina = signed_in("asha"), signed_in("bina")
    rid = drafted(asha, kind=BANK_FREEZE, details=hold())
    [seen] = bina.get("/trace/case-1/requests").json()["requests"]
    assert seen["fingerprint"] == fingerprint("case-1", BANK_FREEZE, hold())[:16]  # what the card shows
    assert sign(bina, rid).status_code == 400  # no details: nothing to compare
    refused = sign(bina, rid, hold(account=OTHER_ACCOUNT))
    assert refused.status_code == 409 and "not the ones" in refused.json()["detail"]
    assert bina.get("/trace/case-1/requests").json()["requests"][0]["status"] == "awaiting_signoff"
    assert sign(bina, rid, hold()).status_code == 200


def test_changed_details_need_a_fresh_sign_off(unit):  # noqa: F811
    asha, bina = signed_in("asha"), signed_in("bina")
    first = drafted(asha, kind=BANK_FREEZE, details=hold())
    sign(bina, first, hold())
    # Signed, a request cannot be put up again with other details ...
    again = asha.patch(f"/requests/{first}", json={"status": "awaiting_signoff", "details": hold(order=OTHER_ORDER)})
    assert again.status_code == 400
    # ... so the officer closes it and asks afresh: only the new details are approved then.
    assert asha.patch(f"/requests/{first}", json={"status": "closed"}).status_code == 200
    second = drafted(asha, kind=BANK_FREEZE, details=hold(order=OTHER_ORDER))
    assert AWAITING in notice_for(asha, hold(order=OTHER_ORDER))
    sign(bina, second, hold(order=OTHER_ORDER))
    assert "Approved by a second officer" in notice_for(asha, hold(order=OTHER_ORDER))
    assert AWAITING in notice_for(asha, hold())  # its request is closed


def test_a_bound_sign_off_keeps_the_account_number_out_of_the_audit_log_and_the_store(unit, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    asha, bina = signed_in("asha"), signed_in("bina")
    rid = drafted(asha, kind=BANK_FREEZE, details=hold())
    sign(bina, rid, hold(account=OTHER_ACCOUNT))  # refused
    sign(bina, rid, hold())
    notice_for(asha, hold())
    prefix = fingerprint("case-1", BANK_FREEZE, hold())[:16]
    with models.session() as s:
        audit_rows = [(r.action, r.detail or "") for r in s.scalars(select(models.AuditEvent))]
        stored = s.get(models.FreezeRequest, rid)
        row = " ".join(str(getattr(stored, c.key)) for c in models.FreezeRequest.__table__.columns)
    signed = [json.loads(d) for a, d in audit_rows if a in ("request.signoff_ask", "request.signoff")]
    assert [d.get("fingerprint") for d in signed] == [prefix, prefix]
    for secret in (ACCOUNT, OTHER_ACCOUNT, IFSC, ORDER, SOURCE, "2,50,000"):
        assert all(secret not in d for _, d in audit_rows) and secret not in row and secret not in caplog.text
