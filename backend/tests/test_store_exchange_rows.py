"""Exchange rows in the label store (ADR-0011): an exchange's own published list.

What matters here:
  * with EXCHEQUER_STORE_EXCHANGE_ROWS on, a transfer into an address a store
    exchange row holds is attributed to that exchange, and the match says what
    it stands on (the exchange's own published list, and which);
  * the curated JSON files always win; with the flag off nothing changes;
  * never-flag rules hold: no row names a token contract, whatever the list says;
  * an address both a store exchange row and a risk list name is treated as an
    exchange wallet is today: store risk rows hidden, a freeze refused, a curated
    sanction still shown;
  * a store without the table, and a `labels` row of category "exchange", read
    as before: never a risk flag.
"""
from __future__ import annotations

import csv
import json
import sqlite3

import networkx as nx
import pytest

from app import config, exchange_matcher
from app.exchange_matcher import ExchangeMatcher
from app.label_store import EXCHANGE_TABLE, POR_BASIS, LabelStore, decode_address, encode_address
from app.risk_matcher import FROZEN, SANCTIONED, RiskMatcher
from scripts.add_store_exchange_rows import COLUMNS, add
from scripts.build_label_store import build

USDT_TRON = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"  # a token contract: never an exchange row


def tron(tag: str) -> str:
    """A valid, readable Tron address that is no one's: 0x41 + 0xab.. + tag."""
    return decode_address(b"\x41" + bytes.fromhex(("ab" * 20)[: 40 - len(tag)] + tag))


OKX_A, OKX_RISKY, VICTIM, OTHER = tron("01"), tron("02"), tron("03"), tron("04")
SOURCE = {"source_id": "por:okx:2026-11", "source_url": "https://www.okx.com/cdn/okx/por/chain/test.zip",
          "published": "2026-11-01", "retrieved": "2026-11-14", "sha256": "0" * 64}
FIELDS = ["address", "chain", "category", "entity_or_incident", "sources", "source_refs", "date",
          "exchequer_supported_chain"]


def write_por_csv(path, addresses):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for a in addresses:
            w.writerow({"address": a, "chain": "tron", "exchange": "OKX", "label": "OKX: Reserves Wallet (2026-11)",
                        "type": "exchange_wallet", **SOURCE})


@pytest.fixture
def store_path(tmp_path):
    """One poisoning row on OKX_RISKY, then OKX's list added: OKX_A, OKX_RISKY and a token contract."""
    src = tmp_path / "flagged.csv"
    with open(src, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerow({**dict.fromkeys(FIELDS, ""), "address": OKX_RISKY, "chain": "tron",
                    "category": "address poisoning", "entity_or_incident": f"lookalike of {OTHER}",
                    "sources": "Tron poisoning via BigQuery full-history scan (base58 4+4 lookalike)"})
    out = tmp_path / "label_store.db"
    assert build(src, out)["rows"] == 1
    por = tmp_path / "okx_por_tron.csv"
    write_por_csv(por, [OKX_A, OKX_RISKY, USDT_TRON, "Tnotanaddress"])
    report = add(out, por)
    assert report["added"] == 2 and report["left_out"] == 2
    return out


@pytest.fixture
def store(store_path):
    return LabelStore(store_path)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(config, "STORE_EXCHANGE_ROWS", True)


def _graph():
    g = nx.DiGraph()
    g.add_node(VICTIM, depth=0)
    g.add_node(OKX_A, depth=1)
    g.add_edge(VICTIM, OKX_A, value_native=125.0)
    return g


def test_a_transfer_into_a_store_exchange_row_is_attributed_to_okx(store, flag_on):
    matches = ExchangeMatcher({}, chain="tron", store=store).annotate(_graph())
    assert [(m.address, m.exchange, m.wallet_type) for m in matches] == [(OKX_A, "OKX", "exchange_wallet")]
    found = matches[0].to_dict()
    assert found["label"] == "OKX: Reserves Wallet (2026-11)" and found["value_received_native"] == 125.0
    assert found["attribution_basis"]["kind"] == POR_BASIS == "exchange's own published list (PoR)"
    source = found["attribution_basis"]["source"]
    assert source.startswith("por:okx:2026-11: OKX's own published address list, https://www.okx.com/")
    assert "published 2026-11-01" in source and "SHA-256 " + "0" * 64 in source


def test_with_the_flag_off_nothing_changes(store):
    assert config.STORE_EXCHANGE_ROWS is False  # off by default
    matcher = ExchangeMatcher({}, chain="tron", store=store)
    assert matcher.lookup(OKX_A) is None and matcher.annotate(_graph()) == []
    # and the store's risk row on OKX_RISKY reads as it did
    assert RiskMatcher({}, chain="tron", store=store).lookup(OKX_RISKY)["category"] == "poisoning"


def test_a_curated_json_label_wins(store, flag_on):
    files = {OKX_A: {"exchange": "Binance", "label": "Binance-Hot 1", "type": "hot_wallet"}}
    matches = ExchangeMatcher(files, chain="tron", store=store).annotate(_graph())
    assert [(m.exchange, m.label, m.basis) for m in matches] == [("Binance", "Binance-Hot 1", None)]
    assert "attribution_basis" not in matches[0].to_dict()


def test_a_label_file_match_carries_no_basis():
    matcher = ExchangeMatcher({OKX_A: {"exchange": "OKX", "label": "OKX 1", "type": "hot_wallet"}}, chain="tron")
    assert "attribution_basis" not in matcher.annotate(_graph())[0].to_dict()


def test_the_add_script_refuses_a_token_contract_and_a_bad_address(store_path):
    left = (store_path.parent / "okx_por_tron.csv.left_out.tsv").read_text()
    assert f"tron\t{USDT_TRON}\ta token contract" in left
    assert "Tnotanaddress\tnot a valid address of this chain" in left


def test_a_token_row_written_by_hand_is_still_never_an_exchange(store_path, flag_on):
    db = sqlite3.connect(store_path)
    db.execute(f"INSERT INTO {EXCHANGE_TABLE} SELECT ?, chain, exchange, label, type, basis, source "
               f"FROM {EXCHANGE_TABLE} WHERE address=?", (encode_address(USDT_TRON), encode_address(OKX_A)))
    db.commit()
    db.close()
    store = LabelStore(store_path)
    assert store.exchange_row("tron", USDT_TRON) is None
    assert store.exchange_row("tron", OKX_A)["exchange"] == "OKX"


def test_an_address_on_okx_list_and_a_risk_list_is_an_exchange_wallet_as_today(store, flag_on, monkeypatch):
    matcher = ExchangeMatcher({}, chain="tron", store=store)
    monkeypatch.setattr(exchange_matcher, "get_matcher", lambda chain_key=None: matcher)
    # A store risk row on an exchange's wallet is hidden, as on a JSON exchange row ...
    assert matcher.lookup(OKX_RISKY)["exchange"] == "OKX"
    assert RiskMatcher({}, chain="tron", store=store).lookup(OKX_RISKY) is None
    # ... an issuer's freeze on it is refused, and a curated sanction is still shown.
    freeze = {"category": FROZEN, "entity": "Tether (USDT freeze)", "label": "USDT frozen by Tether",
              "source": "USDT contract, freeze event"}
    sanction = {"category": SANCTIONED, "entity": "OFAC", "label": "OFAC SDN", "source": "OFAC SDN list"}
    risk = RiskMatcher({OKX_A: freeze, OKX_RISKY: sanction}, chain="tron", store=store)
    assert risk.lookup(OKX_A) is None
    assert risk.lookup(OKX_RISKY)["category"] == SANCTIONED
    # The same lists with the flag off: the freeze stands, no attribution.
    monkeypatch.setattr(config, "STORE_EXCHANGE_ROWS", False)
    assert risk.lookup(OKX_A)["category"] == FROZEN and matcher.lookup(OKX_A) is None


def test_a_store_without_the_table_reads_as_before(tmp_path, flag_on):
    src = tmp_path / "empty.csv"
    src.write_text(",".join(FIELDS) + "\n")
    build(src, tmp_path / "old.db")
    old = LabelStore(tmp_path / "old.db")
    assert old.has_exchange_rows is False and old.exchange_row("tron", OKX_A) is None
    assert ExchangeMatcher({}, chain="tron", store=old).lookup(OKX_A) is None


def test_a_labels_row_of_category_exchange_is_never_a_risk_flag(store_path):
    db = sqlite3.connect(store_path)
    db.execute("UPDATE labels SET category='exchange' WHERE address=?", (encode_address(OKX_RISKY),))
    db.commit()
    db.close()
    assert LabelStore(store_path).lookup("tron", OKX_RISKY) is None


def test_a_re_run_replaces_the_source_rows_and_records_the_counts(store_path, tmp_path):
    por = tmp_path / "okx_second.csv"
    write_por_csv(por, [OKX_A])
    assert add(store_path, por)["added"] == 1
    db = sqlite3.connect(store_path)
    held = db.execute(f"SELECT COUNT(*) FROM {EXCHANGE_TABLE}").fetchone()[0]
    meta = json.loads(db.execute("SELECT value FROM meta WHERE key='exchange_rows'").fetchone()[0])
    db.close()
    assert held == 1 and meta == {"tron": {"OKX": 1}}


def test_a_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "empty.csv"
    src.write_text(",".join(FIELDS) + "\n")
    build(src, tmp_path / "s.db")
    por = tmp_path / "p.csv"
    write_por_csv(por, [OKX_A])
    assert add(tmp_path / "s.db", por, dry_run=True)["added"] == 1
    assert LabelStore(tmp_path / "s.db").has_exchange_rows is False
