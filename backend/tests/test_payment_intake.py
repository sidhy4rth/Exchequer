"""R1: a trace that starts from the victim's payments, not from an address alone."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import pytest
from fastapi import HTTPException

from app import config
from app import pipeline as main
from app.contracts import read_case
from app.etherscan_client import Transaction
from app.payment_intake import (
    PaymentError,
    PaymentRef,
    leg_warnings,
    normalize_hash,
    reported_amount,
    resolve_payments,
)
from app.pipeline import TraceRequest, check_request, run_trace

from conftest import addr

SCAMMER = addr("5ca")
VICTIM = addr("71c")
OTHER_PAYER = addr("07e")
EARLIER = addr("ea7")   # paid by the scammer before the victim's money arrived
LATER = addr("1a7")     # paid after it
PAID_AT = 1_700_000_000


def tx(hash_, src, dst, value, when):
    return Transaction(hash=hash_, from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 1e18), timestamp=when, block_number=when // 12,
                       is_error=False, asset="ETH")


PAYMENT = tx("0x" + "aa" * 32, VICTIM, SCAMMER, 2.0, PAID_AT)
SECOND = tx("0x" + "bb" * 32, VICTIM, SCAMMER, 0.5, PAID_AT + 600)
UNRELATED_IN = tx("0x" + "cc" * 32, OTHER_PAYER, SCAMMER, 9.0, PAID_AT - 3600)
SENT_BEFORE = tx("0x" + "dd" * 32, SCAMMER, EARLIER, 5.0, PAID_AT - 60)
SENT_AFTER = tx("0x" + "ee" * 32, SCAMMER, LATER, 2.4, PAID_AT + 900)
HISTORY = [PAYMENT, SECOND, UNRELATED_IN, SENT_BEFORE, SENT_AFTER]


class FakeClient:
    def get_outgoing_transactions(self, address, limit=None):
        return [t for t in HISTORY if t.from_address == address]

    def get_incoming_transactions(self, address, limit=None):
        return [t for t in HISTORY if t.to_address == address]


@pytest.fixture
def chain(monkeypatch):
    @contextmanager
    def open_source(chain, asset):
        yield FakeClient()

    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(main, "detect_swaps", lambda *a, **k: [])
    monkeypatch.setattr(config, "TX_INTAKE", True)


def request(**kw):
    kw.setdefault("payments", [{"tx_hash": PAYMENT.hash}])
    return TraceRequest(address=SCAMMER, chain="ethereum", asset="ETH", max_depth=2, **kw)


# ---------------------------------------------------------------- the trace
def test_a_payment_trace_ignores_what_the_wallet_sent_before_the_payment(chain):
    result = run_trace(request())
    reached = {n["id"] for n in result["graph"]["nodes"]}
    assert LATER.lower() in reached
    assert EARLIER.lower() not in reached, "money sent before the victim paid is not the victim's"


def test_an_address_only_trace_still_follows_everything(chain):
    result = run_trace(request(payments=[]))
    reached = {n["id"] for n in result["graph"]["nodes"]}
    assert {EARLIER.lower(), LATER.lower()} <= reached
    case = read_case(result)
    assert case.intake.mode == "address" and case.reported_amount is None


def test_the_case_records_the_payments_and_the_reported_amount(chain):
    result = run_trace(request(payments=[{"tx_hash": SECOND.hash}, {"tx_hash": PAYMENT.hash}],
                               ncrp_ack="31911250012345"))
    case = read_case(result)
    assert case.intake.mode == "payment"
    assert case.intake.ncrp_ack == "31911250012345"
    assert [p.tx_hash for p in case.intake.payments] == [PAYMENT.hash, SECOND.hash], "oldest first"
    assert case.reported_amount == 2.5
    first = case.intake.payments[0]
    assert (first.from_address, first.to, first.block) == (VICTIM, SCAMMER, PAID_AT // 12)


def test_the_window_starts_at_the_earliest_payment(chain):
    # The second payment alone would start the window later still: 2.4 at +900
    # stays in, and the earlier send stays out either way.
    result = run_trace(request(payments=[{"tx_hash": SECOND.hash}]))
    reached = {n["id"] for n in result["graph"]["nodes"]}
    assert LATER.lower() in reached and EARLIER.lower() not in reached


# ---------------------------------------------------------------- refusals
def test_a_hash_that_is_not_a_payment_to_this_wallet_is_refused(chain):
    with pytest.raises(HTTPException) as err:
        run_trace(request(payments=[{"tx_hash": SENT_AFTER.hash}]))  # sent BY the scammer
    assert err.value.status_code == 400
    assert "not an incoming ETH transfer" in err.value.detail


def test_a_misspelt_hash_is_refused(chain):
    with pytest.raises(HTTPException) as err:
        run_trace(request(payments=[{"tx_hash": "0x" + "ab" * 32}]))
    assert err.value.status_code == 400


def test_payments_need_the_flag(chain, monkeypatch):
    monkeypatch.setattr(config, "TX_INTAKE", False)
    with pytest.raises(HTTPException) as err:
        check_request(request())
    assert "EXCHEQUER_TX_INTAKE" in err.value.detail


def test_payments_only_start_an_outgoing_trace(chain):
    with pytest.raises(HTTPException) as err:
        check_request(request(direction="incoming"))
    assert "outgoing" in err.value.detail


# ---------------------------------------------------------------- the resolver
def test_the_same_payment_twice_is_refused():
    refs = [PaymentRef(tx_hash=PAYMENT.hash), PaymentRef(tx_hash=PAYMENT.hash.upper())]
    with pytest.raises(PaymentError, match="listed twice"):
        resolve_payments(FakeClient(), SCAMMER, refs, chain_key="ethereum", asset="ETH", limit=100)


def test_hashes_match_without_case_or_prefix():
    assert normalize_hash("0xABcd") == normalize_hash("abcd") == "abcd"
    (payment,) = resolve_payments(FakeClient(), SCAMMER, [PaymentRef(tx_hash=PAYMENT.hash[2:].upper())],
                                  chain_key="ethereum", asset="ETH", limit=100)
    assert payment["tx_hash"] == PAYMENT.hash and payment["found_by"] == "victim"


def test_a_failed_transaction_is_not_a_payment():
    failed = replace(tx("0x" + "ff" * 32, VICTIM, SCAMMER, 1.0, PAID_AT), is_error=True)

    class Client(FakeClient):
        def get_incoming_transactions(self, address, limit=None):
            return [failed]

    with pytest.raises(PaymentError):
        resolve_payments(Client(), SCAMMER, [PaymentRef(tx_hash=failed.hash)],
                         chain_key="ethereum", asset="ETH", limit=100)


# ---------------------------------------------------------------- what the form is told
def test_the_form_is_told_whether_payment_intake_is_on(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        monkeypatch.setattr(config, "TX_INTAKE", False)
        off = client.get("/trace/intake")
        monkeypatch.setattr(config, "TX_INTAKE", True)
        on = client.get("/trace/intake")
    # Not read as a case id by GET /trace/{case_id}.
    assert off.status_code == on.status_code == 200
    assert off.json()["payments"] is False and on.json()["payments"] is True
    assert on.json()["lookup_limit"] == config.TX_INTAKE_LOOKUP_LIMIT


def test_an_intake_trace_estimate_never_exceeds_the_reported_amount(chain, monkeypatch):
    # Audit r1-attribution-integrity-7: the victim paid 2.0; the wallet sent
    # 2.4 to an exchange, the rest from someone else. The case may say at most
    # 2.0 of the victim's money arrived.
    from app.exchange_matcher import ExchangeMatcher
    labels = {LATER: {"exchange": "Binance", "label": "Binance 14", "type": "hot_wallet"}}
    monkeypatch.setattr(main, "get_matcher", lambda key: ExchangeMatcher(labels, chain="ethereum"))
    result = run_trace(request())
    assert result["exchange"] == "Binance"
    assert result["prorata"]["estimated"] == 2.0 and result["prorata"]["sent"] == 2.4
    assert result["prorata"]["seed_cap"] == {"amount": 2.0, "basis": "reported_amount", "applied": True}
    assert read_case(result).estimates.conservative == 2.0


def test_the_report_states_the_capped_figure_and_why(chain, monkeypatch):
    import json

    from app.exchange_matcher import ExchangeMatcher
    from app.models import Case
    from app.report import build_report, render_text_report
    labels = {LATER: {"exchange": "Binance", "label": "Binance 14", "type": "hot_wallet"}}
    monkeypatch.setattr(main, "get_matcher", lambda key: ExchangeMatcher(labels, chain="ethereum"))
    result = run_trace(request())
    amount = next(c for c in result["confidence_detail"]["components"] if c["name"] == "amount_correlation")
    assert "about 2.0000 of the 2.0000 ETH the victim reported paying" in amount["explanation"]
    case = Case(id="c1", address=SCAMMER, created_at="2026-09-24T00:00:00+00:00",
                result_json=json.dumps(result, default=str))
    text = " ".join(render_text_report(build_report(case)).split())
    assert "about 2.0 of the 2.0 ETH the victim reported paying (pro-rata; the reported address sent 2.4" in text


# ---------------------------------------------------------------- shapes, before admission (5-5)
def _post_job(monkeypatch, body):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes import cases

    admitted = []
    monkeypatch.setattr(cases, "admit", lambda http: admitted.append(1) or None)
    with TestClient(app) as client:
        response = client.post("/trace/jobs", json={"address": SCAMMER, "chain": "ethereum", **body})
    return response, admitted


@pytest.mark.parametrize("bad", ["zzzzzzzz", " " * 8, "0x" + "ab" * 31, "0x" + "ab" * 33, "0x" + "gg" * 32])
def test_a_malformed_hash_is_refused_before_anything_is_spent(monkeypatch, bad):
    monkeypatch.setattr(config, "TX_INTAKE", True)
    response, admitted = _post_job(monkeypatch, {"payments": [{"tx_hash": bad}]})
    assert response.status_code == 422 and admitted == []


def test_an_upper_case_hash_without_0x_is_accepted():
    ref = PaymentRef(tx_hash=" " + "AB" * 32 + " ")
    assert ref.tx_hash == "ab" * 32


def test_a_hash_listed_twice_is_refused_before_admission(monkeypatch):
    monkeypatch.setattr(config, "TX_INTAKE", True)
    response, admitted = _post_job(monkeypatch, {"payments": [{"tx_hash": PAYMENT.hash},
                                                              {"tx_hash": PAYMENT.hash[2:].upper()}]})
    assert response.status_code == 400 and "listed twice" in response.json()["detail"]
    assert admitted == []


@pytest.mark.parametrize("bad", ["FIR 123/2026", "‮31911250012345", "3191125001234\u0000", "123", "1" * 21])
def test_an_ncrp_number_that_is_not_digits_is_refused(bad):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="NCRP acknowledgement number"):
        request(ncrp_ack=bad)


def test_an_ncrp_number_is_stored_stripped_and_blank_is_none():
    assert request(ncrp_ack=" 31911250012345 ").ncrp_ack == "31911250012345"
    assert request(ncrp_ack="  ").ncrp_ack is None


def test_a_provider_row_with_no_hash_never_matches():
    blank = replace(PAYMENT, hash="")

    class Client(FakeClient):
        def get_incoming_transactions(self, address, limit=None):
            return [blank]

    with pytest.raises(PaymentError):
        resolve_payments(Client(), SCAMMER, [PaymentRef.model_construct(tx_hash="  ", found_by="victim")],
                         chain_key="ethereum", asset="ETH", limit=100)


# ---------------------------------------------------------------- the statement (5-1)
def test_a_payment_trace_keeps_the_wallet_statement(chain):
    statement = run_trace(request())["statement"]
    assert statement is not None and statement["window_start"] == PAID_AT
    debits = {r["tx"]: r for r in statement["debits"]}
    assert debits[SENT_BEFORE.hash]["before_window"] is True, "marked, never hidden"
    assert debits[SENT_AFTER.hash]["before_window"] is False


def test_an_address_only_statement_is_unchanged(chain):
    statement = run_trace(request(payments=[]))["statement"]
    assert "window_start" not in statement
    assert all("before_window" not in r for r in statement["debits"] + statement["credits"])


# ---------------------------------------------------------------- one hash, several legs (5-2)
CONTRACT = addr("c0de")
LEG_HASH = "0x" + "12" * 32


def legs(*values, sender=CONTRACT):
    return [tx(LEG_HASH, sender, SCAMMER, v, PAID_AT) for v in values]


class LegClient(FakeClient):
    def __init__(self, rows):
        self.rows = rows

    def get_outgoing_transactions(self, address, limit=None):
        return []

    def get_incoming_transactions(self, address, limit=None):
        return list(self.rows)


def resolve(rows):
    return resolve_payments(LegClient(rows), SCAMMER, [PaymentRef(tx_hash=LEG_HASH)],
                            chain_key="ethereum", asset="ETH", limit=100)


@pytest.mark.parametrize("order", [(3999.0, 1.0), (1.0, 3999.0)])
def test_a_payment_with_two_legs_records_both_in_either_order(order):
    payments = resolve(legs(*order))
    assert [(p["leg"], p["amount"]) for p in payments] == [(0, 3999.0), (1, 1.0)]
    assert reported_amount(payments) == 4000.0
    (warning,) = leg_warnings(payments)
    assert "arrived as 2 transfers" in warning and "3,999 + 1 ETH" in warning
    assert SCAMMER.lower() not in warning.lower() and CONTRACT.lower() not in warning.lower()


def test_two_identical_legs_are_both_counted():
    # Two Transfer logs of the same amount are two rows alike: both are money.
    payments = resolve(legs(1000.0, 1000.0))
    assert len(payments) == 2 and reported_amount(payments) == 2000.0


def test_a_single_leg_payment_has_no_leg_field():
    (payment,) = resolve(legs(4.0))
    assert "leg" not in payment
    assert leg_warnings([payment]) == []


def test_legs_from_two_senders_say_so():
    (warning,) = leg_warnings(resolve(legs(3.0) + legs(1.0, sender=VICTIM)))
    assert "from 2 different senders" in warning


def test_a_multi_leg_payment_is_whole_in_the_case(monkeypatch):
    @contextmanager
    def open_source(chain, asset):
        yield LegClient(legs(1.0, 3999.0))

    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(main, "detect_swaps", lambda *a, **k: [])
    monkeypatch.setattr(config, "TX_INTAKE", True)
    result = run_trace(request(payments=[{"tx_hash": LEG_HASH}]))
    case = read_case(result)
    assert case.reported_amount == 4000.0
    assert [(p.leg, p.amount) for p in case.intake.payments] == [(0, 3999.0), (1, 1.0)]
    assert any("arrived as 2 transfers" in w for w in result["warnings"])
