"""The exchange label files name cash-out wallets: no token contract, no
infrastructure, and another firm's account attributed to the exchange that holds it.

An exchange match ends a trace and names the company a letter goes to. On 15 Nov
2026 the BNB Smart Chain file called the BUSD token contract a Binance wallet and
the Ethereum file called the Kanga Exchange Token contract a Kanga wallet, so
funds paid into either read as cashed out there (scripts/clean_exchange_labels.py).
"""
from __future__ import annotations

import copy
import json

import pytest

from app import config, never_flag
from app.exchange_matcher import ExchangeMatcher, firm_account
from app.request_letters import draft
from scripts import clean_exchange_labels

from test_letter_kinds import labelled

CHAINS = sorted(config.CHAINS)
BUSD_BSC = "0xe9e7cea3dedca5984780bafc599bd69add087d56"
KANGA_TOKEN = "0x471d113059324321749e097705197a2b44a070fc"


def _file_labels(chain_key):
    chain = config.get_chain(chain_key)
    return ExchangeMatcher.from_file(chain.labels_path, chain=chain.key).entries()


@pytest.mark.parametrize("chain_key", CHAINS)
def test_no_exchange_label_is_a_token_contract(chain_key):
    tokens = never_flag.tokens(chain_key)
    bad = {a: m["label"] for a, m in _file_labels(chain_key) if never_flag._raw(chain_key, a) in tokens}
    assert bad == {}


def test_the_guard_reads_the_same_token_lists_that_named_busd_and_kanga():
    assert never_flag._raw("bsc", BUSD_BSC) in never_flag.tokens("bsc")
    assert never_flag._raw("ethereum", KANGA_TOKEN) in never_flag.tokens("ethereum")
    assert never_flag.kind("bsc", BUSD_BSC) == never_flag.TOKEN  # no longer also an exchange wallet


@pytest.mark.parametrize("chain_key", CHAINS)
def test_no_infrastructure_row_is_left(chain_key):
    labels = dict(_file_labels(chain_key))
    assert not set(clean_exchange_labels.INFRASTRUCTURE) & set(labels)


@pytest.mark.parametrize("chain_key", CHAINS)
def test_another_firms_account_is_attributed_to_the_exchange_that_holds_it(chain_key):
    for address, meta in _file_labels(chain_key):
        found = firm_account(meta["label"])
        if found:
            assert meta["exchange"].casefold() != found.casefold(), (address, meta)
        if address in clean_exchange_labels.FIRM_ACCOUNTS:
            holder, firm = clean_exchange_labels.FIRM_ACCOUNTS[address]
            assert meta["exchange"] == holder and firm_account(meta["label"], holder) == firm
            assert meta["type"] != "deposit_wallet"  # the firm's account, not one customer's deposit address


def test_the_firm_account_rows_are_all_found():
    ethereum = dict(_file_labels("ethereum"))
    assert all(a in ethereum for a in clean_exchange_labels.FIRM_ACCOUNTS)
    assert ethereum["0xb3f923eabaf178fc1bd8e13902fc5c61d3ddef5b"]["exchange"] == "Binance"  # Wintermute's


@pytest.mark.parametrize("label, exchange, firm", [
    ("Wintermute: Binance Deposit", "Binance", "Wintermute"),
    ("AltCoinTrader: Binance Deposit 1", "Binance", "AltCoinTrader"),
    ("Deribit: Coinbase Prime Custody", "Coinbase", "Deribit"),
    ("ChangeNOW: HTX Deposit", "Huobi / HTX", "ChangeNOW"),
    ("AltCoinTrader: Binance Deposit 1", "AltCoinTrader", None),  # still attributed to the firm
    ("Binance: Deposit Funder", "Binance", None), ("Binance: Deposit 1", "Binance", None),
    ("Coinbase: Batch Deposit 1", "Coinbase", None), ("Huobi: Deposit", "Huobi / HTX", None),
    ("CoinList: WBTC Merchant Deposit Address", "CoinList", None),
    ("Bitcoin Suisse: Eth2 Depositor 3", "Bitcoin Suisse", None), ("Binance 14", "Binance", None),
])
def test_a_firms_account_label_is_told_from_an_exchanges_own(label, exchange, firm):
    assert firm_account(label, exchange) == firm


def test_the_letter_names_the_firm_as_the_account_holder():
    label = "Wintermute: Binance Deposit"
    text = draft("case-1", labelled("exchange_wallet", label=label, exchange_label=label), "exchange")
    assert "deposit address of Wintermute's account at Binance" in text
    assert "the account is Wintermute's" in text
    assert "does not belong to any one customer" not in text


def test_an_exchanges_own_wallet_letter_is_unchanged():
    text = draft("case-1", labelled("hot_wallet", label="Binance 14", exchange_label="Binance 14"), "exchange")
    assert "a wallet Binance operates itself" in text and "account at" not in text


def test_the_instant_seed_keeps_no_row_the_label_file_no_longer_names_as_that_service():
    seed = json.loads((config.DATA_DIR / "instant_exchangers.json").read_text())
    assert "0x6ba7fe01eec4c6a4308c8e2b35970e0488ce9a86" not in {r["address"] for r in seed["rows"]}  # HTX now


# -- the cleaner itself --------------------------------------------------------------
def _document():
    infra = next(iter(clean_exchange_labels.INFRASTRUCTURE))
    firm = "0xb0afffd6f6ad77f61927803ade6dbd47f1a1c356"
    return {"_meta": {}, "labels": {
        BUSD_BSC: {"exchange": "Binance", "label": "Binance: BUSD Stablecoin", "type": "exchange_wallet"},
        infra: {"exchange": "Binance", "label": "Binance Pool", "type": "exchange_wallet"},
        firm: {"exchange": "BTSE", "label": "BTSE: Cobo Deposit", "type": "exchange_wallet"},
        "0x" + "4" * 40: {"exchange": "Binance", "label": "Binance 14", "type": "hot_wallet"},
    }}


def test_the_cleaner_removes_tokens_and_infrastructure_and_moves_firm_accounts():
    document = _document()
    changes = clean_exchange_labels.clean(document, "bsc")
    assert set(changes["removed"]) == {BUSD_BSC, next(iter(clean_exchange_labels.INFRASTRUCTURE))}
    assert document["labels"]["0xb0afffd6f6ad77f61927803ade6dbd47f1a1c356"]["exchange"] == "Cobo"
    assert document["labels"]["0x" + "4" * 40]["exchange"] == "Binance"  # an ordinary wallet is untouched


def test_the_cleaner_changes_nothing_the_second_time():
    document = _document()
    clean_exchange_labels.clean(document, "bsc")
    again = copy.deepcopy(document)
    assert clean_exchange_labels.clean(again, "bsc") == {"removed": {}, "attributed_to_custodian": {}}
    assert again == document


def test_the_cleaner_drops_a_seed_row_whose_label_moved_and_keeps_the_rest():
    seed = {"rows": [{"chain": "ethereum", "address": "0xa", "service": "ChangeNOW"},
                     {"chain": "ethereum", "address": "0xb", "service": "ChangeNOW"}]}
    labels = {"ethereum": {"0xa": {"exchange": "Huobi / HTX"}, "0xb": {"exchange": "ChangeNOW"}}}
    dropped = clean_exchange_labels.clean_instant_seed(seed, labels)
    assert [r["address"] for r in seed["rows"]] == ["0xb"] and len(dropped) == 1
