"""Tests for attributing Tron wallets from TronScan's tag at trace time.

The failure that matters is naming an exchange that is not one: a tag for a
treasury, a bridge or a scam wallet read as a cash-out point. The other is a
trace broken by a lookup -- TronScan refusing must cost an attribution, never
the trace.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from app import main
from app.etherscan_client import Transaction
from app.main import TraceRequest, run_trace
from app.tron_tags import (MAX_LOOKUPS_PER_TRACE, LiveTronExchanges, exchange_for_tag,
                           tag_from_response, warning_from_response)

from conftest import make_graph

SEED = "TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts"
HOP = "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU"
EXCH = "TMuA6YqfCeX8EhbfYEg5y7S4DqzSJireY9"


class FakeTags:
    def __init__(self, tags, enabled=True):
        self._tags, self.enabled, self.asked = tags, enabled, []
        self.lookups = self.failures = 0

    def account(self, address):
        self.asked.append(address)
        self.lookups += 1
        value = self._tags.get(address)
        if isinstance(value, dict):
            return value
        return {"tag": value, "warning": warning_from_response({"addressTag": value})}

    def close(self):
        pass


def test_only_a_tag_naming_a_known_exchange_counts():
    assert exchange_for_tag("Binance-Hot 12") == "Binance"
    assert exchange_for_tag("OKX Hot Wallet 3") == "OKX"
    assert exchange_for_tag("Tether Treasury") is None
    assert exchange_for_tag("Binance Bridge") is None
    assert exchange_for_tag("Scam: Fake Binance") is None
    assert exchange_for_tag("Some Unknown Venue") is None
    assert exchange_for_tag(None) is None


def test_the_tag_is_read_from_the_response_and_never_invented():
    assert tag_from_response({"addressTag": " Binance-Hot 7 "}) == "Binance-Hot 7"
    assert tag_from_response({"addressTag": "", "publicTag": "OKX 1"}) == "OKX 1"
    assert tag_from_response({"balance": 5}) is None
    assert tag_from_response(["not", "a", "dict"]) is None


def test_a_labelled_wallet_is_never_asked_about():
    tags = FakeTags({EXCH: "Binance-Hot 7"})
    live = LiveTronExchanges(tags, is_labelled=lambda a: a == EXCH)
    assert live.is_exchange(EXCH) is False and tags.asked == []


def test_the_walk_stops_at_a_wallet_tronscan_tags_as_an_exchange():
    live = LiveTronExchanges(FakeTags({EXCH: "Binance-Hot 7", HOP: "Tether Treasury"}), lambda a: False)
    assert live.is_exchange(EXCH) is True
    assert live.is_exchange(HOP) is False
    assert live.found[EXCH]["exchange"] == "Binance"
    assert "read live" in live.found[EXCH]["label"]
    assert live.unrecognised == {HOP: "Tether Treasury"}


def test_the_sweep_asks_about_the_last_hop_the_walk_never_checked():
    graph = make_graph([(SEED, HOP, 10.0), (HOP, EXCH, 9.0)], seed=SEED)
    tags = FakeTags({EXCH: "OKX Hot Wallet 8"})
    live = LiveTronExchanges(tags, lambda a: False)
    live.sweep(graph)
    assert EXCH in live.found and SEED not in live.found


def test_lookups_are_capped_per_trace():
    tags = FakeTags({})
    live = LiveTronExchanges(tags, lambda a: False)
    for i in range(MAX_LOOKUPS_PER_TRACE + 20):
        live.is_exchange(f"T{i:033d}")
    assert len(tags.asked) == MAX_LOOKUPS_PER_TRACE


def test_without_a_key_nothing_is_asked():
    tags = FakeTags({EXCH: "Binance-Hot 7"}, enabled=False)
    live = LiveTronExchanges(tags, lambda a: False)
    live.sweep(make_graph([(SEED, EXCH, 1.0)], seed=SEED))
    assert live.is_exchange(EXCH) is False and tags.asked == []


def tx(src, dst, value, when):
    return Transaction(hash=f"{abs(hash((src, dst))):064x}", from_address=src, to_address=dst,
                       value_native=value, value_wei=int(value * 1e6), timestamp=when,
                       block_number=when // 3, is_error=False, asset="USDT")


@pytest.fixture
def tron_trace(monkeypatch):
    history = [tx(SEED, HOP, 100.0, 1_700_000_000), tx(HOP, EXCH, 99.0, 1_700_000_100)]

    class Source:
        def get_outgoing_transactions(self, address, limit=None):
            return [t for t in history if t.from_address == address]

    @contextmanager
    def open_source(chain, asset):
        yield Source()

    monkeypatch.setattr(main, "open_source", open_source)
    monkeypatch.setattr(main.config, "TRONSCAN_API_KEY", "test-key")
    monkeypatch.setattr(main.TronScanTags, "account",
                        lambda self, a: {EXCH: {"tag": "Binance-Hot 9", "warning": None}}.get(a))


def test_a_tron_trace_attributes_a_wallet_from_its_tronscan_tag(tron_trace):
    result = run_trace(TraceRequest(address=SEED, chain="tron", asset="USDT", max_depth=3))
    assert result["exchange"] == "Binance"
    assert result["exchange_address"] == EXCH
    assert "TronScan tag, read live" in result["exchange_label"]
    assert result["live_tags"]["found"][0]["address"] == EXCH


def test_a_failed_lookup_leaves_the_trace_intact(tron_trace, monkeypatch):
    monkeypatch.setattr(main.TronScanTags, "account", lambda self, a: None)
    result = run_trace(TraceRequest(address=SEED, chain="tron", asset="USDT", max_depth=3))
    assert result["exchange"] is None and len(result["graph"]["nodes"]) == 3


def test_the_report_says_what_tronscan_named(tron_trace):
    import json
    from app.models import Case
    from app.report import build_report, render_text_report

    result = run_trace(TraceRequest(address=SEED, chain="tron", asset="USDT", max_depth=3))
    case = Case(id="c1", address=SEED, created_at="2026-09-24T00:00:00+00:00",
                result_json=json.dumps(result, default=str))
    text = render_text_report(build_report(case))
    assert "TronScan tags read live" in text and EXCH in text


def test_a_mistyped_tron_address_is_caught_by_its_checksum():
    """A typo should read as an invalid address, not as a provider outage."""
    from app.etherscan_client import is_tron_address
    good = "TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts"
    assert is_tron_address(good)
    assert not is_tron_address(good[:-1] + ("t" if good[-1] != "t" else "u"))


def test_a_mistyped_tron_address_is_a_400(monkeypatch):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as err:
        run_trace(TraceRequest(address="TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3tu", chain="tron", asset="USDT"))
    assert err.value.status_code == 400


def test_the_sweep_skips_wallets_beyond_the_nearest_labelled_exchange():
    far = "TXEsK1sEsKjZ1xtHitnyAAoqw3WLdYdRNW"
    graph = make_graph([(SEED, HOP, 10.0), (HOP, EXCH, 9.0), (EXCH, far, 1.0)], seed=SEED)
    tags = FakeTags({})
    live = LiveTronExchanges(tags, is_labelled=lambda a: a == EXCH)
    live.sweep(graph)
    assert tags.asked == [SEED, HOP]


# -- TronScan's warning tags --------------------------------------------------
def test_a_warning_is_the_red_tag_or_a_tag_naming_a_scam():
    # "Suspicious" is the red tag TronScan put on TMj4fHv4…, seen 24 Sep 2026.
    assert warning_from_response({"redTag": "Suspicious", "addressTag": ""}) == "Suspicious"
    assert warning_from_response({"addressTag": "Fake_Phishing123"}) == "Fake_Phishing123"
    assert warning_from_response({"addressTag": "Binance-Hot 7", "redTag": ""}) is None
    assert warning_from_response({"balance": 1}) is None


def test_a_red_tagged_wallet_in_the_trace_is_a_screening_hit(tron_trace, monkeypatch):
    monkeypatch.setattr(main.TronScanTags, "account", lambda self, a: {
        EXCH: {"tag": "Binance-Hot 9", "warning": None},
        HOP: {"tag": None, "warning": "Suspicious"},
    }.get(a))
    result = run_trace(TraceRequest(address=SEED, chain="tron", asset="USDT", max_depth=3))
    hit = next(m for m in result["risk_matches"] if m["address"] == HOP)
    assert hit["category"] == "reported" and not hit["is_terminal"]
    assert result["exchange"] == "Binance"  # a warning never stops the trace
    note = next(n for n in result["risk_notes"] if HOP in n)
    assert "Suspicious" in note and "not a designation" in note
    assert result["live_tags"]["warnings"] == [{"address": HOP, "warning": "Suspicious"}]


def test_a_label_file_entry_outranks_tronscans_warning(tron_trace, monkeypatch):
    from app.risk_matcher import RiskMatcher
    listed = RiskMatcher({HOP: {"category": "sanctioned", "entity": "X", "label": "X",
                                "source": "OFAC SDN list"}}, chain="tron")
    monkeypatch.setattr(main, "get_risk_matcher", lambda key=None: listed)
    monkeypatch.setattr(main.TronScanTags, "account", lambda self, a: {
        HOP: {"tag": None, "warning": "Suspicious"}}.get(a))
    result = run_trace(TraceRequest(address=SEED, chain="tron", asset="USDT", max_depth=3))
    assert [m["category"] for m in result["risk_matches"] if m["address"] == HOP] == ["sanctioned"]


def test_a_warning_on_the_reported_address_itself_is_read(tron_trace, monkeypatch):
    from app.risk_matcher import RiskMatcher
    monkeypatch.setattr(main, "get_risk_matcher", lambda key=None: RiskMatcher({}, chain="tron"))
    monkeypatch.setattr(main.TronScanTags, "account", lambda self, a: {
        SEED: {"tag": "Binance-Hot 1", "warning": "Suspicious"}}.get(a))
    result = run_trace(TraceRequest(address=SEED, chain="tron", asset="USDT", max_depth=3))
    hit = next(m for m in result["risk_matches"] if m["address"] == SEED)
    assert hit["category"] == "reported" and hit["depth"] == 0
    assert result["exchange"] is None  # the seed's own tag is never an attribution
