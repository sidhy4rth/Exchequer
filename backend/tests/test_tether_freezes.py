"""Tests for replaying Tether's USDT blacklist events into the set frozen today.

The replay decides who is named as frozen, so the case that matters is a
release: an address Tether unfroze must drop out, and one frozen again after a
release must come back.
"""
from __future__ import annotations

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
