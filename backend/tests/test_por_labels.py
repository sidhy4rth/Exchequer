"""Bybit's and OKX's own wallets, labelled from their proof-of-reserves lists.

Before 15 Nov 2026 Bybit had one label on each EVM chain, so a trace into any
other Bybit wallet ended "unlabelled". scripts/import_por_labels.py reads each
exchange's own PoR file and adds the wallets it lists on Ethereum, BNB Smart
Chain, Polygon and Arbitrum, each row citing the file. These tests check the
shipped rows (format, sources, no collisions) and the importer's rules, offline.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import date

import pytest

from app import config, never_flag, pipeline
from app.etherscan_client import Transaction
from app.exchange_matcher import ExchangeMatcher
from app.pipeline import TraceRequest, run_trace
from scripts import import_por_labels as por

from conftest import addr

CHAINS = por.CHAINS
SOURCE_URL = {
    "Bybit": re.compile(r"https://api2\.bybit\.com/common-static/por/bybit_por_\d{6}\.csv"),
    "OKX": re.compile(r"https://static\.okx\.com/cdn/okx/por/chain/por_csv_\d{10}_V\d+\.zip"),
}
ARCHIVE = re.compile(r"https://web\.archive\.org/web/\d{14}/https://\S+")
# A Bybit reserve wallet the October 2026 PoR file lists on Ethereum (USDT-Ethereum
# row, among others), labelled by this import; not labelled before it.
BYBIT_NEW_ETH = "0xee5b5b923ffce93a870b3104b7ca09c3db80047a"
# An OKX wallet the November 2026 file lists on ETH ("ETH, Non Staking", 25,309.57 ETH at the
# snapshot), labelled by this import; not labelled before it.
OKX_NEW_ETH = "0x0003b5aa5e30e97fcc596bb5d0f3a75255e08d4e"
BYBIT_1 = "0xf89d7b9c864f589bbf53a82105107622b35eaa40"  # "Bybit 1", labelled before; the PoR file lists it too


def _document(chain):
    return json.loads(config.CHAINS[chain].labels_path.read_text(encoding="utf-8"))


def _por_rows(chain):
    return {a: m for a, m in _document(chain)["labels"].items() if isinstance(m, dict) and "source_kind" in m}


# -- the shipped rows --------------------------------------------------------------

@pytest.mark.parametrize("chain", CHAINS)
def test_every_por_row_names_its_exchange_kind_source_and_dates(chain):
    rows = _por_rows(chain)
    assert rows, f"no proof-of-reserves rows on {chain}"
    for address, row in rows.items():
        assert re.fullmatch(r"0x[0-9a-f]{40}", address), address
        assert row["exchange"] in por.SOURCES
        assert re.fullmatch(rf"{re.escape(row['exchange'])}: Reserve Wallet \d+", row["label"])
        assert row["type"] in ("exchange_wallet", "contract_wallet")
        assert row["source_kind"] == por.SOURCES[row["exchange"]]["kind"]
        assert SOURCE_URL[row["exchange"]].fullmatch(row["source"])
        assert ARCHIVE.fullmatch(row.get("source_archive", "")), row
        published, retrieved = date.fromisoformat(row["source_date"]), date.fromisoformat(row["retrieved"])
        assert published <= retrieved <= date(2026, 11, 15)


@pytest.mark.parametrize("chain", CHAINS)
def test_the_file_says_where_its_por_rows_came_from(chain):
    note = _document(chain)["_meta"][por.META_KEY]
    exchanges = {r["exchange"] for r in _por_rows(chain).values()}
    assert set(note["added"]) == exchanges
    for exchange in exchanges:
        cite = note["sources"][exchange]
        assert SOURCE_URL[exchange].fullmatch(cite["url"]) and ARCHIVE.fullmatch(cite["archive"])
        assert re.fullmatch(r"[0-9a-f]{64}", cite["sha256"])
    for row in _por_rows(chain).values():
        assert row["source"] == note["sources"][row["exchange"]]["url"]


def test_an_address_has_one_label_on_every_chain():
    seen: dict[str, tuple[str, str]] = {}
    for chain in CHAINS:
        for address, row in _por_rows(chain).items():
            assert seen.setdefault(address, (row["exchange"], row["label"])) == (row["exchange"], row["label"])


@pytest.mark.parametrize("chain", CHAINS)
def test_no_por_row_collides_with_a_token_list_or_another_file(chain):
    tokens = never_flag.tokens(chain)
    others = por.listed(chain)
    demos = por._demo_addresses()
    for address in _por_rows(chain):
        assert never_flag._raw(chain, address) not in tokens, address
        assert address not in others, (address, others.get(address))
        assert address not in demos, address


def test_no_por_address_is_another_exchanges_on_any_chain():
    labels = {c: _document(c)["labels"] for c in config.CHAINS if config.CHAINS[c].address_family == "evm"}
    for chain in CHAINS:
        for address, row in _por_rows(chain).items():
            for other, found in labels.items():
                meta = found.get(address)
                assert not meta or meta["exchange"] == row["exchange"], (address, chain, other, meta)


def test_a_label_held_before_is_kept_as_it_was():
    for chain in CHAINS:
        assert _document(chain)["labels"][BYBIT_1] == {"exchange": "Bybit", "label": "Bybit 1", "type": "hot_wallet"}


def test_the_matcher_reads_a_por_row_as_the_exchanges_wallet():
    matcher = ExchangeMatcher.from_file(config.CHAINS["ethereum"].labels_path, chain="ethereum")
    found = matcher.lookup(BYBIT_NEW_ETH)
    assert found["exchange"] == "Bybit" and found["type"] in ("exchange_wallet", "contract_wallet")
    assert never_flag.reason("ethereum", BYBIT_NEW_ETH) == never_flag.EXCHANGE


# -- a trace into a new wallet ends at Bybit -----------------------------------------

SEED, HOP = addr("5eed"), addr("a1")
T = 1_790_000_000


def _tx(n, src, dst, value, when):
    return Transaction(hash="0x" + f"{n:064x}", from_address=src, to_address=dst, value_native=value,
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
        return run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=3,
                                      follow_swaps=False))
    return run


def test_a_transfer_into_a_new_bybit_reserve_wallet_is_attributed_to_bybit(trace):
    result = trace([_tx(1, SEED, HOP, 4.0, T), _tx(2, HOP, BYBIT_NEW_ETH, 4.0, T + 60)])
    assert result["exchange"] == "Bybit"
    assert result["exchange_address"] == BYBIT_NEW_ETH


def test_a_transfer_into_a_new_okx_wallet_is_attributed_to_okx(trace):
    result = trace([_tx(1, SEED, HOP, 4.0, T), _tx(2, HOP, OKX_NEW_ETH, 4.0, T + 60)])
    assert result["exchange"] == "OKX"
    assert result["exchange_address"] == OKX_NEW_ETH


def test_a_transfer_to_an_unlabelled_wallet_is_attributed_to_nobody(trace):
    result = trace([_tx(1, SEED, HOP, 4.0, T), _tx(2, HOP, addr("b2"), 4.0, T + 60)])
    assert result["exchange"] is None


# -- the importer's rules --------------------------------------------------------------

A, B, C = ("0x" + d * 40 for d in "abc")


def test_bybit_rows_are_read_per_network_and_other_networks_are_ignored():
    text = ("Coin,Height,Amount,Address\n"
            "USDT(ALL),-,10,\n"
            f"USDT-Ethereum,100,5,{A.upper().replace('0X', '0x')} {B}\n"
            f"USDT-BSC,200,5,{B}\n"
            f"USDT-Optimism,300,5,{C}\n"
            "SOL-Solana,400,5,42brAgAVNzMBP7aaktPvAmBSPEkehnFQejiZc53EpJFd\n")
    found = por.parse_bybit(text)
    assert set(found["ethereum"]) == {A, B} and set(found["bsc"]) == {B}
    assert found["polygon"] == {} and found["arbitrum"] == {}
    assert found["ethereum"][A] == {"USDT-Ethereum@100"}


def test_a_file_that_is_not_bybits_csv_is_refused():
    with pytest.raises(ValueError):
        por.parse_bybit("<?xml version='1.0'?><Error>NoSuchKey</Error>")


def test_okx_rows_are_read_per_network_and_a_staking_position_is_not_a_wallet():
    rows = [{"coin": "USDT-ERC20", "Type": "Non Staking", "Network": "ETH", "address": A.upper().replace("0X", "0x")},
            {"coin": "USDT-POLY", "Type": "Non Staking", "Network": "POLYGON", "address": B},
            {"coin": "USDC", "Type": "Native Staking", "Network": "ETH", "address": C},
            {"coin": "BTC", "Type": "Non Staking", "Network": "BTC", "address": "bc1qexample"},
            {"coin": "USDT-ARBITRUM", "Type": "Non Staking", "Network": "ARBITRUM", "address": "0x123"}]
    found = por.parse_okx(rows)
    assert set(found["ethereum"]) == {A} and set(found["polygon"]) == {B} and found["arbitrum"] == {}


def test_okx_rows_are_read_from_the_address_table_not_the_totals():
    text = ["coin,amount", "USDT,8265265024", "",
            "coin,Type,Network,Snapshot Height,address,amount,message,signature1,signature2",
            f"USDT,Non Staking,ETH,26313797,{A},2.4,I am an OKX address,0xsig,,extra",
            f"ETH,Native ETH Staking,ETH,26313797,0x{'d' * 96},32,I am an OKX address,0xsig,",
            "BTC,Non Staking,BTC,973994,13jTtHxBPFwZkaCdm6BwJMMJkqvTpBZccw,3000,I am an OKX address,sig,"]
    found = por.parse_okx(por._address_section(text))
    assert found["ethereum"] == {A: {"USDT (Non Staking)@ETH"}}


@pytest.mark.parametrize("account, kind, why", [
    ({"code": False, "delegated": False, "nonce": 3, "balance": 0}, "exchange_wallet", None),
    ({"code": False, "delegated": False, "nonce": 0, "balance": 5}, "exchange_wallet", None),
    ({"code": True, "delegated": True, "nonce": 9, "balance": 0}, "exchange_wallet", None),
    ({"code": True, "delegated": False, "nonce": 1, "balance": 7, "erc20": False, "safe": True},
     "contract_wallet", None),
    ({"code": True, "delegated": False, "nonce": 1, "balance": 7, "erc20": True, "safe": False}, None, "token"),
    ({"code": False, "delegated": False, "nonce": 0, "balance": 0}, None, "no activity"),
    (None, None, "not read"),
])
def test_only_a_used_wallet_that_is_not_a_token_contract_is_kept(account, kind, why):
    got_kind, got_why = por.verdict(account)
    assert got_kind == kind
    assert (got_why is None) if why is None else (why in got_why)


def test_gather_leaves_out_every_conflict_and_keeps_a_fresh_wallet():
    labels = _document("ethereum")["labels"]
    demos = por._demo_addresses()
    binance = next(a for a, m in labels.items()
                   if m.get("exchange") == "Binance" and m["type"] == "hot_wallet" and a not in demos)
    token = "0xdac17f958d2ee523a2206206994597c13d831ec7"  # USDT, a traced token
    risk = next(a for a in por._labels(config.CHAINS["ethereum"].risk_labels_path) if a not in demos)
    tokens = never_flag.tokens("ethereum")
    demo = sorted(a for a in por._demo_addresses() - set(labels) - set(por.listed("ethereum"))
                  if never_flag._raw("ethereum", a) not in tokens)[0]
    fresh = "0x" + "7" * 40
    found = {"Bybit": {"ethereum": {a: {"x"} for a in (binance, token, risk, demo, fresh, A, BYBIT_1)}},
             "OKX": {"ethereum": {A: {"y"}}}}
    candidates, conflicts, counts = por.gather(found)
    assert set(candidates["ethereum"]) == {fresh}
    why = {c["address"]: c["why"] for c in conflicts["ethereum"]}
    assert "Binance" in why[binance] and "token" in why[token] and "risk" in why[risk]
    assert "demo" in why[demo] and "both" in why[A]
    assert counts["Bybit/ethereum"]["already"] == 1  # Bybit 1 keeps its label


def test_a_new_wallet_keeps_one_number_on_every_chain():
    candidates = {"ethereum": {A: {"exchange": "Bybit"}}, "bsc": {A: {"exchange": "Bybit"}, B: {"exchange": "Bybit"}}}
    account = {"code": False, "delegated": False, "nonce": 1, "balance": 0}
    accounts = {f"{c}:{a}": account for c in candidates for a in candidates[c]}
    source = {"Bybit": {"url": "u", "archive": "w", "source_date": "2026-10-27", "retrieved": "2026-11-14"}}
    out, left = por.rows(candidates, accounts, source)
    assert out["ethereum"][A]["label"] == out["bsc"][A]["label"] != out["bsc"][B]["label"]
    assert left == {"ethereum": [], "bsc": []}
