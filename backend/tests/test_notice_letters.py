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
from app.notice_letters import (BANK_FREEZE, BANK_INFO, NOTICES, TELECOM, NoticeError, draft)
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
    assert "INR 250,000.00" in draft("case-1", case(), BANK_FREEZE, bank(order=ORDER, amount=250000))
    with pytest.raises(NoticeError):
        draft("case-1", case(), BANK_FREEZE, bank(order=ORDER, amount=-5))


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
