"""Wallets of exchanges FIU-IND acted against that had none in the label files.

data/fiu_named_exchanges.json records where every row came from (the
explorer's own public name tag on the address's page, read as
data/india_exchanges.json round 1 reads it), and the chain's exchange label
file carries the same address, so the matcher reads it like any other label.
These pin that the two agree, that every address is valid, that none collides
with another list or a demo, that a trace reaching one names the exchange, and
that each exchange has its FIU-IND entry. All offline.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import pytest

from app import config, fiu_ind_status, never_flag, pipeline
from app.etherscan_client import Transaction, normalize_address
from app.exchange_matcher import get_matcher, is_deposit_label
from app.pipeline import TraceRequest, run_trace
from app.tron_tags import exchange_for_tag
from scripts._tag_words import names_infrastructure

from conftest import addr

DOC = json.loads((Path(config.DATA_DIR) / "fiu_named_exchanges.json").read_text(encoding="utf-8"))
ROWS = DOC["rows"]
FIU = json.loads((Path(config.DATA_DIR) / fiu_ind_status.STATUS_FILE).read_text(encoding="utf-8"))["exchanges"]
KEYS = {"address", "chain", "exchange", "label", "type", "kind", "source", "source_date", "retrieved_on"}
BATCHES = {1: {"BingX", "LBank", "XT.com", "Phemex", "Bitrue"},
           2: {"MoonPay", "WOO X", "Paxful", "ProBit Global", "LCX", "CEX.IO"}}
NAMED = BATCHES[1] | BATCHES[2]
USQ_5805 = "https://sansad.in/getFile/loksabhaquestions/annex/187/AU5805_lMTYNK.pdf?source=pqals"
# Where FIU-IND's action against each is recorded, and its date (data/fiu_ind_status.json _meta.rule).
PIB = {"BingX": "2173758", "LBank": "2173758", "Phemex": "2173758", "Bitrue": "2173758", "XT.com": "2308131",
       "Paxful": "2173758", "CEX.IO": "2173758", "LCX": "2173758", "ProBit Global": "2173758", "WOO X": "2308131"}
ACTION = {**{name: (f"https://www.pib.gov.in/PressReleasePage.aspx?PRID={pib}",
                    {"2173758": "2025-10-01", "2308131": "2026-09-09"}[pib]) for name, pib in PIB.items()},
          "MoonPay": (USQ_5805, "2026-03-30")}  # Annexure-II only: no PIB release names it
SOURCE = {"ethereum": re.compile(r"https://etherscan\.io/address/(0x[0-9a-f]{40})$"),
          "polygon": re.compile(r"https://polygonscan\.com/address/(0x[0-9a-f]{40})$")}
AS_AT = re.compile(r"[A-Z][a-z]{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2} [AP]M \(UTC\)$")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}$")
OTHER_LISTS = ("risk_labels_path", "intl_sanctions_path", "frozen_labels_path", "threat_labels_path",
               "gambling_labels_path", "router_labels_path")
DEMO_FILES = ("demo_traces.json", "recorded_demos.json", "demo_expectations.json")


def _labels(path):
    if path is None or not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("labels", data) if isinstance(data, dict) else {}
    return {normalize_address(a): m for a, m in entries.items() if isinstance(a, str) and not a.startswith("_")}


# -- the file: shape, sources, validity -------------------------------------------------
def test_every_row_has_its_fields_and_its_own_explorer_page_as_source():
    assert ROWS
    for row in ROWS:
        assert set(row) == KEYS, row
        assert row["exchange"] in NAMED and row["chain"] in SOURCE, row
        page = SOURCE[row["chain"]].match(row["source"])
        assert page and page.group(1) == row["address"], row
        assert AS_AT.match(row["source_date"]) and DAY.match(row["retrieved_on"]), row


def test_the_label_is_the_explorer_tag_and_names_the_exchange():
    for row in ROWS:
        assert exchange_for_tag(row["label"]) == row["exchange"], row
        assert not names_infrastructure(row["label"]) and not is_deposit_label(row["label"]), row
        assert row["type"] in ("exchange_wallet", "contract_wallet"), row
        assert ("(contract)" in row["kind"]) == (row["type"] == "contract_wallet"), row


def test_every_address_is_valid_and_appears_once():
    for row in ROWS:
        assert config.get_chain(row["chain"]).validate_address(row["address"]), row
    counts = Counter((row["chain"], row["address"]) for row in ROWS)
    assert [key for key, n in counts.items() if n > 1] == []


def test_the_counts_in_the_meta_are_the_rows():
    counts = DOC["_meta"]["counts"]
    assert counts["rows"] == len(ROWS)
    assert counts["by_exchange"] == dict(Counter(row["exchange"] for row in ROWS))
    assert counts["by_chain"] == dict(Counter(row["chain"] for row in ROWS))
    assert set(counts["by_exchange"]) == NAMED
    assert {int(k): set(v["exchanges"]) for k, v in DOC["_meta"]["batches"].items()} == BATCHES


# -- agreement with the label files, no collisions ---------------------------------------
@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["address"][:10])
def test_the_chain_label_file_carries_the_row_exactly(row):
    held = _labels(config.get_chain(row["chain"]).labels_path).get(row["address"])
    assert held == {"exchange": row["exchange"], "label": row["label"], "type": row["type"]}


def test_no_row_is_on_another_list_in_the_india_set_or_in_a_demo_or_test():
    listed = set()
    for chain_key in SOURCE:
        for attribute in OTHER_LISTS:
            listed |= set(_labels(getattr(config.get_chain(chain_key), attribute, None)))
    india = {r["address"] for r in json.loads((Path(config.DATA_DIR) / "india_exchanges.json").read_text())["rows"]}
    demos = "".join((Path(config.DATA_DIR) / f).read_text(encoding="utf-8") for f in DEMO_FILES).lower()
    tests = "".join(p.read_text(encoding="utf-8") for p in Path(__file__).parent.glob("test_*.py")
                    if p.name != Path(__file__).name).lower()
    for row in ROWS:
        assert row["address"] not in listed and row["address"] not in india, row
        assert row["address"] not in demos and row["address"] not in tests, row


def test_the_never_flag_check_reads_every_row_as_an_exchange_wallet():
    for row in ROWS:
        assert never_flag.kind(row["chain"], row["address"], with_gambling=True) == never_flag.EXCHANGE, row


def test_what_was_left_out_is_labelled_nowhere():
    left_out = DOC["_meta"]["left_out"]
    assert left_out
    for entry in left_out:
        assert entry["why"].strip() and entry["addresses"], entry
        for address in entry["addresses"]:
            assert get_matcher(entry["chain"]).lookup(address) is None, (address, entry["why"])


def test_the_xt_com_wallet_xt_said_was_drained_in_november_2024_is_not_labelled():
    # Reported on 28 Nov 2024 as the XT.com wallet assets were drained from (left_out in the meta); who controls
    # it since is not established, as with the WazirX multisig (test_india_exchanges.py).
    for chain_key in SOURCE:
        assert get_matcher(chain_key).lookup("0xdb3ded7731c781224ec292e2163d9554c094fd7c") is None


def test_the_lcx_wallet_drained_in_the_january_2022_hack_is_not_labelled():
    # It sent the 8 Jan 2022 transfers to the address threat_labels.json labels "LCX Hacker" (left_out in the meta).
    drained = "0x4631018f63d5e31680fb53c11c9e1b11f1503e6f"
    assert any(drained in e["addresses"] and "LCX Hacker" in e["why"] for e in DOC["_meta"]["left_out"])
    for chain_key in SOURCE:
        assert get_matcher(chain_key).lookup(drained) is None


def test_a_validation_control_wallet_and_a_multisig_contract_are_not_labelled():
    corpus = (Path(config.DATA_DIR) / "validation" / "corpus.json").read_text(encoding="utf-8").lower()
    assert all(row["address"] not in corpus for row in ROWS)
    control, safe = "0x2957ea6d4f06bc2badfb2958c65fc7d1be5461b1", "0xea319fd75766f5180018f8e760f51c3d3c457496"
    assert control in corpus
    for chain_key in SOURCE:
        assert get_matcher(chain_key).lookup(control) is None and get_matcher(chain_key).lookup(safe) is None


# -- each exchange's FIU-IND entry ---------------------------------------------------------
@pytest.mark.parametrize("name", sorted(NAMED))
def test_each_exchange_has_its_fiu_ind_entry_from_the_source_that_names_it(name):
    entry = FIU[name]
    assert entry["registered"] is False and entry["penalties"] == [] and "listed_as" not in entry
    (action,) = entry["actions"]
    assert (action["url"], action["date"]) == ACTION[name]


# -- a trace that reaches one names the exchange --------------------------------------
SEED, HOP = addr("5eed"), addr("a1")
T = 1_700_000_000
_COUNTER = iter(range(1, 10**6))


def _tx(src, dst, value, when):
    return Transaction(hash="0x" + f"{next(_COUNTER):064x}", from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 1e18), timestamp=when, block_number=when // 12,
                       is_error=False, asset="ETH")


@pytest.fixture
def trace(monkeypatch):
    def run(history):
        class Fake:
            def get_outgoing_transactions(self, address, limit=None):
                return [t for t in history if t.from_address == address]

        @contextmanager
        def open_source(chain, asset):
            yield Fake()
        monkeypatch.setattr(pipeline, "open_source", open_source)
        monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
        return run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=4,
                                      follow_swaps=False))
    return run


@pytest.mark.parametrize("exchange", sorted(NAMED))
def test_a_trace_that_reaches_one_is_attributed_to_that_exchange_with_its_fiu_ind_note(trace, monkeypatch, exchange):
    row = next(r for r in ROWS if r["chain"] == "ethereum" and r["exchange"] == exchange)
    result = trace([_tx(SEED, HOP, 5.0, T + 10), _tx(HOP, row["address"], 5.0, T + 20)])
    assert result["exchange"] == exchange and result["exchange_address"] == row["address"]
    monkeypatch.setattr(config, "FIU_IND_NOTE", True)
    fiu_ind_status.clear_cache()
    note = fiu_ind_status.note(result["exchange"])
    fiu_ind_status.clear_cache()
    assert note and ACTION[exchange][0] in " ".join(note["sources"])
    assert note["text"].startswith(exchange) and "was not on FIU-IND's list of registered VDA service" in note["text"]


def test_a_trace_that_reaches_none_of_them_names_no_exchange(trace):
    result = trace([_tx(SEED, HOP, 5.0, T + 10), _tx(HOP, addr("b2"), 5.0, T + 20)])
    assert result["exchange"] is None
