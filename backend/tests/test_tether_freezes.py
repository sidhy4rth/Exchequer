"""Tests for replaying Tether's USDT blacklist events into the set frozen today.

The replay decides who is named as frozen, so the case that matters is a
release: an address Tether unfroze must drop out, and one frozen again after a
release must come back.
"""
from __future__ import annotations

import json

import httpx
import pytest

from scripts import import_tether_freezes as freezes
from scripts.import_tether_freezes import _tron_hex, replay


def ev(block, index, address, tx="0x"):
    return (block, index, address, tx, 0)


def test_a_freeze_with_no_release_is_frozen():
    assert set(replay([ev(1, 0, "a")], [])) == {"a"}


def test_a_released_address_is_not_frozen():
    assert replay([ev(1, 0, "a")], [ev(2, 0, "a")]) == {}


def test_frozen_again_after_a_release_is_frozen_with_the_latest_freeze():
    frozen = replay([ev(1, 0, "a", "0x1"), ev(3, 0, "a", "0x3")], [ev(2, 0, "a")])
    assert frozen["a"][3] == "0x3"


def test_order_within_a_block_follows_the_log_index():
    assert replay([ev(5, 1, "a")], [ev(5, 2, "a")]) == {}
    assert set(replay([ev(5, 2, "a")], [ev(5, 1, "a")])) == {"a"}


def test_a_tron_address_converts_to_its_abi_hex():
    # TR7NHq... is the USDT contract; its 20-byte body is a614f803...
    assert _tron_hex("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t") == "a614f803b6fd780986a42c78ec9c7f77e6ded13c"


def tron_client(*responses):
    """An httpx client that answers each request in turn; no network."""
    answers = iter(responses)
    return httpx.Client(transport=httpx.MockTransport(lambda _request: next(answers)))


EVENT = {"result": {"_user": "0x" + "ab" * 20}, "block_number": 5, "event_index": 0,
         "transaction_id": "tx1", "block_timestamp": 1_700_000_000_000}


def test_every_page_of_tron_events_is_read(monkeypatch):
    monkeypatch.setattr(freezes.time, "sleep", lambda _seconds: None)
    client = tron_client(
        httpx.Response(200, json={"success": True, "data": [EVENT], "meta": {"fingerprint": "next"}}),
        httpx.Response(200, json={"success": True, "data": [EVENT], "meta": {}}),
    )
    assert len(freezes.tron_events(client, "AddedBlackList")) == 2


@pytest.mark.parametrize("response", [
    httpx.Response(429, json={"Error": "rate limited"}),
    httpx.Response(500, text="server error"),
    httpx.Response(200, json={"success": False, "error": "busy"}),
    httpx.Response(200, json={"message": "no data key at all"}),
])
def test_a_bad_answer_stops_the_import_rather_than_looking_like_the_last_page(response):
    """A rate limit used to end the read quietly, so a freeze list came out short."""
    with pytest.raises((httpx.HTTPError, freezes.TronReadError)):
        freezes.tron_events(tron_client(response), "AddedBlackList")


def test_a_bad_answer_partway_through_also_stops_the_import(monkeypatch):
    monkeypatch.setattr(freezes.time, "sleep", lambda _seconds: None)
    client = tron_client(
        httpx.Response(200, json={"success": True, "data": [EVENT], "meta": {"fingerprint": "next"}}),
        httpx.Response(429, json={"Error": "rate limited"}),
    )
    with pytest.raises(httpx.HTTPError):
        freezes.tron_events(client, "AddedBlackList")


def test_burn_and_system_addresses_are_not_wallets():
    from scripts.import_tether_freezes import is_system_address
    assert is_system_address("0x" + "0" * 40)
    assert is_system_address("0x" + "0" * 38 + "18")
    assert not is_system_address("0x9faf5515f177f3a8a845d48c19032b33cc54c09c")


# -- infrastructure is left out (audit r1-scripts-3) -------------------------------
from app import config  # noqa: E402

USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
METAMASK_ROUTER = "0x881d40237659c251811cec9c364ef91dc08d300c"
WALLET = "0x" + "4" * 40


def _entry(day="2021-08-05"):
    return {"category": "frozen", "entity": "Tether (USDT freeze)", "label": f"USDT frozen by Tether on {day}",
            "source": "Tether USDT contract on Ethereum, AddedBlackList event, tx 0x1"}


def test_the_usdt_contract_and_a_router_are_left_out_and_listed():
    kept, excluded, review = freezes.leave_out("ethereum", {USDT: _entry(), METAMASK_ROUTER: _entry(), WALLET: _entry()})
    assert set(kept) == {WALLET} and review == []
    assert excluded[USDT]["why"] == "token contract" and excluded[METAMASK_ROUTER]["why"] == "DEX router"


def test_a_frozen_exchange_deposit_stays_listed():
    deposit = next(a for a, m in json.loads(config.CHAINS["ethereum"].labels_path.read_text())["labels"].items()
                   if m["type"] == "deposit_wallet")
    kept, excluded, review = freezes.leave_out("ethereum", {deposit: _entry()})
    assert deposit in kept and not excluded and not review


def test_a_frozen_exchange_hot_wallet_stops_the_import(tmp_path, monkeypatch):
    hot = next(a for a, m in json.loads(config.CHAINS["ethereum"].labels_path.read_text())["labels"].items()
               if m["type"] != "deposit_wallet")
    written = []
    monkeypatch.setattr(freezes, "write", lambda *a, **k: written.append(a))
    assert freezes._screened("ethereum", {hot: _entry(), WALLET: _entry()}, {}, dry_run=False) == 1
    assert written == []


def test_screen_held_moves_infrastructure_to_excluded_offline(tmp_path, monkeypatch):
    for name in ("frozen_labels.json", "frozen_labels_tron.json", "exchange_labels.json", "router_labels.json",
                 "exchange_labels_tron.json", "never_flag_tokens.json"):
        source = config.DATA_DIR / name
        target = tmp_path / name
        if name.startswith("frozen"):
            target.write_text(json.dumps({"_meta": {"counts": {"frozen": 2}}, "labels": (
                {USDT: _entry(), WALLET: _entry()} if name == "frozen_labels.json" else {})}))
        else:
            target.write_text(source.read_text())
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(freezes, "eth_events", lambda *a: pytest.fail("no network"))
    assert freezes.screen_held(dry_run=False) == 0
    written = json.loads((tmp_path / "frozen_labels.json").read_text())
    assert set(written["labels"]) == {WALLET}
    assert written["_meta"]["excluded"][USDT]["why"] == "token contract"
    assert written["_meta"]["counts"] == {"frozen": 1, "excluded": 1}
