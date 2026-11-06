"""Exchange labels name cash-out wallets, never routers, treasuries or deployers.

An exchange match ends a trace and names where the funds were cashed out, so a
wrong exchange label blames the wrong place. The importers let through 'OKX:
DEX Router 2' and 'OKX: DEX Router 4' (a scam swapping through OKX's
on-chain router came out as "cashed out at OKX"), 'Tether: Treasury' as
Bitfinex on every EVM chain, and exchanges' contract deployers. The routers
are routers now (swap detection follows through them); the rest are gone, and
both importers refuse such labels.
"""
from __future__ import annotations

import json
import re

import pytest

from app import config
from scripts import import_eth_labels, import_exchange_labels

NOT_CASH_OUT = re.compile(r"router|aggregat|relayer|paymaster|treasury|deployer|\bdex\b(?!-trade)", re.I)
OKX_ROUTERS = ("0x7d0ccaa3fac1e5a943c5168b6ced828691b46b36", "0x156acd2bc5fc336d59baae602a2bd9b5e20d6672")
LABEL_FILES = sorted(config.DATA_DIR.glob("exchange_labels*.json"))


def _labels(path):
    data = json.loads(path.read_text())
    return data.get("labels", data) if isinstance(data, dict) else {}


@pytest.mark.parametrize("path", LABEL_FILES, ids=lambda p: p.name)
def test_no_exchange_label_is_a_router_treasury_or_deployer(path):
    bad = {a: m["label"] for a, m in _labels(path).items()
           if not a.startswith("_") and isinstance(m, dict) and NOT_CASH_OUT.search(m.get("label", ""))}
    assert bad == {}


def test_the_okx_dex_routers_are_routers():
    routers = _labels(config.DATA_DIR / "router_labels.json")
    for address in OKX_ROUTERS:
        assert routers[address]["type"] == "router"
        assert routers[address]["exchange"] == "OKX DEX"


@pytest.mark.parametrize("tag", ["OKX: DEX Router 2", "OKX: Aggregation Router V2", "KuCoin: Aggregator",
                                 "Gelato: Relayer", "Tether: Treasury", "Binance: Deployer 3"])
def test_the_eth_importer_skips_what_is_not_a_cash_out_wallet(tag):
    assert import_eth_labels.SKIP_TAG.search(tag)


def test_the_eth_importer_skips_the_dex_dataset():
    assert import_eth_labels.SKIP_SLUG.search("dex")


@pytest.mark.parametrize("tag", ["Binance 14", "OKX 9", "Dex-Trade 2", "Kraken: Hot Wallet"])
def test_the_eth_importer_keeps_real_exchange_wallets(tag):
    assert not import_eth_labels.SKIP_TAG.search(tag)


@pytest.mark.parametrize("label, kept", [("Tether: Treasury", False), ("Bitfinex: Deployer 1", False),
                                         ("OKX: DEX Router 4", False), ("Bitfinex 5", True), ("Dex-Trade 2", True)])
def test_the_dataset_importer_refuses_what_is_not_a_cash_out_wallet(label, kept):
    assert import_exchange_labels.is_cash_out_label(label) is kept


# -- a deposit address is one customer's, said so explicitly (audit r1-labels-data-5) --
from app.exchange_matcher import is_deposit_label  # noqa: E402


@pytest.mark.parametrize("label, deposit", [
    ("Binance Dep: 0xe057cbcd030b6b56e1f235efc5412d42664b3ab8", True),
    ("Kraken: Deposit Address 3", True),
    ("Binance: Deposit Funder", False), ("OKX: Deposit Supplier", False),
    ("Bitcoin Suisse: Eth2 Depositor 1", False), ("AltCoinTrader: Binance Deposit 1", False),
    ("Coinbase: Batch Deposit 1", False), ("CoinList: WBTC Merchant Deposit Address", False),
    ("Poloniex Deposit", False), ("Binance 14", False),
])
def test_only_an_explicit_deposit_label_is_a_deposit(label, deposit):
    from app import tron_tags
    from scripts import seed_bsc_labels
    assert is_deposit_label(label) is deposit
    assert (import_exchange_labels.classify(label) == "deposit_wallet") is deposit
    assert (import_eth_labels.wallet_type(label) == "deposit_wallet") is deposit
    assert (seed_bsc_labels.wallet_type(label) == "deposit_wallet") is deposit
    assert (tron_tags.wallet_type(label) == "deposit_wallet") is deposit  # seed_tron_labels and live tags


@pytest.mark.parametrize("tag", ["Binance: Deposit Funder 2", "OKX: Deposit Supplier", "Kraken: Eth2 Depositor",
                                 "Binance: Binance-Peg Tokens", "Binance: AE Token Swap"])
def test_exchange_infrastructure_tags_are_never_imported_or_carried(tag):
    assert import_eth_labels.SKIP_TAG.search(tag)


@pytest.mark.parametrize("path", LABEL_FILES, ids=lambda p: p.name)
def test_no_shipped_deposit_wallet_is_an_exchanges_own_or_another_firms(path):
    bad = {a: m["label"] for a, m in _labels(path).items()
           if not a.startswith("_") and m.get("type") == "deposit_wallet" and not is_deposit_label(m["label"])}
    assert bad == {}


def test_the_port_never_carries_a_funder_peg_or_swap_address():
    from scripts import port_evm_labels
    carried = port_evm_labels.ethereum_candidates()
    assert not [m["label"] for m in carried.values()
                if re.search(r"funder|supplier|depositor|peg|swap", m["label"], re.I)]
