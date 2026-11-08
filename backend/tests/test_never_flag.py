"""The never-flag policy (app/never_flag.py): infrastructure no store row may label.

What matters here:
  * the zero/burn range and placeholders are system addresses on EVM and Tron;
  * a token, router or system address keeps no store label at all, while an
    exchange, deposit or casino wallet keeps only an issuer's freeze;
  * real addresses from the repo's own files resolve to the right kind;
  * the token list in data/ is well formed and names no team member.
"""
from __future__ import annotations

import pytest

from app import label_rules, never_flag
from app.label_store import encode_address
from app.never_flag import DEPOSIT, EXCHANGE, GAMBLING, NO_POISONING, ROUTER, SYSTEM, TOKEN, blocks, kind

from conftest import addr

TRON_ZERO = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"


@pytest.mark.parametrize("address", [
    "0x" + "0" * 40, "0x" + "0" * 36 + "dead", "0x" + "e" * 40,
    "0xdead000000000000000042069420694206942069", TRON_ZERO])
def test_burn_and_placeholder_addresses_are_system(address):
    assert never_flag.is_system(encode_address(address))
    assert kind("tron" if address.startswith("T") else "ethereum", address) == SYSTEM


def test_an_ordinary_wallet_is_nothing():
    assert not never_flag.is_system(encode_address(addr("5ca33e")))
    assert kind("ethereum", addr("5ca33e"), with_gambling=True) is None
    assert kind("ethereum", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t") is None  # a Tron address is not an EVM one


@pytest.mark.parametrize("what, category, blocked", [
    (SYSTEM, "frozen", True), (TOKEN, "frozen", True), (ROUTER, "mixer", True),
    (EXCHANGE, "poisoning", True), (EXCHANGE, "frozen", False),
    (DEPOSIT, "scam", True), (DEPOSIT, "frozen", False),
    (GAMBLING, "stolen", True), (GAMBLING, "frozen", False),
    (NO_POISONING, "poisoning", True), (NO_POISONING, "scam", False),
    (None, "poisoning", False),
])
def test_the_policy(what, category, blocked):
    assert blocks(what, category) is blocked


@pytest.mark.parametrize("chain, address, expected", [
    ("ethereum", "0xdac17f958d2ee523a2206206994597c13d831ec7", TOKEN),     # USDT, config.py
    ("ethereum", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", TOKEN),     # WETH, never_flag_tokens.txt
    ("ethereum", "0x6b175474e89094c44da98b954eedeac495271d0f", TOKEN),     # DAI
    ("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", TOKEN),                 # USDT on Tron
    ("ethereum", "0x11111112542d85b3ef69ae05771c2dccff4faa26", ROUTER),    # 1inch
    ("ethereum", "0x28c6c06298d514db089934071355e5743bf21d60", EXCHANGE),  # Binance 14
    ("ethereum", "0x000f9f5f6db6d63bb64bb55d58272a1ce660fd90", DEPOSIT),
    ("tron", "TWBPGLwQw2EbqYLLw1DJnTDt2ZQ9yJW1JJ", EXCHANGE),              # WhiteBIT
])
def test_real_infrastructure_resolves_to_its_kind(chain, address, expected):
    assert kind(chain, address) == expected


def test_a_casino_wallet_is_checked_only_when_asked():
    cloudbet = "TAJ3SYGtVjGqm61qoGzZN9bQY6MST2JQVL"
    assert kind("tron", cloudbet) is None
    assert kind("tron", cloudbet, with_gambling=True) == GAMBLING


def test_the_token_list_is_well_formed_and_names_no_one():
    text = never_flag.TOKENS_FILE.read_text()
    assert not label_rules.INTERNAL_NAMES.search(text)
    entries = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    assert entries and len(entries) == len(set(entries))
    for entry in entries:
        assert encode_address(entry) is not None, entry


def test_a_list_takes_the_last_field_of_each_line(tmp_path):
    listed = tmp_path / "list.txt"
    listed.write_text(f"# reason\tfile\taddress\nspam-token recipient\tops.tsv\t{addr('5e2c')}\n"
                      f"{addr('70c3').upper().replace('0X', '0x')}\nTR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t\n")
    assert never_flag.read_list(listed, "ethereum") == {encode_address(addr("5e2c")), encode_address(addr("70c3"))}
    assert never_flag.read_list(listed, "tron") == {encode_address("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")}


# -- r1-labels-data-1, round 2: routers on chains with no router file ---------
ROUTER_1INCH_V5 = "0x1111111254eeb25477b68fb85ed929f73a960582"   # router_labels.json
ROUTER_TRANSIT_BSC = "0x638f32fe09baec1fdc54f962e3e8e5f2b286aa70"  # router_labels_bsc.json


@pytest.mark.parametrize("chain", ["ethereum", "bsc", "polygon", "arbitrum"])
def test_every_evm_router_file_counts_on_every_evm_chain(chain):
    assert kind(chain, ROUTER_1INCH_V5) == ROUTER
    assert kind(chain, ROUTER_TRANSIT_BSC) == ROUTER
    assert never_flag.reason(chain, ROUTER_1INCH_V5) == ROUTER
    assert encode_address(ROUTER_1INCH_V5) in never_flag.build_kinds(chain)


def test_a_router_carried_across_is_refused_labels_but_is_no_swap_venue_there():
    """Only the refusal carries over. Calling a transfer into it a swap is a
    claim about the contract on that chain, which the router file does not make."""
    from app.exchange_matcher import get_router_matcher

    assert get_router_matcher("polygon").lookup(ROUTER_1INCH_V5) is None
    assert get_router_matcher("ethereum").lookup(ROUTER_TRANSIT_BSC) is None


def test_routers_are_not_carried_to_tron():
    # A Tron address is a different family; the hex form of an EVM router is not one.
    assert kind("tron", ROUTER_1INCH_V5) is None
