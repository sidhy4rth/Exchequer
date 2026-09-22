"""Tests for reading crypto addresses out of other governments' sanctions lists.

Most of these lists carry addresses in free text, so the parsing that matters
is the chain an address is filed under: a BNB-chain address filed as Ethereum
would never match, and a lifted seizure order must not accuse anyone.
"""
from __future__ import annotations

import json
from datetime import date

import scripts.import_intl_sanctions as intl
from scripts.import_intl_sanctions import addresses_in, chain_hint

ETH_ADDR = "0x175d44451403Edf28469dF03A9280c1197ADb92c"
TRON_ADDR = "TXEsK1sEsKjZ1xtHitnyAAoqw3WLdYdRNW"


def test_the_chain_named_before_an_address_decides_where_it_is_filed():
    text = f"(1) ETH: {ETH_ADDR} (2) BNB: {ETH_ADDR} (3) USDT: {TRON_ADDR}"
    assert addresses_in(text) == [(ETH_ADDR, "ethereum"), (ETH_ADDR, "bsc"), (TRON_ADDR, "tron")]


def test_a_token_name_alone_does_not_pick_an_evm_chain():
    assert chain_hint("USDT: ") is None
    assert chain_hint("wallet ") is None


def test_a_wallet_named_only_in_lifted_orders_is_left_out(monkeypatch):
    lifted, current = "0x" + "1" * 40, "0x" + "2" * 40
    entities = [
        {"id": "w1", "schema": "CryptoWallet", "properties": {"publicKey": [lifted]}},
        {"id": "w2", "schema": "CryptoWallet", "properties": {"publicKey": [current], "currency": ["ETH"]}},
        {"id": "s1", "schema": "Sanction", "properties": {
            "entity": ["w1"], "authorityId": ["ASO 1/21"], "endDate": ["2022-01-01"]}},
        {"id": "s2", "schema": "Sanction", "properties": {
            "entity": ["w2"], "authorityId": ["ASO 9/26"]}},
    ]
    index = {"resources": [{"name": "entities.ftm.json", "url": "entities"}]}

    def fake_fetch(url):
        if url == "entities":
            return "\n".join(json.dumps(e) for e in entities).encode()
        return json.dumps(index).encode()

    monkeypatch.setattr(intl, "fetch", fake_fetch)
    rows, _ = intl.read_opensanctions("il_mod_crypto", date(2026, 9, 23))

    assert [(address, hint) for address, hint, _ in rows] == [(current, "ethereum")]
    assert "ASO 9/26" in rows[0][2]["source"]
