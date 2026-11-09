"""Who paid (5-3): each payment's sender is labelled and, when the complaint
gives the victim's own wallet, compared with it.

Any incoming transfer used to be accepted as "the victim's payment" with its
sender unchecked and unlabelled, so a scammer's own wallet or a look-alike
transfer could open the time window early with nothing to say so. The
warnings these produce name no address: the senders and the victim's wallet
are the complaint's particulars.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from app import config
from app import pipeline as main
from app.contracts import read_case
from app.etherscan_client import Transaction
from app.exchange_matcher import ExchangeMatcher
from app.payment_intake import review_payments
from app.pipeline import TraceRequest, check_request, run_trace

from conftest import addr

SCAMMER, VICTIM, STRANGER, HOT = addr("5ca"), addr("71c"), addr("57a"), addr("b14")
ROUTER = addr("4011")
PAID_AT = 1_760_000_000
DAY = 86_400
HASH_A, HASH_B = "0x" + "aa" * 32, "0x" + "bb" * 32
LABELS = {HOT: {"exchange": "Binance", "label": "Binance 14", "type": "hot_wallet"}}
ROUTERS = {ROUTER: {"exchange": "Uniswap", "label": "Uniswap V3 router", "type": "router"}}


def payment(sender, tx_hash=HASH_A, when=PAID_AT, amount=2.0):
    return {"tx_hash": tx_hash, "chain": "ethereum", "asset": "ETH", "amount": amount, "from": sender,
            "to": SCAMMER, "block": when // 12, "timestamp": when, "found_by": "victim"}


def review(payments, victim=VICTIM):
    return review_payments(payments, victim_address=victim,
                           exchange_of=ExchangeMatcher(LABELS).lookup, router_of=ExchangeMatcher(ROUTERS).lookup)


def assert_no_address(text):
    for a in (SCAMMER, VICTIM, STRANGER, HOT, ROUTER):
        assert a.lower() not in text.lower()


def test_a_payment_from_another_wallet_is_marked_and_warned():
    paid = [payment(STRANGER)]
    (warning,) = review(paid)
    assert paid[0]["payer_is_victim"] is False and paid[0]["payer_label"] is None
    assert "was not sent from the victim's wallet" in warning
    assert_no_address(warning)


def test_a_payment_from_the_victim_is_marked_and_not_warned():
    paid = [payment(VICTIM.upper().replace("0X", "0x"))]
    assert review(paid) == []
    assert paid[0]["payer_is_victim"] is True


def test_an_exchange_payer_is_labelled_with_the_exchange_wording():
    paid = [payment(HOT)]
    (warning,) = review(paid)
    assert paid[0]["payer_label"] == "Binance 14" and paid[0]["payer_is_victim"] is False
    assert "came from an exchange wallet (Binance 14)" in warning and "withdrew from an exchange" in warning
    assert_no_address(warning)


def test_a_contract_payer_is_labelled():
    paid = [payment(ROUTER)]
    (warning,) = review(paid)
    assert paid[0]["payer_label"] == "Uniswap V3 router"
    assert "through a contract (Uniswap V3 router)" in warning
    assert_no_address(warning)


def test_without_the_victims_wallet_nothing_is_compared():
    paid = [payment(STRANGER), payment(HOT, tx_hash=HASH_B, when=PAID_AT + 60)]
    assert review(paid, victim=None) == []
    assert [p["payer_is_victim"] for p in paid] == [None, None]
    assert paid[1]["payer_label"] == "Binance 14", "the label is kept either way"


def test_a_first_payment_long_before_the_next_is_warned():
    paid = [payment(VICTIM, HASH_A, PAID_AT), payment(VICTIM, HASH_B, PAID_AT + 14 * DAY)]
    (warning,) = review(paid)
    assert "is 14 days before the next" in warning and "reads the wallet from the first" in warning


def test_payments_close_together_are_not_warned():
    paid = [payment(VICTIM, HASH_A, PAID_AT), payment(VICTIM, HASH_B, PAID_AT + 2 * DAY)]
    assert review(paid) == []


def test_two_legs_of_one_hash_are_one_payment_for_the_gap():
    legs = [{**payment(VICTIM), "leg": 0}, {**payment(VICTIM, amount=1.0), "leg": 1}]
    assert review(legs) == []


# ---------------------------------------------------------------- the request
def request(**kw):
    kw.setdefault("payments", [{"tx_hash": HASH_A}])
    return TraceRequest(address=SCAMMER, chain="ethereum", asset="ETH", max_depth=2, **kw)


@pytest.fixture
def intake_on(monkeypatch):
    monkeypatch.setattr(config, "TX_INTAKE", True)


@pytest.mark.parametrize("kw, words", [
    ({"payments": [], "victim_address": VICTIM}, "with the payment hashes"),
    ({"victim_address": "0x1234"}, "is not a valid Ethereum"),
    ({"victim_address": SCAMMER.upper().replace("0X", "0x")}, "is the reported wallet"),
])
def test_a_bad_victim_wallet_is_refused_before_admission(intake_on, kw, words):
    with pytest.raises(HTTPException) as err:
        check_request(request(**kw))
    assert err.value.status_code == 400 and words in err.value.detail
    assert "0x1234" not in err.value.detail


def test_a_blank_victim_wallet_is_none():
    assert request(victim_address="  ").victim_address is None


def test_the_case_records_the_payer_check(intake_on, monkeypatch):
    paid = Transaction(hash=HASH_A, from_address=STRANGER, to_address=SCAMMER, value_native=2.0,
                       value_wei=2 * 10**18, timestamp=PAID_AT, block_number=PAID_AT // 12, is_error=False,
                       asset="ETH")

    class Client:
        def get_outgoing_transactions(self, address, limit=None):
            return []

        def get_incoming_transactions(self, address, limit=None):
            return [paid]

    @contextmanager
    def open_source(chain, asset):
        yield Client()

    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(main, "detect_swaps", lambda *a, **k: [])
    result = run_trace(request(victim_address=VICTIM))
    case = read_case(result)
    assert case.intake.victim_address == VICTIM.lower()
    assert case.intake.payments[0].payer_is_victim is False
    assert any("was not sent from the victim's wallet" in w for w in result["warnings"])
