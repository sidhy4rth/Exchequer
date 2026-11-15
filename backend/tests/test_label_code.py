"""An Ethereum exchange label typed as a keyed wallet holds no contract code.

hot_wallet, cold_wallet and exchange_wallet say "an account the exchange holds
the key to". On 15 Nov 2026 a label audit found such labels on proxy and
forwarder contracts; scripts/check_label_code.py retyped those contract_wallet
from eth_getCode answers recorded in tests/fixtures/label_code/ethereum.json.
These tests read only that recording: no network.
"""
from __future__ import annotations

import copy
import json

import pytest

from app import config, never_flag
from app.exchange_matcher import ExchangeMatcher
from app.request_letters import attribution_kind
from scripts import check_label_code as clc

from test_letter_kinds import labelled

RECORDING = json.loads(clc.ANSWERS.read_text(encoding="utf-8"))
ANSWERS = RECORDING["code"]
DOCUMENT = json.loads(config.CHAINS["ethereum"].labels_path.read_text(encoding="utf-8"))
LABELS = DOCUMENT["labels"]
NOTE = DOCUMENT["_meta"][clc.META_KEY]

A, B = "11" * 20, "22" * 20  # placeholders inside synthetic bytecode, not real addresses
BITGET_HOT_1 = "0xe6a421f24d330967a3af2f4cdb5c34067e7e4d75"  # retyped: an EIP-1167 proxy
BITKUB_HOT_3 = "0x59e0cda5922efba00a57794faf09bf6252d64126"  # kept: an EIP-7702 delegated account


# -- the guard ---------------------------------------------------------------------
def test_every_keyed_wallet_label_has_a_recorded_answer():
    missing = sorted(a for a, m in LABELS.items() if m["type"] in clc.WALLET_TYPES and a not in ANSWERS)
    assert missing == [], "new Ethereum labels: run `python -m scripts.check_label_code --record`, then the script"


def test_no_keyed_wallet_label_holds_code_other_than_a_7702_delegation():
    bad = {}
    for address, meta in LABELS.items():
        if meta["type"] not in clc.WALLET_TYPES or address not in ANSWERS:
            continue
        kind, why = clc.classify(ANSWERS[address])
        if kind in (clc.EOA, clc.DELEGATED):
            continue
        if kind == clc.OTHER and address in NOTE["left_for_review"]:
            continue  # a contract a person must read; listed, its type unchanged
        bad[address] = f"{meta['type']}: {why} ({meta['label']})"
    assert bad == {}


def test_the_review_list_holds_only_contracts_still_typed_as_keyed_wallets():
    for address in NOTE["left_for_review"]:
        assert LABELS[address]["type"] in clc.WALLET_TYPES
        assert clc.classify(ANSWERS[address])[0] == clc.OTHER


def test_every_contract_wallet_label_holds_contract_code():
    for address, meta in LABELS.items():
        if meta["type"] == clc.CONTRACT_WALLET and address in ANSWERS:
            assert clc.classify(ANSWERS[address])[0] in (clc.PROXY, clc.FORWARDER, clc.OTHER), address


def test_the_script_has_nothing_left_to_change():
    decided = clc.plan(LABELS, ANSWERS)
    assert decided["retyped"] == {} and decided["unread"] == {}
    assert decided["delegated"] == NOTE["eip7702_delegated"]
    assert decided["review"] == NOTE["left_for_review"]


def test_the_recording_names_its_keyless_source_and_block():
    meta = RECORDING["_meta"]
    assert meta["rpc"] == clc.RPC and "key" not in meta["rpc"].lower()
    assert meta["block"] > 0 and meta["recorded"]


# -- what changed, and what did not --------------------------------------------------
def test_the_retyped_rows_were_keyed_wallets_on_proxies_or_forwarders():
    assert len(NOTE["retyped"]) == 26
    for address, why in NOTE["retyped"].items():
        assert LABELS[address]["type"] == clc.CONTRACT_WALLET
        assert why.split(" -> ")[0] in clc.WALLET_TYPES
        assert clc.classify(ANSWERS[address])[0] in (clc.PROXY, clc.FORWARDER)


def test_a_retyped_wallet_is_still_the_same_exchanges_own_wallet():
    matcher = ExchangeMatcher.from_file(config.CHAINS["ethereum"].labels_path, chain="ethereum")
    meta = matcher.lookup(BITGET_HOT_1)
    assert meta["exchange"] == "Bitget" and meta["type"] == clc.CONTRACT_WALLET
    assert never_flag.kind("ethereum", BITGET_HOT_1) == never_flag.EXCHANGE
    assert attribution_kind(labelled("contract_wallet", label=meta["label"])) == "exchange_wallet"
    assert attribution_kind(labelled("hot_wallet", label=meta["label"])) == "exchange_wallet"


def test_a_7702_delegated_account_keeps_its_type():
    assert LABELS[BITKUB_HOT_3]["type"] == "hot_wallet"
    assert BITKUB_HOT_3 in NOTE["eip7702_delegated"]


# -- the classifier: fires on each shape, silent on ordinary accounts and contracts ---
@pytest.mark.parametrize("code, kind", [
    ("0x", clc.EOA),
    ("0xef0100" + A, clc.DELEGATED),
    ("0x363d3d373d3d3d363d73" + A + "5af43d82803e903d91602b57fd5bf3", clc.PROXY),
    (clc.SAFE_PROXY + "00" * 28 + "3660008037600080366000845af4", clc.PROXY),
    ("0x7f" + clc.EIP1967_SLOT + "54" + "3660008037600080366000845af4", clc.PROXY),
    ("0x366000803760206000366000" + "73" + A + "5af4", clc.PROXY),
    ("0x600060006000600034" + "73" + B + "5af100", clc.FORWARDER),  # CALL with the value, no functions
])
def test_each_shape_is_recognised(code, kind):
    assert clc.classify(code)[0] == kind


@pytest.mark.parametrize("code", [
    "0x6000356000" + "63a9059cbb" + "14" + "600060006000600034" + "73" + B + "5af100",  # a function: not a forwarder
    "0x6080604052600080fd",  # code that neither delegates nor calls
    {"size": 5905, "keccak256": "0x" + "00" * 32, "head": "0x6060"},  # too large for a proxy
])
def test_other_contracts_are_left_for_review(code):
    assert clc.classify(code)[0] == clc.OTHER


def test_a_delegatecall_byte_inside_push_data_or_metadata_is_not_an_instruction():
    pushed = "0x73" + "f4" * 20 + "50" + "6080604052600080fd"
    trailer = "a2" + "64" + "69706673" + "58" + "22" + "1220" + "f4" * 32  # solc's CBOR metadata, 42 bytes
    assert clc.classify(pushed)[0] == clc.OTHER
    assert clc.classify("0x6080604052600080fd" + trailer + "002a")[0] == clc.OTHER
    assert clc._opcodes(bytes.fromhex(trailer)).count(clc.DELEGATECALL)  # read raw, it would look like one


def test_a_7702_prefix_on_longer_code_is_not_a_delegation():
    assert clc.classify("0xef0100" + A + "00")[0] != clc.DELEGATED


def test_the_plan_reads_only_keyed_wallets_and_reports_unread_ones():
    labels = {
        "0x" + "a" * 40: {"exchange": "X", "label": "X 1", "type": "hot_wallet"},
        "0x" + "b" * 40: {"exchange": "X", "label": "X 2", "type": "exchange_wallet"},
        "0x" + "c" * 40: {"exchange": "X", "label": "X 3", "type": "cold_wallet"},
        "0x" + "d" * 40: {"exchange": "X", "label": "X Dep", "type": "deposit_wallet"},
        "0x" + "e" * 40: {"exchange": "X", "label": "X 5", "type": "exchange_wallet"},
        "0x" + "f" * 40: {"exchange": "X", "label": "X 6", "type": "hot_wallet"},
    }
    answers = {
        "0x" + "a" * 40: "0x363d3d373d3d3d363d73" + A + "5af43d82803e903d91602b57fd5bf3",
        "0x" + "b" * 40: "0xef0100" + A,
        "0x" + "c" * 40: {"size": 3000, "keccak256": "0x" + "00" * 32, "head": "0x6060"},
        "0x" + "d" * 40: "0x363d3d373d3d3d363d73" + A + "5af43d82803e903d91602b57fd5bf3",
        "0x" + "f" * 40: "0x",
    }
    decided = clc.plan(labels, answers)
    assert list(decided["retyped"]) == ["0x" + "a" * 40]
    assert list(decided["delegated"]) == ["0x" + "b" * 40]
    assert list(decided["review"]) == ["0x" + "c" * 40]
    assert list(decided["unread"]) == ["0x" + "e" * 40]

    document = {"_meta": {}, "labels": copy.deepcopy(labels)}
    clc.apply(document, decided, "2026-11-15, block 1")
    assert document["labels"]["0x" + "a" * 40]["type"] == clc.CONTRACT_WALLET
    assert document["labels"]["0x" + "b" * 40]["type"] == "exchange_wallet"
    assert document["labels"]["0x" + "c" * 40]["type"] == "cold_wallet"
    assert document["labels"]["0x" + "d" * 40]["type"] == "deposit_wallet"
