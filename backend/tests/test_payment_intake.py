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
from app.payment_intake import PaymentError, PaymentRef, normalize_hash, resolve_payments
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
