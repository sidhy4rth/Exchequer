"""Bitget's own reserve wallets, labelled from its proof-of-reserves API.

scripts/import_bitget_por_labels.py (Ethereum, BNB Smart Chain) and
scripts/import_por_tron_labels.py (Tron) read Bitget's queryReserveWalletDetail
answer for each audit. An answer to a POST has no archive copy, so the answers
the rows cite are kept byte for byte in tests/fixtures/bitget_por/, and these
tests check every row against them, offline: the address is in the answer it
cites, the answer's SHA-256 is the one recorded, and nothing collides. Every
address here is read from the label files or the answers, never typed.
"""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from app import config, never_flag, pipeline
from app.etherscan_client import Transaction
from app.exchange_matcher import ExchangeMatcher, role_of
from app.pipeline import TraceRequest, run_trace
from scripts import check_label_code as clc
from scripts import import_bitget_por_labels as bitget
from scripts import import_por_labels as por
from scripts import import_por_tron_labels as tron_por

from conftest import addr

FIXTURES = Path(__file__).parent / "fixtures" / "bitget_por"
EVM = ("ethereum", "bsc")


def _answer(audit_id: str) -> bytes:
    return (FIXTURES / f"queryReserveWalletDetail_{audit_id}.json").read_bytes()


def _document(chain):
    return json.loads(config.CHAINS[chain].labels_path.read_text(encoding="utf-8"))


def _rows(chain):
    return {a: m for a, m in _document(chain)["labels"].items() if "source_audit" in m}


# -- the EVM rows ----------------------------------------------------------------------

@pytest.mark.parametrize("chain", EVM)
def test_every_row_cites_the_answer_it_was_read_from(chain):
    rows = _rows(chain)
    cited = _document(chain)["_meta"][bitget.META_KEY]["audits_cited"]
    assert rows
    for address, row in rows.items():
        assert set(row) == {"exchange", "label", "type", "source_kind", "source", "source_audit",
                            "source_sha256", "source_date", "retrieved"}
        assert row["exchange"] == "Bitget" and re.fullmatch(r"Bitget: Reserve Wallet \d+", row["label"])
        assert row["source_kind"] == bitget.KIND and row["source"] == bitget.URL
        data = _answer(row["source_audit"])
        assert hashlib.sha256(data).hexdigest() == row["source_sha256"] == cited[row["source_audit"]]["sha256"]
        snapshot, found = bitget.parse(data)
        assert address in found[chain]
        assert row["source_date"] == snapshot == cited[row["source_audit"]]["snapshot_date"]
        assert date.fromisoformat(row["source_date"]) <= date.fromisoformat(row["retrieved"]) == date(2026, 11, 15)


@pytest.mark.parametrize("chain", EVM)
def test_each_row_cites_the_newest_kept_answer_that_lists_it(chain):
    audits = {p.stem.rsplit("_", 1)[1]: bitget.parse(p.read_bytes()) for p in FIXTURES.glob("*.json")}
    for address, row in _rows(chain).items():
        listing = [snapshot for snapshot, found in audits.values() if address in found[chain]]
        assert row["source_date"] == max(listing)


@pytest.mark.parametrize("chain", EVM)
def test_the_file_says_what_was_read_and_how_many_were_added(chain):
    note = _document(chain)["_meta"][bitget.META_KEY]
    assert note["added"] == {"Bitget": len(_rows(chain))}
    assert note["source"]["url"] == bitget.URL and note["source"]["archive"] is None
    assert set(note["audits_cited"]) == {r["source_audit"] for r in _rows(chain).values()}
    for audit_id, cite in note["audits_cited"].items():
        assert note["audits_read"][audit_id] == cite["sha256"]
        assert cite["bytes"] == len(_answer(audit_id))


def test_the_rows_are_contract_wallets_without_a_role():
    # Bitget gives no hot or cold role, and none was read on chain (#248's role_basis).
    for chain in EVM:
        for row in _rows(chain).values():
            assert row["type"] == "contract_wallet" and "role" not in row and "role_basis" not in row
            assert role_of(row["type"], row.get("role")) == "contract_wallet"


def test_every_ethereum_row_holds_a_minimal_proxy():
    answers = json.loads(clc.ANSWERS.read_text(encoding="utf-8"))["code"]
    for address in _rows("ethereum"):
        kind, why = clc.classify(answers[address])
        assert kind == clc.PROXY and why.startswith("EIP-1167"), (address, why)


def test_one_label_per_address_and_each_number_once():
    seen: dict[str, str] = {}
    labels = []
    for chain in EVM:
        for address, row in _rows(chain).items():
            assert seen.setdefault(address, row["label"]) == row["label"]
            labels.append(row["label"])
    assert len(set(labels)) == len(seen)


@pytest.mark.parametrize("chain", EVM)
def test_no_row_collides_with_a_token_list_another_file_a_demo_or_another_exchange(chain):
    tokens, others, demos = never_flag.tokens(chain), por.listed(chain), por._demo_addresses()
    labels = {c: _document(c)["labels"] for c in config.CHAINS if config.CHAINS[c].address_family == "evm"}
    for address in _rows(chain):
        assert never_flag._raw(chain, address) not in tokens and address not in others and address not in demos
        for found in labels.values():
            assert found.get(address, {"exchange": "Bitget"})["exchange"] == "Bitget"


def test_the_matcher_reads_a_row_as_bitgets_own_wallet():
    for chain in EVM:
        matcher = ExchangeMatcher.from_file(config.CHAINS[chain].labels_path, chain=chain)
        for address in _rows(chain):
            found = matcher.lookup(address)
            assert found["exchange"] == "Bitget" and found["type"] == "contract_wallet"
            assert never_flag.reason(chain, address) == never_flag.EXCHANGE


# -- a trace into one ends at Bitget ---------------------------------------------------

SEED, HOP = addr("5eed"), addr("a1")
T = 1_790_000_000


def _tx(n, src, dst, value, when):
    return Transaction(hash="0x" + f"{n:064x}", from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 1e18), timestamp=when, block_number=when // 12,
                       is_error=False, asset="ETH")


@pytest.fixture
def trace(monkeypatch):
    def run(history, chain):
        class Fake:
            def get_outgoing_transactions(self, address, limit=None):
                return [t for t in history if t.from_address == address]

        @contextmanager
        def open_source(chain, asset):
            yield Fake()
        monkeypatch.setattr(pipeline, "open_source", open_source)
        monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
        return run_trace(TraceRequest(address=SEED, chain=chain, asset=config.CHAINS[chain].native_symbol,
                                      max_depth=3, follow_swaps=False))
    return run


@pytest.mark.parametrize("chain", EVM)
def test_a_transfer_into_a_bitget_reserve_wallet_is_attributed_to_bitget(trace, chain):
    wallet = sorted(_rows(chain))[0]
    result = trace([_tx(1, SEED, HOP, 4.0, T), _tx(2, HOP, wallet, 4.0, T + 60)], chain)
    assert result["exchange"] == "Bitget" and result["exchange_address"] == wallet


def test_a_transfer_that_never_reaches_one_is_not_attributed(trace):
    result = trace([_tx(1, SEED, HOP, 4.0, T), _tx(2, HOP, addr("b2"), 4.0, T + 60)], "ethereum")
    assert result["exchange"] is None


# -- the Tron rows -----------------------------------------------------------------------

def test_every_tron_row_is_in_the_answer_its_source_names():
    document = _document("tron")
    sources = document["_meta"]["proof_of_reserves"]["sources"]
    rows = {a: m for a, m in document["labels"].items() if str(m.get("source", "")).startswith("por:bitget:")}
    assert rows
    for address, row in rows.items():
        record = sources[row["source"]]
        audit_id = re.fullmatch(r'POST \{"auditId": "(Au\d{10})"\}', record["request"])[1]
        data = _answer(audit_id)
        assert hashlib.sha256(data).hexdigest() == record["sha256"]
        assert address in {a for a, _ in tron_por.parse_bitget_json(data)}
        assert record["url"] == bitget.URL and record["published"] == bitget.parse(data)[0]
        assert row["label"] == f"Bitget: Reserves Wallet ({row['source'][-7:]})"


# -- the parsers -----------------------------------------------------------------------

A, B, TOKEN = ("0x" + d * 40 for d in "abc")
TRON_PLACEHOLDER = "T" + "1" * 33  # the link's shape only, not a real address


def _entries(*entries):
    return json.dumps({"code": "200", "data": [
        {"chainName": c, "coinName": "USDT", "height": "7", "snapshotTime": "1794499200000", "walletUrl": u}
        for c, u in entries]}).encode()


def test_a_token_link_names_its_holder_not_the_token_contract():
    data = _entries(("Ethereum", f"https://etherscan.io/token/{TOKEN}?a={A.upper().replace('0X', '0x')}"),
                    ("Binance Smart Chain", f"https://bscscan.com/address/{B}"))
    snapshot, found = bitget.parse(data)
    assert snapshot == "2026-11-12"
    assert found["ethereum"] == {A: {"USDT@7"}} and set(found["bsc"]) == {B}
    assert TOKEN not in found["ethereum"]


def test_chains_exchequer_does_not_trace_are_not_read():
    data = _entries(("Optimism", f"https://optimistic.etherscan.io/address/{A}"),
                    ("BITCOIN", "https://blockchair.com/bitcoin/address/1example"),
                    ("Tron", f"https://tronscan.org/#/address/{TRON_PLACEHOLDER}"))
    _, found = bitget.parse(data)
    assert all(found[c] == {} for c in por.CHAINS)
    assert list(tron_por.parse_bitget_json(data)) == [(TRON_PLACEHOLDER, "USDT")]


def test_an_answer_with_two_snapshot_times_is_refused():
    data = json.loads(_entries(("Ethereum", f"https://etherscan.io/address/{A}"),
                               ("Ethereum", f"https://etherscan.io/address/{B}")))
    data["data"][1]["snapshotTime"] = "1792555200000"
    with pytest.raises(ValueError):
        bitget.parse(json.dumps(data).encode())


def test_each_address_takes_the_newest_audit_that_lists_it():
    audits = {"Au1": {"snapshot": "2026-02-10", "found": {"ethereum": {A: set(), B: set()}}},
              "Au2": {"snapshot": "2026-11-12", "found": {"ethereum": {A: set()}}},
              "Au0": {"snapshot": None, "found": {"ethereum": {}}}}
    assert bitget.newest(audits)["ethereum"] == {A: "Au2", B: "Au1"}
