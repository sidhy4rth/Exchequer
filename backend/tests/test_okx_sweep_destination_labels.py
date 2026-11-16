"""OKX's Ethereum sweep destinations, labelled in exchange_labels.json for ADR-0012.

The staged OKX Ethereum deposit rows (ADR-0012) need each row's sweeps_to to be
a wallet this file names as OKX's own. 825 swept rows were left out because
they swept only into OKX proof-of-reserves wallets the file did not name (504
of them into 0x91d40e48...). These rows label those wallets: each is listed in
OKX's own PoR file (cited as the PoR import's rows cite it), the release's
on-chain classification classes it exchange_wallet, and each row's
`sweep_basis` says what was read. No hot or cold role is claimed. Offline:
these tests read the shipped files and the recorded eth_getCode answers only.
"""
from __future__ import annotations

import json
import re
from datetime import date

from app import config, never_flag
from app.deposit_inference import SWEEP_DESTINATION_TYPES, infer_deposit_addresses
from app.exchange_matcher import ExchangeMatcher, role_of
from app.scoring import _match_directness
from scripts import check_label_code as clc
from scripts import import_por_labels as por

from conftest import addr, make_graph

NOTE_KEY = "okx_sweep_destinations_2026_11_15"
MOST_SWEPT = "0x91d40e4818f4d4c57b4578d9eca6afc92ac8debe"  # an account; 504 of the dropped rows swept here
A_PROXY = "0x1b8de2a8144bd40166ba49fc404e94582d28ffcc"  # an EIP-1967 proxy holding USDC; 43 swept here
RESERVE_215 = "0x445f16314284b43dfa1fd3cd77b9dea4a1bebd97"  # OKX's USDC consolidation proxy (#248)
# test_por_labels.OKX_ETH_STORE_ROW: an OKX Ethereum row left to the label store, kept out on purpose.
LEFT_TO_THE_STORE = "0x0003b5aa5e30e97fcc596bb5d0f3a75255e08d4e"

DOCUMENT = json.loads(config.CHAINS["ethereum"].labels_path.read_text(encoding="utf-8"))
LABELS = DOCUMENT["labels"]
NOTE = DOCUMENT["_meta"][NOTE_KEY]
OKX_SOURCE = DOCUMENT["_meta"][por.META_KEY]["sources"]["OKX"]
ANSWERS = json.loads(clc.ANSWERS.read_text(encoding="utf-8"))["code"]
MATCHER = ExchangeMatcher.from_file(config.CHAINS["ethereum"].labels_path, chain="ethereum")


def _rows():
    return {a: m for a, m in LABELS.items() if isinstance(m, dict) and "sweep_basis" in m}


def test_the_rows_are_the_ones_the_note_lists_and_none_has_another_basis():
    rows = _rows()
    assert set(rows) == set(NOTE["listed"]) and len(rows) == 47
    assert NOTE["added"] == {"OKX": 47}
    assert {MOST_SWEPT, A_PROXY} <= set(rows)
    assert not [a for a, m in rows.items() if "role_basis" in m or "source_audit" in m]
    assert LEFT_TO_THE_STORE not in LABELS and LEFT_TO_THE_STORE in NOTE["left_out"]


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
        assert "classes it exchange_wallet" in row["sweep_basis"], address
        assert "(Non Staking)" in NOTE["listed"][address] and "Staking)" not in NOTE["listed"][address].replace(
            "(Non Staking)", ""), address


def test_types_follow_the_recorded_code_and_no_hot_or_cold_role_is_claimed():
    for address, row in _rows().items():
        kind, why = clc.classify(ANSWERS[address])
        if row["type"] == "exchange_wallet":
            assert kind == clc.EOA and "role" not in row, address
        else:
            assert row["type"] == clc.CONTRACT_WALLET and row["role"] == "exchange_wallet", address
            assert (kind, why) == (clc.PROXY, "EIP-1967 proxy, 209 bytes"), address
            assert ANSWERS[address] == ANSWERS[RESERVE_215], address  # the same proxy code as #248's
        assert role_of(row["type"], row.get("role")) == "exchange_wallet" in SWEEP_DESTINATION_TYPES
    assert sum(1 for r in _rows().values() if r["type"] == clc.CONTRACT_WALLET) == 7


def test_a_number_is_not_shared_with_any_other_okx_wallet_on_any_chain():
    numbers = {a: r["label"] for a, r in _rows().items()}
    assert len(set(numbers.values())) == len(numbers)
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


def test_the_matcher_reads_each_as_okxs_own_wallet_with_its_role_not_recorded():
    for address in _rows():
        assert never_flag.reason("ethereum", address) == never_flag.EXCHANGE
        (match,) = MATCHER.annotate(make_graph([(SEED, address, 1.0)], seed=SEED))
        assert match.exchange == "OKX"
        assert _match_directness(match).raw_value == 0.8  # not a hot or cold wallet's 1.0


SEED, DEPOSIT, UNLABELLED = addr("5eed"), addr("de90"), addr("c0de")


def _sweeps_into(destination, count=3):
    graph = make_graph([(SEED, DEPOSIT, 10.0), (DEPOSIT, destination, 10.0)], seed=SEED)
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = {
        destination: {"count": count, "total": 10.0 * count, "min": 10.0, "first": 1_700_000_000,
                      "last": 1_700_100_000}}
    return graph


def test_an_address_that_sweeps_only_into_one_of_them_is_inferred_an_okx_deposit():
    for address in (MOST_SWEPT, A_PROXY):
        found = infer_deposit_addresses(_sweeps_into(address), MATCHER)
        assert [m.address for m in found] == [DEPOSIT] and found[0].exchange == "OKX"


def test_one_sweep_or_a_sweep_into_an_unlabelled_wallet_is_still_not_inferred():
    assert infer_deposit_addresses(_sweeps_into(MOST_SWEPT, count=1), MATCHER) == []
    assert MATCHER.lookup(UNLABELLED) is None
    assert infer_deposit_addresses(_sweeps_into(UNLABELLED), MATCHER) == []


# -- 16 Nov 2026 revision (#328): rows the internal-wallet filter dropped no longer count --------
REVISED = NOTE["revised_2026_11_16"]
RESERVE_237 = "0x5ca38fb7cf2b587026a1650f0d2b0a13c41f5d0f"
RESERVE_258 = "0xdce83237fbf279c4522e7cac4b10428e2b8694da"
TX_HASH = re.compile(r"0x[0-9a-f]{64}")


def _counted(row):
    return int(re.search(r"and (\d+) OKX PoR addresses that file classes deposit_wallet", row["sweep_basis"]).group(1))


def test_each_revised_row_states_what_the_filter_dropped_and_what_is_left():
    counts = REVISED["wallets_counted_dropped_left"]
    assert len(counts) == 29 and set(counts) <= set(_rows())
    assert REVISED["rows_counted"] == 821 and REVISED["rows_dropped_by_filter"] == 79
    assert REVISED["counted_rows_file_sha256"] == NOTE["classification"]["dropped_rows_sha256"]
    for address, text in counts.items():
        counted, dropped, left = map(int, re.fullmatch(
            r"(\d+) counted, (\d+) dropped by the filter, (\d+) left", text).groups())
        row = _rows()[address]
        assert counted == _counted(row) and dropped >= 1 and left == counted - dropped, address
        assert "(#328)" in row["sweep_basis"] and f"dropped {dropped} of those {counted}, so " in row["sweep_basis"]
        if left:
            assert f"so {left} of them are left as deposit sweeps" in row["sweep_basis"], address
        else:
            assert "so no deposit sweep is left behind this label" in row["sweep_basis"], address
    none_left = [a for a, t in counts.items() if t.endswith(" 0 left")]
    assert sorted(none_left) == sorted(REVISED["no_customer_deposit_sweep_left"]) and len(none_left) == 13
    assert {RESERVE_237, RESERVE_258} <= set(none_left)
    assert "#328" in NOTE["rule"] and "13 of the 47" in NOTE["rule"]


def test_a_row_the_filter_did_not_touch_is_not_revised():
    unrevised = set(_rows()) - set(REVISED["wallets_counted_dropped_left"])
    assert len(unrevised) == 18 and A_PROXY in unrevised
    for address in unrevised:
        assert "#328" not in _rows()[address]["sweep_basis"] and "revised" not in _rows()[address]["sweep_basis"]


def test_237_and_258_cite_the_hand_checked_funding_tests_and_keep_their_label():
    tests = REVISED["hand_check"]["funding_tests"]
    assert set(tests) == {RESERVE_237, RESERVE_258}
    seen = set()
    for wallet, test in tests.items():
        row = LABELS[wallet]
        assert row["exchange"] == "OKX" and row["type"] == "exchange_wallet" and row["source"] == NOTE["source"]["url"]
        assert _counted(row) == len(test["rows"]) == 10
        assert test["funded_by"] in row["sweep_basis"] and "block 25126685" in row["sweep_basis"]
        three = 0
        for deposit, hashes in test["rows"].items():
            hashes = hashes.split(",")
            assert re.fullmatch(r"0x[0-9a-f]{40}", deposit) and deposit not in LABELS and deposit not in seen
            assert len(hashes) in (2, 3) and all(TX_HASH.fullmatch(h) for h in hashes), deposit
            three += len(hashes) == 3
            seen.add(deposit)
        assert three == 5  # 5 of each 10 also got 10 USDT and returned 5 USDT
        funding, back = re.search(r"e\.g\. funding (0x[0-9a-f]{64}), return (0x[0-9a-f]{64})", row["sweep_basis"]).groups()
        assert [funding, back] in [h.split(",") for h in test["rows"].values()]
    relay = REVISED["hand_check"]["not_counted"].split(",")[0]
    assert relay not in LABELS and relay not in seen and relay not in REVISED["wallets_counted_dropped_left"]
