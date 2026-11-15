"""OKX's two Ethereum consolidation wallets, labelled in exchange_labels.json.

OKX's 17,046 Ethereum proof-of-reserves addresses go to the label store, but
deposit inference (app/deposit_inference.py) reads its sweep destinations
from the label file. Since early 2025 OKX's per-address USDT and USDC sweeps
go to two wallets the file did not name, so a trace through an OKX deposit
address could not be read as one. Both wallets are in OKX's own PoR file; the
rows cite it as the PoR import's rows do, and each says in `role_basis` what
on-chain reading its hot_wallet role stands on. Offline: these tests read the
shipped files and the recorded eth_getCode answers only.
"""
from __future__ import annotations

import json
import re
from datetime import date

from app import config, never_flag
from app.deposit_inference import infer_deposit_addresses
from app.exchange_matcher import ExchangeMatcher, role_of
from app.scoring import _match_directness
from scripts import check_label_code as clc
from scripts import import_por_labels as por

from conftest import addr, make_graph

USDT_SWEEPS = "0x559432e18b281731c054cd703d4b49872be4ed53"  # an account; OKX's USDT sweeps land here
USDC_SWEEPS = "0x445f16314284b43dfa1fd3cd77b9dea4a1bebd97"  # an ERC-1967 proxy; OKX's USDC sweeps land here
NOTE_KEY = "okx_consolidation_2026_11_15"

DOCUMENT = json.loads(config.CHAINS["ethereum"].labels_path.read_text(encoding="utf-8"))
LABELS = DOCUMENT["labels"]
NOTE = DOCUMENT["_meta"][NOTE_KEY]
OKX_SOURCE = DOCUMENT["_meta"][por.META_KEY]["sources"]["OKX"]
ANSWERS = json.loads(clc.ANSWERS.read_text(encoding="utf-8"))["code"]
MATCHER = ExchangeMatcher.from_file(config.CHAINS["ethereum"].labels_path, chain="ethereum")


def _rows():
    return {a: m for a, m in LABELS.items() if isinstance(m, dict) and "role_basis" in m}


def test_exactly_the_two_wallets_carry_a_role_read_on_chain():
    assert set(_rows()) == {USDT_SWEEPS, USDC_SWEEPS} == set(NOTE["listed"])
    assert NOTE["added"] == {"OKX": 2}


def test_each_row_cites_okxs_por_file_as_the_import_rows_do():
    for address, row in _rows().items():
        assert row["exchange"] == "OKX"
        assert re.fullmatch(r"OKX: Reserve Wallet \d+", row["label"])
        assert row["source_kind"] == por.SOURCES["OKX"]["kind"]
        assert row["source"] == OKX_SOURCE["url"] == NOTE["source"]["url"]
        assert row["source_archive"] == OKX_SOURCE["archive"] == NOTE["source"]["archive"]
        assert row["source_date"] == OKX_SOURCE["source_date"] and row["retrieved"] == OKX_SOURCE["retrieved"]
        assert date.fromisoformat(row["source_date"]) <= date.fromisoformat(row["retrieved"])
        assert NOTE["source"]["sha256"] == OKX_SOURCE["sha256"]
        assert row["role_basis"].startswith("Role read on chain, not from the source"), address


def test_the_role_is_hot_and_the_proxy_is_typed_by_its_code():
    assert LABELS[USDT_SWEEPS]["type"] == "hot_wallet" and "role" not in LABELS[USDT_SWEEPS]
    assert LABELS[USDC_SWEEPS]["type"] == clc.CONTRACT_WALLET and LABELS[USDC_SWEEPS]["role"] == "hot_wallet"
    assert clc.classify(ANSWERS[USDT_SWEEPS])[0] == clc.EOA
    assert clc.classify(ANSWERS[USDC_SWEEPS]) == (clc.PROXY, "EIP-1967 proxy, 209 bytes")
    for address in (USDT_SWEEPS, USDC_SWEEPS):
        assert role_of(LABELS[address]["type"], LABELS[address].get("role")) == "hot_wallet"


def test_a_number_is_not_shared_with_any_other_okx_wallet_on_any_chain():
    numbers = {a: r["label"] for a, r in _rows().items()}
    for chain in config.CHAINS.values():
        if chain.address_family != "evm":
            continue
        for address, meta in json.loads(chain.labels_path.read_text(encoding="utf-8"))["labels"].items():
            if isinstance(meta, dict) and meta.get("label") in numbers.values():
                assert numbers.get(address) == meta["label"], (chain.labels_path.name, address)


def test_no_row_collides_with_a_token_list_another_file_a_demo_or_another_exchange():
    tokens, others, demos = never_flag.tokens("ethereum"), por.listed("ethereum"), por._demo_addresses()
    for address in _rows():
        assert never_flag._raw("ethereum", address) not in tokens
        assert address not in others and address not in demos
        for chain in config.CHAINS.values():
            if chain.address_family == "evm":
                meta = json.loads(chain.labels_path.read_text(encoding="utf-8"))["labels"].get(address)
                assert not meta or meta["exchange"] == "OKX", (chain.labels_path.name, meta)


def test_the_matcher_reads_both_as_okxs_own_hot_wallet():
    for address in (USDT_SWEEPS, USDC_SWEEPS):
        assert never_flag.reason("ethereum", address) == never_flag.EXCHANGE
        (match,) = MATCHER.annotate(make_graph([(SEED, address, 1.0)], seed=SEED))
        assert match.exchange == "OKX"
        assert _match_directness(match).raw_value == 1.0


SEED, DEPOSIT, UNLABELLED = addr("5eed"), addr("de90"), addr("c0de")


def _sweeps_into(destination, count=3):
    graph = make_graph([(SEED, DEPOSIT, 10.0), (DEPOSIT, destination, 10.0)], seed=SEED)
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = {
        destination: {"count": count, "total": 10.0 * count, "min": 10.0, "first": 1_700_000_000,
                      "last": 1_700_100_000}}
    return graph


def test_an_address_that_sweeps_only_into_either_wallet_is_inferred_an_okx_deposit():
    for address in (USDT_SWEEPS, USDC_SWEEPS):
        found = infer_deposit_addresses(_sweeps_into(address), MATCHER)
        assert [m.address for m in found] == [DEPOSIT] and found[0].exchange == "OKX"


def test_one_sweep_or_a_sweep_into_an_unlabelled_wallet_is_still_not_inferred():
    assert infer_deposit_addresses(_sweeps_into(USDT_SWEEPS, count=1), MATCHER) == []
    assert MATCHER.lookup(UNLABELLED) is None
    assert infer_deposit_addresses(_sweeps_into(UNLABELLED), MATCHER) == []
