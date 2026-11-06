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


def test_a_poisoning_row_is_on_chain_detection_unless_a_published_list_is_its_only_source():
    """A row from our own detectors whose text is not "lookalike of …" (e.g. a Tron operator
    expansion row) is still on-chain detection; only a list someone else published is tier 3."""
    ours = row(address="0x" + "b7" * 20, chain="tron", category="address poisoning",
               entity_or_incident="lookalike sent by verified poisoning operator T… (operator-level check)",
               sources="Tron operator expansion (Mukesh, operator-level verification) ; "
                       "Tron poisoning via BigQuery full-history scan (base58 4+4 lookalike)")
    published = row(address=addr("7e57"), chain="ethereum", category="address poisoning",
                    entity_or_incident="Address-poisoning phishing address (Etherscan+Forta labelled)",
                    sources="Poison-Hunter CCS24 ground truth")
    assert map_row(ours)[0][0][-1] == 4
    assert map_row(published)[0][0][-1] == 3


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


# -- what a row may claim, and how it reads (r1-labels-data-2, -13, -17) ---------
HF = "HF ethereum_fraud_dataset (fesevu, CC BY 4.0)"
DETECTOR = "Ethereum poisoning via BigQuery full-history scan (8-char lookalike)"


def old_store(tmp_path, rows, *, tier=None, texts=None):
    """A store as an earlier build wrote it: tiers set by the hunt category,
    text copied verbatim. Built with today's code, then rewritten to match."""
    src = tmp_path / "old.csv"
    with open(src, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    out = tmp_path / "old.db"
    build(src, out)
    db = sqlite3.connect(out)
    if tier is not None:
        db.execute("UPDATE labels SET tier=?", (tier,))
    for old, new in (texts or {}).items():
        db.execute("UPDATE texts SET text=? WHERE text=?", (new, old))
    db.commit()
    db.close()
    return LabelStore(out)


def test_an_ml_dataset_row_is_not_called_threat_intelligence(tmp_path):
    hf = row(address=SCAMMER, chain="ethereum", category="phishing/scam", entity_or_incident="phishing",
             sources=HF, source_refs="https://huggingface.co/datasets/fesevu/ethereum_fraud_dataset_by_activity")
    assert map_row(hf)[0][0][-1] == 5
    mixed = row(**{**hf, "sources": f"ScamSniffer scam-database @87c9e14 ; {HF}"})
    assert map_row(mixed)[0][0][-1] == 5
    research = row(**{**hf, "sources": f"Elliptic Binance hack blocklist ; {HF}", "category": "hack proceeds"})
    assert map_row(research)[0][0][-1] == 3
    # A store built before the rule (tier 3) reads the same way.
    hit = old_store(tmp_path, [hf], tier=3).lookup("ethereum", SCAMMER)
    assert "published threat intelligence" not in hit["source"]
    assert hit["source"].endswith("evidence: unvetted list (community reports or a machine-learning dataset), "
                                  "not checked")


def test_a_published_lookalike_list_is_not_on_chain_detection(tmp_path):
    slowmist = "Threat-intel report: SlowMist (via DeFiHackLabs substack): Analysis of fake Zoom"
    listed = row(address=POISONER, chain="ethereum", category="address poisoning",
                 entity_or_incident=f"lookalike of {TARGET}", sources=slowmist)
    assert map_row(listed)[0][0][-1] == 3
    fake = row(**{**listed, "entity_or_incident": "Fake token contract used to poison victims"})
    rows, _ = map_row(fake)
    assert rows[0][-1] == 3 and rows[0][3] == "Fake token contract used in address poisoning"
    ours = row(**{**listed, "sources": DETECTOR})
    assert map_row(ours)[0][0][-1] == 4
    # A dataset's "Fake token transfer" names a transfer, not the contract.
    transfer = row(**{**listed, "entity_or_incident": "Fake token transfer", "sources": HF})
    rows, _ = map_row(transfer)
    assert rows[0][3] == "Fake token transfer" and rows[0][-1] == 5
    # Read back from a store that filed it as detection.
    hit = old_store(tmp_path, [listed], tier=4).lookup("ethereum", POISONER)
    assert hit["source"].endswith("evidence: published threat intelligence")


def test_no_source_text_names_a_team_member(tmp_path):
    named = {
        "Tron operator expansion (operator-level verification) ; Tron poisoning via BigQuery full-history "
        "scan (base58 4+4 lookalike)":
            "Tron operator expansion (Mukesh, operator-level verification) ; Tron poisoning via BigQuery "
            "full-history scan (base58 4+4 lookalike)",
    }
    rows = [row(address="0x" + "b7" * 20, chain="tron", category="address poisoning",
                entity_or_incident="lookalike sent by verified poisoning operator",
                sources=list(named.values())[0]),
            row(address=SCAMMER, chain="ethereum", category="stablecoin freeze", entity_or_incident="USDC",
                sources="XSGD freeze/restriction events (on-chain replay, Mukesh)"),
            row(address=POISONER, chain="ethereum", category="address poisoning",
                entity_or_incident=f"lookalike of {TARGET}",
                sources="Tron poisoning detection by Mukesh (TronGrid, 8-char lookalike)"),
            row(address=addr("1a"), chain="tron|ethereum", category="laundering (reported)",
                entity_or_incident="HuionePay",
                sources="Laundering source (Mukesh): SlowMist KYT: On-chain analysis of HuionePay")]
    for r in rows:
        built, _ = map_row(r)
        assert "mukesh" not in built[0][8].lower()
    assert map_row(rows[0])[0][0][-1] == 4  # still our own detection
    assert map_row(rows[3])[0][0][8] == "Laundering source: SlowMist KYT: On-chain analysis of HuionePay"
    # A store built before the rule, its texts restored to the names, reads without them.
    store = old_store(tmp_path, rows[1:], texts={
        "XSGD freeze/restriction events (on-chain replay)": "XSGD freeze/restriction events (on-chain replay, Mukesh)",
        "Tron poisoning detection (TronGrid, 8-char lookalike)":
            "Tron poisoning detection by Mukesh (TronGrid, 8-char lookalike)"})
    for chain, address in (("ethereum", SCAMMER), ("ethereum", POISONER)):
        hit = store.lookup(chain, address)
        assert "mukesh" not in hit["source"].lower()
    assert store.lookup("ethereum", SCAMMER)["source"].startswith("XSGD freeze/restriction events (on-chain replay)")


def test_a_null_entity_never_reaches_a_report(tmp_path):
    null = row(address=SCAMMER, chain="ethereum", category="phishing/scam", entity_or_incident="null",
               sources="Explorer tag via dawsbot/eth-labels @d9b21ae", source_refs="label:phish-hack")
    rows, _ = map_row(null)
    assert rows[0][3] == "phishing/scam"
    for value in ("NULL", "none", "N/A", "-", "nan"):
        assert map_row(row(**{**null, "entity_or_incident": value}))[0][0][3] == "phishing/scam"
    assert map_row(row(**{**null, "sources": "null", "source_refs": "null"}))[0][0][8] == ""
    # A store that holds the literal "null" reads as the category's default.
    store = old_store(tmp_path, [null], texts={"phishing/scam": "null"})
    hit = store.lookup("ethereum", SCAMMER)
    assert hit["entity"] == "Reported scam wallet" and hit["label"] == "Reported scam wallet"
