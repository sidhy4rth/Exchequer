"""OKX's own Tron wallets, labelled in exchange_labels_tron.json for ADR-0012.

A staged OKX Tron deposit row needs its sweeps_to to be a wallet this file names
as OKX's own, and until these rows the file named one (Hot Wallet 8). These
rows label more of OKX's proof-of-reserves Tron addresses: each is in OKX's own
PoR file, and scripts/classify_okx_tron_wallets.py classes it own_wallet from
keyless TronGrid reads kept in tests/fixtures/okx_tron_own_wallets.json (it pays
real USDT to many addresses outside OKX and moves value both ways with OKX
wallets). No hot or cold role is claimed. Offline: these tests read the shipped
files and the recorded reads only. Addresses are read from those files, never typed.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app import config, never_flag
from app.deposit_inference import SWEEP_DESTINATION_TYPES, infer_deposit_addresses
from app.exchange_matcher import ExchangeMatcher, curated_sources, role_of
from app.label_store import encode_address
from app.scoring import _match_directness
from app.tron_tags import exchange_for_tag
from scripts import add_store_exchange_rows as store_rows
from scripts import classify_okx_tron_wallets as clf
from scripts import import_por_labels as eth_por
from scripts import import_por_tron_labels as por
from scripts.seed_tron_labels import keep_previous

from conftest import make_graph

NOTE_KEY = "okx_own_wallets_2026_11_15"
TRON = config.CHAINS["tron"]
DOCUMENT = json.loads(TRON.labels_path.read_text(encoding="utf-8"))
LABELS = DOCUMENT["labels"]
NOTE = DOCUMENT["_meta"][NOTE_KEY]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "okx_tron_own_wallets.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
READS = FIXTURE["addresses"]
MATCHER = ExchangeMatcher.from_file(TRON.labels_path, chain="tron")
# Two unlabelled wallets the other Tron tests already use (test_tron_tags.py).
SEED = "TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts"
HOP = "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU"


def _rows():
    return {a: m for a, m in LABELS.items() if "sweep_basis" in m}


def _busiest():
    """The labelled wallet that paid the most addresses outside OKX in what was read."""
    return max(_rows(), key=lambda a: READS[a]["usdt_out"]["distinct_non_okx"])


# -- the rows ----------------------------------------------------------------------

def test_the_rows_are_the_ones_the_note_lists():
    rows = _rows()
    assert set(rows) == set(NOTE["listed"]) and len(rows) == 10
    assert NOTE["added"] == {"OKX": 10}
    assert {a: m["label"] for a, m in rows.items()} == NOTE["listed"]
    assert not set(rows) & set(NOTE["left_out"])


def test_each_row_cites_okxs_por_file_as_the_import_names_it():
    source = por.SOURCES["por:okx:2026-11"]
    eth = json.loads(config.CHAINS["ethereum"].labels_path.read_text(encoding="utf-8"))
    eth_okx = eth["_meta"][eth_por.META_KEY]["sources"]["OKX"]
    assert NOTE["source"]["url"] == source.url and NOTE["source"]["source_date"] == source.published
    assert NOTE["source"]["sha256"] == eth_okx["sha256"]  # the same file the Ethereum rows cite
    for address, row in _rows().items():
        assert row["exchange"] == "OKX" and row["type"] == "exchange_wallet" and "role" not in row, address
        assert re.fullmatch(r"OKX: Reserve Wallet \d+", row["label"]) and exchange_for_tag(row["label"]) == "OKX"
        assert row["source"] == source.url and row["source_kind"] == source.kind
        assert row["source_archive"] == NOTE["source"]["archive"] == eth_okx["archive"]
        assert row["source_date"] == source.published and row["retrieved"] == NOTE["source"]["retrieved"]
        assert not row["source"].startswith("por:")  # not one of the import's rows (test_tron_por_labels)


def test_a_number_is_not_shared_with_any_other_okx_wallet_on_any_chain():
    numbers = {a: r["label"] for a, r in _rows().items()}
    assert len(set(numbers.values())) == len(numbers)
    for chain in config.CHAINS.values():
        if chain.labels_path is None or not chain.labels_path.exists():
            continue
        for address, meta in json.loads(chain.labels_path.read_text(encoding="utf-8"))["labels"].items():
            if isinstance(meta, dict) and meta.get("label") in numbers.values():
                assert numbers.get(address) == meta["label"], (chain.labels_path.name, address)


def test_the_counts_still_match_the_rows():
    counts = DOCUMENT["_meta"]["counts"]
    assert counts["labels"] == len(LABELS) and counts["by_exchange"]["OKX"] == 11


# -- the recorded classification ------------------------------------------------------

def test_the_note_names_the_recorded_reads_by_their_hash():
    assert NOTE["classification"]["evidence_sha256"] == hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    assert NOTE["classification"]["rules"] == FIXTURE["rules"] == clf.RULES


def test_the_rules_give_each_recorded_address_the_class_it_was_given():
    for address, reads in READS.items():
        assert clf.classify(reads) == (reads["class"], reads["why"]), address


def test_every_row_is_classed_own_wallet_and_its_basis_quotes_why():
    for address, row in _rows().items():
        reads = READS[address]
        assert reads["class"] == clf.OWN and reads["in_por"] and not reads["is_contract"], address
        assert reads["why"] in row["sweep_basis"] and "tests/fixtures/okx_tron_own_wallets.json" in row["sweep_basis"]


def test_everything_else_read_is_left_out_with_its_reason():
    assert set(READS) == set(_rows()) | set(NOTE["left_out"])
    for address, why in NOTE["left_out"].items():
        assert address not in LABELS, address
        reads = READS[address]
        if reads["class"] == clf.OWN:  # passes, but a recorded demo uses it: re-record that first
            assert address in FIXTURE["_meta"]["demo_addresses"] and "recorded demo" in why
        else:
            assert why.startswith(f"classed {reads['class']}"), address
    assert {READS[a]["class"] for a in FIXTURE["_meta"]["controls"]} == {clf.DEPOSIT_LIKE}


# -- the rules on their own -------------------------------------------------------------

def _side(n=0, non_okx=0, okx=0):
    return {"n": n, "distinct_non_okx": non_okx, "distinct_okx": okx, "span_days": 1.0}


def _reads(usdt_out=None, trx_out=None, usdt_in=None, trx_in=None, contract=False):
    return {"is_contract": contract, "usdt_out": usdt_out or _side(), "trx_out": trx_out or _side(),
            "usdt_in": usdt_in or _side(), "trx_in": trx_in or _side()}


def test_a_wallet_that_pays_many_and_trades_with_okx_both_ways_is_okxs_own():
    assert clf.classify(_reads(usdt_out=_side(400, 50, 1), usdt_in=_side(400, 0, 1)))[0] == clf.OWN
    assert clf.classify(_reads(trx_out=_side(200, 190, 1), trx_in=_side(200, 0, 3)))[0] == clf.OWN


def test_a_sweeping_deposit_address_and_ordinary_wallets_are_not():
    assert clf.classify(_reads(usdt_out=_side(400, 0, 1), usdt_in=_side(400, 26, 0)))[0] == clf.DEPOSIT_LIKE
    assert clf.classify(_reads(usdt_out=_side(400, 49, 1), usdt_in=_side(400, 0, 1)))[0] == clf.UNCLASSIFIED
    assert clf.classify(_reads(usdt_out=_side(400, 300, 0), usdt_in=_side(400, 0, 5)))[0] == clf.UNCLASSIFIED
    assert clf.classify(_reads(usdt_out=_side(400, 300, 1), usdt_in=_side(400, 300, 0)))[0] == clf.UNCLASSIFIED
    assert clf.classify(_reads(usdt_out=_side(400, 300, 1), usdt_in=_side(400, 0, 1), contract=True))[0] \
        == clf.UNCLASSIFIED
    assert clf.classify(_reads(usdt_in=_side(400, 300, 3)))[0] == clf.UNCLASSIFIED


def test_a_fake_token_or_a_zero_transfer_does_not_count_as_a_payment():
    def event(token, value, to):
        return {"token_info": {"address": token}, "type": "Transfer", "value": str(value),
                "from": SEED, "to": to, "block_timestamp": 1_700_000_000_000}
    rows = [event(clf.USDT, 5_000_000, HOP), event(HOP, 5_000_000, HOP), event(clf.USDT, 0, HOP)]
    kept = clf.usdt_transfers(rows, SEED, "out")
    assert kept == [{"from": SEED, "to": HOP, "v": 5_000_000, "ts": 1_700_000_000_000}]
    assert clf.usdt_transfers(rows, HOP, "out") == []  # not sent by HOP
    summary = clf.summarise(kept, "to", okx={HOP})
    assert summary["distinct_okx"] == 1 and summary["distinct_non_okx"] == 0 and summary["value_to_okx"] == 5.0


def test_a_trx_transfer_is_read_from_its_hex_parties_and_a_failed_one_is_not():
    def tx(result):
        value = {"owner_address": encode_address(SEED).hex(), "to_address": encode_address(HOP).hex(), "amount": 7}
        return {"raw_data": {"contract": [{"type": "TransferContract", "parameter": {"value": value}}]},
                "ret": [{"contractRet": result}], "block_timestamp": 1}
    assert clf.trx_transfers([tx("SUCCESS"), tx("REVERT")], SEED, "out") == [
        {"from": SEED, "to": HOP, "v": 7, "ts": 1}]
    assert clf.trx_transfers([tx("SUCCESS")], SEED, "in") == []


# -- no collision ------------------------------------------------------------------------

def test_no_row_hides_a_freeze_a_sanction_a_demo_or_a_test_wallet():
    this_file = Path(__file__).name
    elsewhere = {a: why for a, why in por.listed_elsewhere().items() if this_file not in why}
    assert {a: elsewhere[a] for a in _rows() if a in elsewhere} == {}
    assert {a: k for a in _rows() if (k := never_flag.kind("tron", a)) != never_flag.EXCHANGE} == {}


def test_no_row_is_named_by_another_exchange_in_any_label_file():
    for chain in config.CHAINS.values():
        if chain.labels_path is None or not chain.labels_path.exists() or chain.labels_path == TRON.labels_path:
            continue
        labels = json.loads(chain.labels_path.read_text(encoding="utf-8"))["labels"]
        assert not set(_rows()) & set(labels), chain.labels_path.name


# -- what a trace and the store builder make of them --------------------------------------

def test_the_matcher_reads_each_as_okxs_own_wallet_with_its_role_not_recorded():
    for address in _rows():
        meta = MATCHER.lookup(address)
        assert meta["exchange"] == "OKX"
        assert role_of(meta["type"], meta.get("role")) == "exchange_wallet" in SWEEP_DESTINATION_TYPES
        (match,) = MATCHER.annotate(make_graph([(SEED, address, 1.0)], seed=SEED))
        assert match.exchange == "OKX" and _match_directness(match).raw_value == 0.8  # not a hot wallet's 1.0


def test_the_store_builder_now_accepts_each_as_a_deposit_rows_sweeps_to():
    files, _ = curated_sources("tron")
    for address in _rows():
        assert store_rows.own_wallet(files, address, "OKX")
        assert not store_rows.own_wallet(files, address, "Binance")
    assert not store_rows.own_wallet(files, SEED, "OKX")


def _sweeps_into(destination, count=3):
    graph = make_graph([(SEED, HOP, 10.0), (HOP, destination, 10.0)], seed=SEED)
    graph.nodes[HOP]["outflows_by_counterparty"] = {
        destination: {"count": count, "total": 10.0 * count, "min": 10.0, "first": 1_700_000_000,
                      "last": 1_700_100_000}}
    return graph


def test_an_address_that_sweeps_into_one_of_them_is_inferred_an_okx_deposit():
    found = infer_deposit_addresses(_sweeps_into(_busiest()), MATCHER, native_symbol="TRX", asset="USDT")
    assert [m.address for m in found] == [HOP] and found[0].exchange == "OKX"


def test_one_sweep_or_a_sweep_into_an_unlabelled_wallet_is_still_not_inferred():
    assert infer_deposit_addresses(_sweeps_into(_busiest(), count=1), MATCHER, native_symbol="TRX", asset="USDT") == []
    left_out = sorted(NOTE["left_out"])[0]
    assert MATCHER.lookup(left_out) is None
    assert infer_deposit_addresses(_sweeps_into(left_out), MATCHER, native_symbol="TRX", asset="USDT") == []


def test_the_tronscan_seeder_never_replaces_or_drops_one_of_these_rows():
    address = _busiest()
    kept = {address: {"exchange": "OKX", "label": "OKX 3", "type": "hot_wallet"}}
    keep_previous(kept, {address: LABELS[address]}, dropped={address})
    assert kept[address] == LABELS[address]
    kept = {}
    keep_previous(kept, {address: LABELS[address]}, dropped={address})
    assert kept[address] == LABELS[address]
