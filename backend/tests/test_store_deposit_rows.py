"""Deposit rows in the label store (ADR-0012): an address on an exchange's own
published list that behaves as a customer's deposit address.

What matters here:
  * a deposit_wallet row is held only with its basis (sweeps_to, sweep_tx,
    checked_on), and sweeps_to must be a wallet the label file names as the
    same exchange's own: a listing alone is not enough;
  * the store reads the basis back with the row, and a deposit row whose basis
    is missing is never read;
  * an own-wallet row reads exactly as before, and one that states a sweep is
    left out;
  * a re-run replaces a source's deposit rows with the rest of its rows.
"""
from __future__ import annotations

import csv
import sqlite3

import pytest

from app import config
from app.exchange_matcher import ExchangeMatcher
from app.label_store import DEPOSIT_TABLE, EXCHANGE_TABLE, POR_BASIS, POR_DEPOSIT_BASIS, LabelStore
from scripts.add_store_exchange_rows import COLUMNS, DEPOSIT_COLUMNS, add
from tests.test_store_exchange_rows import OKX_A, SOURCE, VICTIM, _left_out, empty_store, store_path, tron

_ = store_path  # the fixture, imported for use here

OKX_HOT_8 = "TLaGjwhvA8XQYSxFAcAXy7Dvuue9eGYitv"  # "OKX Hot Wallet 8" in the Tron label file
SWEEP_TX = "ab" * 32  # a fixture hash, no one's transaction
OKX_B = tron("05")


def _tron_labels():
    return dict(ExchangeMatcher.from_file(config.get_chain("tron").labels_path, chain="tron").entries())


def write_rows(path, rows):
    """`rows`: dicts of the columns that differ from an OKX own-wallet row."""
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[*COLUMNS, *DEPOSIT_COLUMNS])
        w.writeheader()
        for row in rows:
            w.writerow({"chain": "tron", "exchange": "OKX", "label": "OKX: Reserves Wallet (2026-11)",
                        "type": "exchange_wallet", **SOURCE, **dict.fromkeys(DEPOSIT_COLUMNS, ""), **row})


def deposit(address, **over):
    return {"address": address, "type": "deposit_wallet", "sweeps_to": OKX_HOT_8, "sweep_tx": SWEEP_TX,
            "checked_on": "2026-11-15", **over}


def test_the_label_file_names_the_sweep_destination_okx_hot_wallet():
    found = _tron_labels()[OKX_HOT_8]
    assert (found["exchange"], found["type"]) == ("OKX", "hot_wallet")


def test_a_deposit_row_is_held_with_its_basis_and_read_back(tmp_path):
    out, por = empty_store(tmp_path), tmp_path / "p.csv"
    write_rows(por, [deposit(OKX_B), {"address": OKX_A}])
    report = add(out, por)
    assert report["added"] == 2 and report["deposit_rows"] == 1 and report["left_out"] == 0
    store = LabelStore(out)
    row = store.exchange_row("tron", OKX_B)
    assert row["type"] == "deposit_wallet" and row["exchange"] == "OKX"
    assert row["basis"]["kind"] == POR_DEPOSIT_BASIS
    assert row["basis"]["source"].startswith("por:okx:2026-11: OKX's own published address list")
    assert row["basis"]["deposit"] == {"sweeps_to": OKX_HOT_8, "sweep_tx": SWEEP_TX, "checked_on": "2026-11-15"}
    # The own-wallet row beside it reads exactly as an ADR-0011 row does.
    own = store.exchange_row("tron", OKX_A)
    assert own["type"] == "exchange_wallet" and own["basis"]["kind"] == POR_BASIS and "deposit" not in own["basis"]


@pytest.mark.parametrize("missing", [
    {"sweeps_to": ""}, {"sweep_tx": ""}, {"checked_on": ""}, {"sweep_tx": "0x1234"},
    {"checked_on": "15/11/2026"}, {"sweeps_to": "0x" + "12" * 20},  # an EVM address on a Tron row
])
def test_a_deposit_row_without_a_well_formed_basis_refuses_the_csv(tmp_path, missing):
    out, por = empty_store(tmp_path), tmp_path / "p.csv"
    write_rows(por, [deposit(OKX_B, **missing), {"address": OKX_A}])
    with pytest.raises(ValueError, match="type 'deposit_wallet' without a well-formed basis .*only exchange_wallet"):
        add(out, por)
    assert LabelStore(out).has_exchange_rows is False


def test_a_sweep_into_another_exchange_or_an_unlabelled_wallet_is_not_a_basis(tmp_path):
    other = next(a for a, r in _tron_labels().items() if r["exchange"] != "OKX" and r["type"] == "hot_wallet")
    out, por = empty_store(tmp_path), tmp_path / "p.csv"
    write_rows(por, [deposit(OKX_B, sweeps_to=other), deposit(OKX_A, sweeps_to=VICTIM)])
    report = add(out, por)
    assert report["added"] == 0 and report["left_out_why"] == {"deposit basis": 2}
    assert f"deposit basis: {other} is not a wallet the label file names as OKX's own" in _left_out(por)
    assert f"deposit basis: {VICTIM} is not a wallet the label file names as OKX's own" in _left_out(por)


def test_an_own_wallet_row_that_states_a_sweep_is_left_out(tmp_path):
    out, por = empty_store(tmp_path), tmp_path / "p.csv"
    write_rows(por, [{"address": OKX_A, "sweeps_to": OKX_HOT_8}])
    assert add(out, por)["added"] == 0
    assert "an own-wallet row that states a sweep" in _left_out(por)


def test_a_deposit_row_without_its_basis_row_is_never_read(tmp_path):
    out, por = empty_store(tmp_path), tmp_path / "p.csv"
    write_rows(por, [deposit(OKX_B)])
    add(out, por)
    db = sqlite3.connect(out)
    db.execute(f"DELETE FROM {DEPOSIT_TABLE}")
    db.commit()
    db.close()
    assert LabelStore(out).exchange_row("tron", OKX_B) is None


def test_a_store_built_before_deposit_rows_reads_as_before(store_path):
    store = LabelStore(store_path)  # tests/test_store_exchange_rows.py's store, built by this script
    db = sqlite3.connect(store_path)
    db.execute(f"DROP TABLE {DEPOSIT_TABLE}")  # as a store built before ADR-0012 is
    db.commit()
    db.close()
    old = LabelStore(store_path)
    assert old.has_deposit_rows is False
    assert old.exchange_row("tron", OKX_A) == store.exchange_row("tron", OKX_A)


def test_a_re_run_replaces_a_source_deposit_rows(tmp_path):
    out, por = empty_store(tmp_path), tmp_path / "p.csv"
    write_rows(por, [deposit(OKX_B), deposit(OKX_A)])
    assert add(out, por)["deposit_rows"] == 2
    write_rows(por, [{"address": OKX_B}])  # the source's next list: OKX_B checked as its own wallet, OKX_A gone
    assert add(out, por)["deposit_rows"] == 0
    db = sqlite3.connect(out)
    held = db.execute(f"SELECT COUNT(*) FROM {DEPOSIT_TABLE}").fetchone()[0]
    rows = db.execute(f"SELECT COUNT(*) FROM {EXCHANGE_TABLE}").fetchone()[0]
    db.close()
    assert held == 0 and rows == 1
    assert LabelStore(out).exchange_row("tron", OKX_B)["type"] == "exchange_wallet"
    assert LabelStore(out).exchange_row("tron", OKX_A) is None
