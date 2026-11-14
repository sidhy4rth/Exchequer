"""The India exchange set: Indian exchanges' wallets, each row with its public source.

data/india_exchanges.json records where every row came from (an explorer's
public name tag, or a wallet list the exchange published itself), and the
chain's exchange label file carries the same address, so the matcher reads it
the way it reads every other label. These pin that the two agree, that every
address is valid for its chain, that none collides with another list, and
that a trace reaching one of them names the exchange. All offline.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import pytest

from app import config, never_flag, pipeline
from app.tron_tags import exchange_for_tag
from app.etherscan_client import Transaction, normalize_address
from app.exchange_matcher import get_matcher, is_deposit_label
from app.pipeline import TraceRequest, run_trace
from scripts._tag_words import names_infrastructure

from conftest import addr

SET_FILE = Path(config.DATA_DIR) / "india_exchanges.json"
DOC = json.loads(SET_FILE.read_text(encoding="utf-8"))
ROWS = DOC["rows"]
KEYS = {"address", "chain", "exchange", "label", "type", "kind", "source", "source_date", "retrieved_on"}
INDIAN = {"WazirX", "CoinDCX", "CoinSwitch", "ZebPay", "Mudrex", "Giottus", "Bitbns", "Unocoin", "BuyUcoin"}
SOURCE = re.compile(r"https://(etherscan\.io|polygonscan\.com)/address/0x[0-9a-f]{40}$"
                    r"|https://coinswitch\.co/building-blocks/[a-z0-9-]+/$")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}$")
OTHER_LISTS = ("risk_labels_path", "intl_sanctions_path", "frozen_labels_path", "threat_labels_path",
               "gambling_labels_path", "router_labels_path")


def _labels(path):
    if path is None or not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("labels", data) if isinstance(data, dict) else {}
    return {normalize_address(a): m for a, m in entries.items() if isinstance(a, str) and not a.startswith("_")}


# -- the file: shape, sources, validity -------------------------------------------------
def test_the_set_is_not_empty_and_every_row_has_its_fields_and_a_source():
    assert ROWS, "the set is empty: say so in the PR and the report"
    for row in ROWS:
        assert set(row) - {"published_as"} == KEYS, row
        assert row["exchange"] in INDIAN, row
        assert SOURCE.match(row["source"]), row["source"]
        assert DAY.match(row["retrieved_on"]), row
        assert row["source_date"].strip(), row  # the page's own date, or the post's publication date
        assert row["kind"].strip() and row["label"].strip(), row


def test_every_address_is_valid_for_its_chain_as_published():
    for row in ROWS:
        chain = config.get_chain(row["chain"])
        assert chain.validate_address(row.get("published_as", row["address"]), checksum=True), row
        assert row["address"] == normalize_address(row.get("published_as", row["address"])), row


def test_no_address_appears_twice_on_one_chain():
    counts = Counter((row["chain"], row["address"]) for row in ROWS)
    assert [key for key, n in counts.items() if n > 1] == []


def test_no_row_names_infrastructure_or_a_deposit_address():
    for row in ROWS:
        assert not names_infrastructure(row["label"]), row
        assert not is_deposit_label(row["label"]) and row["type"] != "deposit_wallet", row


def test_the_counts_in_the_meta_are_the_rows():
    counts = DOC["_meta"]["counts"]
    assert counts["rows"] == len(ROWS)
    assert counts["by_exchange"] == dict(Counter(row["exchange"] for row in ROWS))
    assert counts["by_chain"] == dict(Counter(row["chain"] for row in ROWS))
    assert sum(counts["by_source"].values()) == len(ROWS)


# -- agreement with the label files and no collisions -------------------------------
@pytest.mark.parametrize("row", ROWS, ids=lambda r: f"{r['chain']}-{r['address'][:10]}")
def test_the_chain_label_file_carries_the_row_exactly(row):
    held = _labels(config.get_chain(row["chain"]).labels_path).get(row["address"])
    assert held == {"exchange": row["exchange"], "label": row["label"], "type": row["type"]}


def test_no_row_is_on_a_sanctions_freeze_threat_gambling_or_router_list():
    for chain_key in {row["chain"] for row in ROWS}:
        chain = config.get_chain(chain_key)
        listed = set()
        for attribute in OTHER_LISTS:
            path = getattr(chain, attribute, None)
            listed |= set(_labels(path))
        assert [r["address"] for r in ROWS if r["chain"] == chain_key and r["address"] in listed] == []


def test_the_never_flag_check_reads_every_row_as_an_exchange_wallet_and_nothing_stricter():
    for row in ROWS:
        assert never_flag.kind(row["chain"], row["address"], with_gambling=True) == never_flag.EXCHANGE, row


def test_what_was_left_out_is_labelled_nowhere():
    for entry in DOC["_meta"]["left_out"]:
        assert entry["why"].strip() and entry["addresses"], entry
        try:
            chain = config.get_chain(entry["chain"])
        except config.UnknownChainError:
            continue  # a chain Exchequer does not trace, or one the source did not name
        for address in entry["addresses"]:
            assert get_matcher(chain.key).lookup(address) is None, (address, entry["why"])


def test_the_wazirx_multisig_attacked_in_july_2024_is_not_labelled():
    # WazirX's own announcement names it the affected wallet; whoever controls it since is not established.
    assert get_matcher("ethereum").lookup("0x27fd43babfbe83a81d14665b1a6fb8030a60c9b4") is None


def test_a_conflict_with_a_held_label_was_reported_not_overwritten():
    for conflict in DOC["_meta"]["conflicts_not_added"]:
        held = get_matcher(conflict["chain"]).lookup(conflict["address"])
        assert held is not None and held["exchange"] != conflict["source_says"], conflict


def test_a_tronscan_tag_naming_coinswitch_reads_as_coinswitch_and_a_warning_does_not():
    assert exchange_for_tag("CoinSwitch") == exchange_for_tag("CoinSwitch Hot Wallet 2") == "CoinSwitch"
    assert exchange_for_tag("CoinSwitch (Fake)") is None and exchange_for_tag("CoinSwitch Scam") is None
    assert exchange_for_tag("CoinSwitchPool") is None


# -- a trace that reaches one names the exchange --------------------------------------
SEED, HOP = addr("5eed"), addr("a1")
T = 1_700_000_000
_COUNTER = iter(range(1, 10**6))


def _tx(src, dst, value, when):
    return Transaction(hash="0x" + f"{next(_COUNTER):064x}", from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 1e18), timestamp=when, block_number=when // 12,
                       is_error=False, asset="ETH")


@pytest.fixture
def trace(monkeypatch):
    def run(history):
        class Fake:
            def get_outgoing_transactions(self, address, limit=None):
                return [t for t in history if t.from_address == address]

        @contextmanager
        def open_source(chain, asset):
            yield Fake()
        monkeypatch.setattr(pipeline, "open_source", open_source)
        monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
        return run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=4,
                                      follow_swaps=False))
    return run


@pytest.mark.parametrize("exchange", sorted({r["exchange"] for r in ROWS if r["chain"] == "ethereum"}))
def test_a_trace_that_reaches_a_set_address_is_attributed_to_that_exchange(trace, exchange):
    row = next(r for r in ROWS if r["chain"] == "ethereum" and r["exchange"] == exchange)
    result = trace([_tx(SEED, HOP, 5.0, T + 10), _tx(HOP, row["address"], 5.0, T + 20)])
    assert result["exchange"] == exchange and result["exchange_address"] == row["address"]


def test_a_trace_that_reaches_no_set_address_names_no_exchange(trace):
    result = trace([_tx(SEED, HOP, 5.0, T + 10), _tx(HOP, addr("b2"), 5.0, T + 20)])
    assert result["exchange"] is None
