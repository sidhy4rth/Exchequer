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
import warnings

import pytest

from app import config, never_flag
from app.deposit_inference import infer_deposit_addresses
from app.exchange_matcher import ExchangeMatch, ExchangeMatcher, role_of
from app.scoring import _match_directness
from app.request_letters import attribution_kind
from scripts import check_label_code as clc

from conftest import addr, make_graph
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
# It checks the labels the recording holds. A label added since has no answer
# to check: it is named in a warning here, and `check_label_code --check`,
# which a label import runs (docs/label-releases.md), fails until it is read.
RECORDED = {a: m for a, m in LABELS.items() if a in ANSWERS}


def test_the_recording_covers_every_label_the_code_check_decided():
    decided = {**NOTE["retyped"], **NOTE["eip7702_delegated"], **NOTE["left_for_review"]}
    assert decided and set(decided) <= set(RECORDED)


def test_a_keyed_wallet_label_added_since_the_recording_is_named_with_what_to_run():
    missing = clc.unread(LABELS, ANSWERS)
    if missing:
        warnings.warn(clc.UNREAD_HELP.format(n=len(missing)) + " " + ", ".join(missing), stacklevel=1)
    assert clc.unread(RECORDED, ANSWERS) == {}


def test_the_import_check_fails_on_an_unread_label_and_says_what_to_run(tmp_path, monkeypatch, capsys):
    labels_file = config.CHAINS["ethereum"].labels_path
    before = labels_file.read_bytes()
    some = next(a for a, m in RECORDED.items() if m["type"] in clc.WALLET_TYPES)
    partial = tmp_path / "ethereum.json"
    partial.write_text(json.dumps({**RECORDING, "code": {a: c for a, c in ANSWERS.items() if a != some}}))
    monkeypatch.setattr(clc, "ANSWERS", partial)
    assert clc.main(["--check"]) == 1
    out = capsys.readouterr()
    assert some in out.out and "--record" in out.err and "ethereum.json" in out.err
    assert labels_file.read_bytes() == before  # --check writes nothing


def _labels_in(tmp_path, monkeypatch):
    """A copy of the Ethereum label file that the script reads and writes instead of the real one."""
    copy_of = tmp_path / config.CHAINS["ethereum"].labels_filename
    copy_of.write_bytes(config.CHAINS["ethereum"].labels_path.read_bytes())
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert config.CHAINS["ethereum"].labels_path == copy_of
    return copy_of


def test_a_run_without_flags_after_the_retype_changes_nothing(tmp_path, monkeypatch):
    # The docs say to run it without flags after every label import. The 26 it
    # retyped are contract_wallet now, so a fresh plan no longer lists them: the
    # run must keep them in the note, not replace the note with an empty list.
    labels_file = _labels_in(tmp_path, monkeypatch)
    before = labels_file.read_bytes()
    assert clc.main([]) == 0
    assert json.loads(labels_file.read_bytes())["_meta"][clc.META_KEY]["retyped"] == NOTE["retyped"]
    assert labels_file.read_bytes() == before


def test_a_run_that_retypes_one_more_keeps_the_ones_before_it(tmp_path, monkeypatch):
    labels_file = _labels_in(tmp_path, monkeypatch)
    eoa = next(a for a, m in RECORDED.items() if m["type"] == "exchange_wallet" and ANSWERS[a] == "0x")
    answers = tmp_path / "answers.json"
    proxy = "0x363d3d373d3d3d363d73" + A + "5af43d82803e903d91602b57fd5bf3"
    answers.write_text(json.dumps({**RECORDING, "code": {**ANSWERS, eoa: proxy}}))
    monkeypatch.setattr(clc, "ANSWERS", answers)
    assert clc.main([]) == 0
    after = json.loads(labels_file.read_bytes())
    assert set(after["_meta"][clc.META_KEY]["retyped"]) == set(NOTE["retyped"]) | {eoa}
    assert after["labels"][eoa]["type"] == clc.CONTRACT_WALLET and after["labels"][eoa]["role"] == "exchange_wallet"


def test_a_record_keeps_an_answer_the_node_did_not_give_this_time(tmp_path, monkeypatch):
    # A batch that fails after its retries is left out of record(); its addresses
    # must keep the answers read before, or every later run reports them unread.
    _labels_in(tmp_path, monkeypatch)
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(RECORDING))
    monkeypatch.setattr(clc, "ANSWERS", answers)
    dropped = sorted(ANSWERS)[:3]
    monkeypatch.setattr(clc, "record", lambda asked: ({a: ANSWERS[a] for a in asked if a not in dropped},
                                                      RECORDING["_meta"]["block"] + 1))
    assert clc.main(["--record", "--dry-run"]) == 0
    written = json.loads(answers.read_text())
    assert written["code"] == ANSWERS and written["_meta"]["block"] == RECORDING["_meta"]["block"] + 1


def test_no_keyed_wallet_label_holds_code_other_than_a_7702_delegation():
    bad = {}
    for address, meta in LABELS.items():
        if meta["type"] not in clc.WALLET_TYPES or address not in ANSWERS:
            continue  # unrecorded: the warning above and `check_label_code --check`
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
    decided = clc.plan(RECORDED, ANSWERS)
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


# -- #234 and its follow-up together change nothing a trace concludes ------------
MATCHER = ExchangeMatcher.from_file(config.CHAINS["ethereum"].labels_path, chain="ethereum")
BEFORE = {a: why.split(" -> ")[0] for a, why in NOTE["retyped"].items()}  # the type each row had


def test_each_retyped_row_keeps_the_type_it_had_as_its_role():
    for address, before in BEFORE.items():
        assert LABELS[address]["role"] == before
        assert role_of(MATCHER.lookup(address)["type"], MATCHER.lookup(address)["role"]) == before


def test_a_role_counts_only_on_a_contract_wallet():
    assert role_of("contract_wallet", "hot_wallet") == "hot_wallet"
    assert role_of("contract_wallet", None) == "contract_wallet"
    assert role_of("contract_wallet", "router") == "contract_wallet"
    assert role_of("deposit_wallet", "hot_wallet") == "deposit_wallet"


def _match(address, wallet_type, role=None):
    meta = MATCHER.lookup(address)
    return ExchangeMatch(address=address, exchange=meta["exchange"], label=meta["label"],
                         wallet_type=wallet_type, depth=1, value_received_native=1.0, role=role)


def test_match_directness_is_what_it_was_before_the_retype():
    raised = [a for a, before in BEFORE.items() if before in ("hot_wallet", "cold_wallet")]
    assert len(raised) == 6
    for address, before in BEFORE.items():
        graph = make_graph([(SEED, address, 1.0)], seed=SEED)
        (now,) = MATCHER.annotate(graph)
        assert now.wallet_type == clc.CONTRACT_WALLET and now.role == before
        assert _match_directness(now).raw_value == _match_directness(_match(address, before)).raw_value
    assert all(_match_directness(_match(a, clc.CONTRACT_WALLET, BEFORE[a])).raw_value == 1.0 for a in raised)


SEED, DEPOSIT, UNLABELLED = addr("5eed"), addr("de90"), addr("c0de")


def _sweeps_into(destination):
    graph = make_graph([(SEED, DEPOSIT, 10.0), (DEPOSIT, destination, 10.0)], seed=SEED)
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = {
        destination: {"count": 3, "total": 30.0, "min": 10.0, "first": 1_700_000_000, "last": 1_700_100_000}}
    return graph


def test_a_deposit_sweeping_into_a_bitget_contract_hot_wallet_is_inferred_as_before():
    for hot in (BITGET_HOT_1, "0xe2b406ec9227143a8830229eeb3eb6e24b5c60be"):
        assert MATCHER.lookup(hot)["type"] == clc.CONTRACT_WALLET
        before = ExchangeMatcher({hot: {**MATCHER.lookup(hot), "type": BEFORE[hot]}}, chain="ethereum")
        found = infer_deposit_addresses(_sweeps_into(hot), MATCHER)
        assert [m.address for m in found] == [DEPOSIT] and found[0].exchange == "Bitget"
        assert [m.to_dict() for m in found] == [m.to_dict() for m in infer_deposit_addresses(_sweeps_into(hot), before)]


def test_a_sweep_into_an_unlabelled_contract_is_not_inferred():
    assert MATCHER.lookup(UNLABELLED) is None
    assert infer_deposit_addresses(_sweeps_into(UNLABELLED), MATCHER) == []


def test_a_contract_wallet_without_a_role_or_on_a_token_is_still_not_a_sweep_destination():
    token = config.CHAINS["ethereum"].tokens[0].address.lower()
    assert never_flag.kind("ethereum", token) == never_flag.TOKEN
    for address, row in ((UNLABELLED, {"type": "contract_wallet"}),
                         (token, {"type": "contract_wallet", "role": "hot_wallet"})):
        matcher = ExchangeMatcher({address: {"exchange": "Bitget", "label": "Bitget 1", **row}}, chain="ethereum")
        assert infer_deposit_addresses(_sweeps_into(address), matcher) == []
    kept = ExchangeMatcher({UNLABELLED: {"exchange": "Bitget", "label": "Bitget 1", "type": "contract_wallet",
                                         "role": "hot_wallet"}}, chain="ethereum")
    assert [m.address for m in infer_deposit_addresses(_sweeps_into(UNLABELLED), kept)] == [DEPOSIT]  # the control


def test_no_retyped_row_is_a_token_router_or_system_address():
    assert {never_flag.kind("ethereum", a) for a in BEFORE} == {never_flag.EXCHANGE}


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
    assert document["labels"]["0x" + "a" * 40]["role"] == "hot_wallet"
    assert document["labels"]["0x" + "b" * 40]["type"] == "exchange_wallet"
    assert document["labels"]["0x" + "c" * 40]["type"] == "cold_wallet"
    assert document["labels"]["0x" + "d" * 40]["type"] == "deposit_wallet"
