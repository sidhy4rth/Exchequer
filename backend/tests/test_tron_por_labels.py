"""Tron wallets that exchanges publish as their own (proof of reserves).

The rows whose source starts with "por:" in data/exchange_labels_tron.json
come from each exchange's own address disclosure, read by
scripts/import_por_tron_labels.py. The failures that matter: a row whose
source cannot be shown, an address that is not one, an exchange wallet that
silently hides a freeze or a sanction on the same address, and a trace that
does not stop at one of these wallets and name the exchange. Every address
here is read from the label file, never typed.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import date

import pytest

from app import config, never_flag
from app import pipeline as main
from app.etherscan_client import Transaction, is_tron_address
from app.exchange_matcher import ExchangeMatcher, is_deposit_label
from app.pipeline import TraceRequest, run_trace
from app.tron_tags import CANONICAL, exchange_for_tag
from scripts import import_por_tron_labels as por
from scripts.seed_tron_labels import keep_previous

TRON = config.CHAINS["tron"]
DOC = json.loads(TRON.labels_path.read_text())
LABELS = DOC["labels"]
SOURCES = DOC["_meta"]["proof_of_reserves"]["sources"]
POR_ROWS = {a: m for a, m in LABELS.items() if str(m.get("source", "")).startswith("por:")}
# Two unlabelled wallets the other Tron trace tests already use (test_tron_tags.py).
SEED = "TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts"
HOP = "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU"
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def wallet_of(exchange: str) -> str:
    return next(a for a, m in sorted(POR_ROWS.items()) if m["exchange"] == exchange)


# -- the data ------------------------------------------------------------------

def test_the_por_rows_cover_the_exchanges_tron_was_missing():
    assert {m["exchange"] for m in POR_ROWS.values()} >= {"Bybit", "Huobi / HTX", "KuCoin", "Binance"}


@pytest.mark.parametrize("address", sorted(POR_ROWS))
def test_every_por_row_is_a_valid_tron_exchange_wallet_with_a_known_source(address):
    row = POR_ROWS[address]
    assert is_tron_address(address)
    assert row["source"] in SOURCES and row["source"] in por.SOURCES
    assert SOURCES[row["source"]]["exchange"] == row["exchange"]
    assert row["exchange"] in set(CANONICAL.values())
    # A PoR list never says one customer's address, nor hot or cold unless it does.
    assert row["type"] == "exchange_wallet" and not is_deposit_label(row["label"])
    assert exchange_for_tag(row["label"]) == row["exchange"]  # reads as its exchange, as every row must


@pytest.mark.parametrize("source_id", sorted(SOURCES))
def test_every_source_says_where_and_when_it_was_read(source_id):
    record, known = SOURCES[source_id], por.SOURCES[source_id]
    assert record["url"] == known.url and record["url"].startswith("https://")
    assert record["archive_url"] is None or record["archive_url"].startswith("https://web.archive.org/web/")
    assert ISO.match(record["published"]) and ISO.match(record["retrieved"])
    assert date.fromisoformat(record["published"]) <= date.fromisoformat(record["retrieved"])
    assert re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
    assert record["kind"] and record["statement"]
    added = sum(1 for m in POR_ROWS.values() if m["source"] == source_id)
    assert added == record["added"]
    assert record["added"] + len(record["corroborated"]) + len(record["left_out"]) == record["tron_addresses_listed"]


def test_an_address_already_labelled_keeps_its_tronscan_row():
    for record in SOURCES.values():
        for address, label in record["corroborated"].items():
            assert LABELS[address]["label"] == label
            assert LABELS[address]["exchange"] == record["exchange"]


def test_what_was_left_out_is_not_labelled_from_that_source():
    for source_id, record in SOURCES.items():
        for address in record["left_out"]:
            assert LABELS.get(address, {}).get("source") != source_id


def test_no_por_wallet_hides_a_freeze_a_sanction_or_a_demo():
    # An exchange wallet suppresses an issuer's freeze and every store label on
    # the same address (never_flag.freeze_refusal), so none may overlap.
    elsewhere = por.listed_elsewhere()
    overlap = {a: elsewhere[a] for a in POR_ROWS if a in elsewhere}
    assert overlap == {}
    assert {a: k for a in POR_ROWS if (k := never_flag.kind("tron", a)) != never_flag.EXCHANGE} == {}


def test_the_counts_match_the_rows():
    counts = DOC["_meta"]["counts"]
    assert counts["labels"] == len(LABELS)
    by_exchange: dict[str, int] = {}
    for meta in LABELS.values():
        by_exchange[meta["exchange"]] = by_exchange.get(meta["exchange"], 0) + 1
    assert counts["by_exchange"] == by_exchange


def test_no_source_is_too_large_for_the_json_file():
    # OKX's 474,530-address list would make this file 91 MB; it waits for a compact store.
    for source_id in SOURCES:
        assert sum(1 for m in POR_ROWS.values() if m["source"] == source_id) <= por.MAX_FILE_ROWS


def test_the_loader_reads_every_row():
    matcher = ExchangeMatcher.from_file(TRON.labels_path, chain="tron")
    assert len(matcher) == len(LABELS)
    address = wallet_of("Bybit")
    assert matcher.lookup(address)["exchange"] == "Bybit"


# -- the importer's parsers -------------------------------------------------------

def test_the_bybit_parser_reads_only_tron_rows():
    one, two = sorted(a for a, m in POR_ROWS.items() if m["exchange"] == "Bybit")[:2]
    text = ("Coin,Height,Amount,Address\nA(ALL),-,1,\n"
            f"USDT-Tron,1,5,{one} {two}\nUSDT-Ethereum,1,5,0x{'ab' * 20}\nTRX-TRX,1,2,{one}\n")
    assert list(por.parse_bybit_csv(text.encode())) == [(one, "USDT"), (two, "USDT"), (one, "TRX")]


def test_the_htx_parser_reads_the_address_section_and_marks_unsigned_rows():
    signed, unsigned = sorted(a for a, m in POR_ROWS.items() if m["exchange"] == "Huobi / HTX")[:2]
    text = ("coin,snapshot height,balance\nTRX(All),-,9\n\ncoin,address,snapshot height,balance,message,signature\n"
            f"TRX,{signed},1,5,huobi,abcd\nU-TRC20,{unsigned},1,5,-,-\nBTC,1abc,1,5,huobi,abcd\n")
    assert list(por.parse_htx_csv(text.encode())) == [(signed, "TRX"), (unsigned, "U-TRC20 (unsigned)")]


def test_the_blog_parser_reads_tronscan_links_only():
    address = wallet_of("KuCoin")
    page = f'<a href="https://tronscan.org/#/address/{address}">x</a> T{"1" * 33} not linked'
    assert list(por.parse_tronscan_links(page.encode())) == [(address, "")]


def test_the_okx_parser_keeps_tron_rows_and_marks_signed_ones():
    one, two = sorted(POR_ROWS)[:2]
    lines = ["coin,amount", "TRX,5", "",
             "coin,Type,Network,Snapshot Height,address,amount,message,signature1,signature2",
             f"USDT-TRC20,Non Staking,TRON,1,{one},3.5,I am an OKX address,c2ln,",
             f"TRX,Non Staking,TRON,1,{two},0,I am an OKX address,,",
             "BTC,Non Staking,BTC,1,1abc,3,I am an OKX address,c2ln,"]
    assert list(por.parse_okx_csv(iter(lines))) == [(one, "USDT-TRC20" + por.SIGNED), (two, "TRX")]


def test_the_tronscan_seeder_never_replaces_a_por_row():
    address = wallet_of("Bybit")
    kept = {address: {"exchange": "Bybit", "label": "Bybit Hot", "type": "hot_wallet"}}
    keep_previous(kept, {address: POR_ROWS[address]}, dropped={address})
    assert kept[address] == POR_ROWS[address]


def test_the_tronscan_seeder_still_drops_its_own_rows_it_now_refuses():
    old = {"exchange": "Bybit", "label": "Bybit 3", "type": "exchange_wallet"}
    kept: dict = {}
    assert keep_previous(kept, {SEED: old}, dropped={SEED}) == 0 and kept == {}


# -- a trace ---------------------------------------------------------------------

def tx(src, dst, value, when):
    return Transaction(hash=f"{abs(hash((src, dst, when))):064x}", from_address=src, to_address=dst,
                       value_native=value, value_wei=int(value * 1e6), timestamp=when,
                       block_number=when // 3, is_error=False, asset="USDT")


@pytest.fixture
def tron_trace(monkeypatch):
    def run(history):
        class Source:
            def get_outgoing_transactions(self, address, limit=None):
                return [t for t in history if t.from_address == address]

            def is_contract(self, address):
                return False

        @contextmanager
        def open_source(chain, asset):
            yield Source()
        monkeypatch.setattr(main, "open_source", open_source)
        monkeypatch.setattr(main.config, "TRONSCAN_API_KEY", None)  # no live tags: the file alone
        return run_trace(TraceRequest(address=SEED, chain="tron", asset="USDT", max_depth=3))
    return run


@pytest.mark.parametrize("exchange", ["Bybit", "Huobi / HTX"])
def test_a_tron_transfer_into_a_por_wallet_is_attributed_to_that_exchange(tron_trace, exchange):
    wallet = wallet_of(exchange)
    result = tron_trace([tx(SEED, HOP, 100.0, 1_700_000_000), tx(HOP, wallet, 99.0, 1_700_000_100)])
    assert result["exchange"] == exchange
    assert result["exchange_address"] == wallet
    assert "Reserves Wallet" in result["exchange_label"]


def test_a_transfer_that_never_reaches_one_is_not_attributed(tron_trace):
    result = tron_trace([tx(SEED, HOP, 100.0, 1_700_000_000)])
    assert result["exchange"] is None
