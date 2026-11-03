"""The gambling importer asserts a label only where there is evidence for it."""
from __future__ import annotations

from scripts.import_gambling_labels import build

HOT = "0x" + "4" * 40
DEP = "0x" + "d" * 40
EXCH = "0x" + "e" * 40
SEEDS = [{"address": HOT.upper().replace("0X", "0x"), "nameTag": "Stake.com: Hot Wallet", "label": "gambling", "chainId": "1"}]


def test_deposit_rows_cite_their_sweep_and_bring_the_hot_wallet_on_that_chain_only():
    deposits = [{"address": DEP, "chain": "polygon", "platform": "Stake.com", "hot_wallet": HOT,
                 "sweeps": 3, "token": "USDT", "tx": "0xabc", "date": "2026-10-01"}]
    out = build(SEEDS, deposits, {}, {})
    assert out["polygon"][DEP]["category"] == "gambling"
    assert "Swept 3x USDT" in out["polygon"][DEP]["source"] and "0xabc" in out["polygon"][DEP]["source"]
    assert out["polygon"][HOT]["label"] == "Stake.com hot wallet"
    # no sweeps were seen on Ethereum, so nothing is asserted there
    assert out["ethereum"] == {}


def test_an_address_already_labelled_as_an_exchange_is_not_relabelled():
    deposits = [{"address": EXCH, "chain": "ethereum", "platform": "Stake.com", "hot_wallet": HOT,
                 "sweeps": 2, "token": "USDC", "tx": "0x1", "date": "2026-10-01"}]
    out = build(SEEDS, deposits, {}, {"ethereum": {EXCH}})
    assert EXCH not in out["ethereum"]


def test_tron_rows_are_kept_in_base58_and_invalid_addresses_dropped():
    tron = {"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": {"platform": "BC.Game", "sweeps": 4, "hot_wallet": "Txyz", "tx": "t1"},
            "not-an-address": {"platform": "X"}}
    out = build([], [], tron, {})
    assert list(out["tron"]) == ["TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"]
    assert out["tron"]["TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"]["entity"] == "BC.Game"
