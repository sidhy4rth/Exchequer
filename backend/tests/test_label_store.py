"""The on-disk label store: compact rows, cited evidence, never outranking a file.

What matters here:
  * addresses round-trip through their raw-byte form (EVM and Tron base58);
  * each hunt category maps to the right Exchequer category and evidence tier,
    and the weak or out-of-scope ones are left out;
  * a lookup returns a sentence-ready record that cites its sample tx and says
    how strong the evidence is;
  * the matcher asks the label files first, so a government label always wins;
  * a missing or stale store means screening exactly as before.
"""
from __future__ import annotations

import csv
import sqlite3

import networkx as nx
import pytest

from app import config, label_store
from app.label_store import LabelStore, decode_address, encode_address, get_label_store
from app.risk_matcher import POISONING, SANCTIONED, RiskMatch, RiskMatcher
from scripts.build_label_store import build, map_row

from conftest import addr

USDT_TRON = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
POISONER = addr("9015011")
TARGET = addr("7a6e7")
SCAMMER = addr("5ca33e")
TX = "ab" * 32
FIELDS = ["address", "chain", "category", "entity_or_incident", "sources", "source_refs", "date",
          "exchequer_supported_chain"]


def row(**kw):
    base = dict.fromkeys(FIELDS, "")
    base.update(kw)
    return base


ROWS = [
    row(address=POISONER, chain="ethereum", category="address poisoning",
        entity_or_incident=f"lookalike of {TARGET} (None USDT with {addr('71c71')})",
        sources="Ethereum poisoning via BigQuery full-history scan (8-char lookalike)",
        source_refs=f"tx 0x{TX}", date="2026-10-01"),
    row(address=SCAMMER, chain="ethereum|arbitrum", category="phishing/scam",
        entity_or_incident="Inferno Drainer receiver", sources="Threat-intel report: Check Point",
        source_refs="https://research.example/inferno"),
    row(address=addr("6a3b"), chain="ethereum", category="gambling platform", entity_or_incident="Stake.com"),
    row(address=addr("1609"), chain="ethereum", category="laundering-linked (1 hop)", entity_or_incident="x"),
    row(address=addr("ce10"), chain="celo", category="phishing/scam", entity_or_incident="x"),
]


@pytest.fixture
def store_path(tmp_path):
    src = tmp_path / "flagged.csv"
    with open(src, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(ROWS)
    out = tmp_path / "label_store.db"
    report = build(src, out)
    assert report["rows"] == 3  # poisoner + scammer on two chains
    assert report["skipped"] == {
        "left out: gambling platform": 1,
        "left out: laundering-linked (1 hop)": 1,
        "no Exchequer chain (celo)": 1,
    }
    return out


def test_addresses_round_trip_through_their_raw_bytes():
    assert decode_address(encode_address(TARGET)) == TARGET
    raw = encode_address(USDT_TRON)
    assert len(raw) == 21 and decode_address(raw) == USDT_TRON
    # a single changed character fails the base58 checksum
    assert encode_address(USDT_TRON[:-1] + "u") is None
    assert encode_address("0x1234") is None


def test_categories_map_to_exchequer_ones_and_weak_ones_are_left_out():
    rows, reason = map_row(ROWS[0])
    assert reason is None and rows[0][2] == "poisoning" and rows[0][-1] == 4
    assert decode_address(rows[0][5]) == TARGET  # the lookalike target, kept as evidence
    assert map_row(row(address=addr("1"), chain="ethereum", category="fraud platform (court record)",
                       entity_or_incident="X"))[0][0][-1] == 1
    # only a mixer's own pool may end a trace
    rows, _ = map_row(row(address=addr("2"), chain="ethereum", category="mixer",
                          entity_or_incident="creator of malicious contract $TORNADO"))
    assert rows[0][2] == "scam"
    assert map_row(row(address=addr("3"), chain="ethereum", category="mixer",
                       entity_or_incident="Tornado.Cash: 0.1 WBTC"))[0][0][2] == "mixer"
    assert map_row(ROWS[2]) == ([], "left out: gambling platform")
    # a Tron contract written in hex is stored under its base58 identity
    rows, _ = map_row(row(address="0x" + "a6" * 20, chain="tron", category="address poisoning",
                          entity_or_incident="fake token contract used to poison victims"))
    assert rows[0][0] == b"\x41" + bytes.fromhex("a6" * 20)


def test_a_lookup_cites_its_evidence_and_its_tier(store_path):
    store = LabelStore(store_path)
    hit = store.lookup("ethereum", POISONER.upper().replace("0X", "0x"))
    assert hit["category"] == "poisoning"
    assert hit["label"] == f"Lookalike of {TARGET}"
    assert f"sample tx 0x{TX}" in hit["source"] and "2026-10-01" in hit["source"]
    assert hit["source"].endswith("evidence: on-chain detection")
    scam = store.lookup("arbitrum", SCAMMER)
    assert scam["entity"] == "Inferno Drainer receiver"
    assert "https://research.example/inferno" in scam["source"]
    assert store.lookup("polygon", SCAMMER) is None
    assert store.counts("ethereum") == {"poisoning": 1, "scam": 1}
    assert len(store) == 3


def test_the_label_files_outrank_the_store(store_path):
    store = LabelStore(store_path)
    files = {SCAMMER: {"category": SANCTIONED, "entity": "OFAC SDN", "label": "OFAC SDN", "source": "OFAC"}}
    matcher = RiskMatcher(files, chain="ethereum", store=store)
    assert matcher.lookup(SCAMMER)["category"] == SANCTIONED
    assert matcher.lookup(POISONER)["category"] == POISONING
    assert matcher.is_flagged(POISONER) and not matcher.is_terminal(POISONER)
    assert matcher.counts_by_category()["poisoning"] == 1
    assert len(matcher) == 3  # one file entry + two store rows on this chain

    graph = nx.DiGraph()
    graph.add_node(POISONER, depth=1)
    graph.add_edge(addr("51c7"), POISONER, value_native=2.5)
    [match] = matcher.annotate(graph)
    assert match.category == POISONING and graph.nodes[POISONER]["risk_category"] == POISONING
    sentence = match.describe("ETH")
    assert sentence.startswith(f"Address poisoning: {POISONER}") and "not a designation" in sentence


def test_a_freeze_by_another_issuer_is_not_attributed_to_tether():
    m = RiskMatch(address=addr("f2"), category="frozen", entity="USDC", label="USDC frozen by Circle",
                  source="USDC contract freeze events", depth=1, value_received_native=1.0)
    assert m.describe().startswith("Frozen by the token's issuer:")
    t = RiskMatch(address=addr("f3"), category="frozen", entity="Tether", label="Frozen by Tether",
                  source="USDT blacklist", depth=1, value_received_native=1.0)
    assert t.describe().startswith("Frozen by Tether:")


def test_no_store_or_a_stale_one_means_screening_as_before(tmp_path, monkeypatch, store_path):
    monkeypatch.setattr(config, "LABEL_STORE_PATH", tmp_path / "missing.db")
    get_label_store.cache_clear()
    try:
        assert get_label_store() is None
        db = sqlite3.connect(store_path)
        db.execute("UPDATE meta SET value='0' WHERE key='schema_version'")
        db.commit()
        db.close()
        monkeypatch.setattr(config, "LABEL_STORE_PATH", store_path)
        get_label_store.cache_clear()
        assert get_label_store() is None
        assert label_store.SCHEMA_VERSION == 1
    finally:
        get_label_store.cache_clear()
