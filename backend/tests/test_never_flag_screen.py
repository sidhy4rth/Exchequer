"""Importer view of the never-flag rule (never_flag.reason/screen). Token contracts, DEX routers, exchange wallets and burn addresses carry no screening label.

Tether's blacklist names its own USDT contract and the MetaMask swap router, and
the Ethereum freeze import kept both (the Tron import dropped only Tron's USDT),
so a trace through a MetaMask swap printed "Frozen by Tether" and offered a
Tether letter naming the router (audit r1-scripts-3).
"""
from __future__ import annotations

import json

import pytest

from app import config, never_flag

USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
METAMASK_ROUTER = "0x881d40237659c251811cec9c364ef91dc08d300c"


def _labels(name):
    return json.loads((config.DATA_DIR / name).read_text())["labels"]


def test_the_usdt_contract_and_the_metamask_router_are_never_flagged():
    assert never_flag.reason("ethereum", USDT) == never_flag.TOKEN
    assert never_flag.reason("ethereum", METAMASK_ROUTER) == never_flag.ROUTER
    assert never_flag.reason("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t") == never_flag.TOKEN
    assert never_flag.reason("tron", "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb") == never_flag.SYSTEM


def test_an_exchange_hot_wallet_is_never_flagged_but_a_deposit_address_may_be():
    labels = _labels("exchange_labels.json")
    hot = next(a for a, m in labels.items() if m["type"] != "deposit_wallet")
    deposit = next(a for a, m in labels.items() if m["type"] == "deposit_wallet")
    assert never_flag.reason("ethereum", hot) == never_flag.EXCHANGE
    assert never_flag.reason("ethereum", deposit) is None  # one customer's account


def test_an_ordinary_wallet_is_not_on_the_list():
    assert never_flag.reason("ethereum", "0x" + "7" * 40) is None


def test_a_reviewed_exception_is_allowed(tmp_path, monkeypatch):
    (tmp_path / never_flag.NEVER_FLAG_FILE).write_text(json.dumps({"tokens": [USDT], "allow": {USDT: "reviewed"}}))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    never_flag.clear_cache()
    try:
        assert never_flag.reason("ethereum", USDT) is None
    finally:
        monkeypatch.undo()
        never_flag.clear_cache()


def test_the_token_file_is_sorted_valid_and_names_no_one():
    from app.etherscan_client import is_valid_address
    document = json.loads((config.DATA_DIR / never_flag.NEVER_FLAG_FILE).read_text())
    tokens = document["tokens"]
    assert tokens == sorted(set(tokens)) and len(tokens) == document["_meta"]["counts"]["tokens"]
    assert all(is_valid_address(t) for t in tokens)
    assert "mukesh" not in json.dumps(document["_meta"]).lower()


# Lists of parties: no entry may be a token contract, a router, a burn address or an
# exchange wallet that is not a deposit address. A deposit address may be listed.
PARTY_FILES = sorted(p.name for pattern in ("frozen_labels*.json", "risk_labels*.json", "intl_sanctions*.json",
                                            "threat_labels*.json", "gambling_labels*.json")
                     for p in config.DATA_DIR.glob(pattern))


@pytest.mark.parametrize("name", PARTY_FILES)
def test_no_shipped_screening_label_names_infrastructure(name):
    document = json.loads((config.DATA_DIR / name).read_text())
    chain = document.get("_meta", {}).get("chain") or "ethereum"
    assert never_flag.screen(chain, document["labels"]) == {}
