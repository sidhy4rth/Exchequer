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
    assert m.describe().startswith("Frozen by Circle (USDC):")
    x = RiskMatch(address=addr("f4"), category="frozen", entity="XSGD frozen by its issuer",
                  label="XSGD frozen by its issuer", source="XSGD freeze events", depth=1, value_received_native=1.0)
    assert x.describe().startswith("Frozen by the token's issuer (XSGD):")
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


# -- only a mixer's own pool may end a trace (r2-g2-documented-claims-vs-code-7-5) --
POOL = "Tornado.Cash: 0.1 WBTC (OFAC-delisted Mar 2025)"
REGISTRY = "Tornado.Cash: Relayer Registry (OFAC-delisted Mar 2025)"
TAG = "PYUSD contract freeze events (on-chain replay) ; Explorer tag via dawsbot/eth-labels @d9b21ae"


def mixer_row(address, entity, chain="ethereum"):
    return row(address=address, chain=chain, category="mixer", entity_or_incident=entity, sources=TAG)


def test_tornado_governance_and_registry_rows_are_not_mixers(tmp_path):
    for entity in (REGISTRY, "Tornado.Cash: Trees", "Tornado.Cash: Donate", "Tornado.Cash: L1 Helper"):
        assert map_row(mixer_row(SCAMMER, entity)) == ([], "mixer contract that is not a pool")
    # A store built before the rule still holds it: it reads as nothing, so the walk goes on.
    store = old_store(tmp_path, [mixer_row(SCAMMER, POOL)], texts={POOL: REGISTRY})
    assert store.lookup("ethereum", SCAMMER) is None
    assert not RiskMatcher({}, chain="ethereum", store=store).is_terminal(SCAMMER)


def test_a_tornado_pool_in_the_store_still_ends_a_trace(tmp_path):
    rows, _ = map_row(mixer_row(SCAMMER, POOL))
    assert [r[2] for r in rows] == ["mixer"]
    store = old_store(tmp_path, [mixer_row(SCAMMER, POOL)])
    assert RiskMatcher({}, chain="ethereum", store=store).is_terminal(SCAMMER)


def test_an_ethereum_pool_filed_under_arbitrum_is_not_a_mixer_there(tmp_path):
    rows, _ = map_row(mixer_row(SCAMMER, POOL, chain="ethereum|arbitrum"))
    assert [r[1] for r in rows] == [label_store.CHAIN_IDS["ethereum"]]
    assert map_row(mixer_row(SCAMMER, POOL, chain="arbitrum")) == ([], "mixer tag read on another chain")
    # An older store filed it under both.
    store = old_store(tmp_path, [mixer_row(SCAMMER, POOL)])
    db = sqlite3.connect(store.path)
    db.execute("INSERT INTO labels SELECT address, ?, category, entity, label, peer, tx, date, source, tier "
               "FROM labels", (label_store.CHAIN_IDS["arbitrum"],))
    db.commit()
    db.close()
    store = LabelStore(store.path)
    assert store.lookup("ethereum", SCAMMER)["category"] == "mixer"
    assert store.lookup("arbitrum", SCAMMER) is None


def test_a_store_only_non_pool_does_not_stop_the_walk(tmp_path):
    from app.graph_builder import build_trace_graph
    from test_graph_builder import SEED, FakeClient, tx

    registry, beyond = SCAMMER, addr("be70d")
    store = old_store(tmp_path, [mixer_row(registry, POOL)], texts={POOL: REGISTRY})
    matcher = RiskMatcher({}, chain="ethereum", store=store)
    client = FakeClient({SEED: [tx(SEED, registry, 5.0)], registry: [tx(registry, beyond, 5.0)]})
    graph = build_trace_graph(SEED, client, is_terminal=matcher.is_terminal).graph
    assert beyond in graph


# -- r1-labels-data-1: a store row never labels infrastructure at run time ------
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"     # exchange_labels.json: hot wallet
DEPOSIT = "0x000f9f5f6db6d63bb64bb55d58272a1ce660fd90"        # exchange_labels.json: a Binance customer deposit address
ROUTER_1INCH = "0x11111112542d85b3ef69ae05771c2dccff4faa26"   # router_labels.json
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"           # config: a traced token
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"           # data/never_flag_tokens.txt
CLOUDBET = "TAJ3SYGtVjGqm61qoGzZN9bQY6MST2JQVL"               # gambling_labels_tron.json


def test_a_store_row_on_infrastructure_reads_as_nothing(tmp_path):
    binance_raw = "0x" + "77" * 20
    rows = [row(address=binance_raw, chain="ethereum", category="address poisoning",
                entity_or_incident=f"lookalike of {TARGET}", sources=DETECTOR),
            row(address=SCAMMER, chain="ethereum", category="mixer", entity_or_incident="Tornado.Cash: 0.1 WBTC",
                sources="Explorer tag via dawsbot/eth-labels @d9b21ae")]
    store = old_store(tmp_path, rows)
    # Point the two rows at real infrastructure, as an older or mistaken build might.
    db = sqlite3.connect(store.path)
    db.execute("UPDATE labels SET address=? WHERE address=?", (encode_address(BINANCE_14), encode_address(binance_raw)))
    db.execute("UPDATE labels SET address=? WHERE address=?", (encode_address(ROUTER_1INCH), encode_address(SCAMMER)))
    for address in (USDT, WETH, DEPOSIT, "0x" + "0" * 40):
        db.execute("INSERT INTO labels SELECT ?, chain, category, entity, label, peer, tx, date, source, tier "
                   "FROM labels WHERE address=?", (encode_address(address), encode_address(BINANCE_14)))
    db.execute("INSERT INTO labels SELECT ?, ?, category, entity, label, peer, tx, date, source, tier "
               "FROM labels WHERE address=?", (encode_address(CLOUDBET), label_store.CHAIN_IDS["tron"],
                                                encode_address(BINANCE_14)))
    db.commit()
    db.close()
    store = LabelStore(store.path)
    matcher = RiskMatcher({}, chain="ethereum", store=store)
    for address in (BINANCE_14, USDT, WETH, DEPOSIT, "0x" + "0" * 40, ROUTER_1INCH):
        assert matcher.lookup(address) is None, address
    assert not matcher.is_terminal(ROUTER_1INCH)  # a mixer row on a router no longer ends the trace
    # The gambling file outranks the store at run time; the store alone would still say poisoning.
    assert store.lookup("tron", CLOUDBET)["category"] == "poisoning"
    # A label file's own entry on the same address still applies.
    filed = {BINANCE_14: {"category": SANCTIONED, "entity": "x", "label": "x", "source": "OFAC"}}
    assert RiskMatcher(filed, chain="ethereum", store=store).lookup(BINANCE_14)["category"] == SANCTIONED



CIRCLE_FROZEN = addr("c17c1e")


@pytest.fixture
def freeze_store(tmp_path):
    src = tmp_path / "freezes.csv"
    with open(src, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerow(row(address=CIRCLE_FROZEN, chain="ethereum", category="stablecoin freeze",
                       entity_or_incident="USDC frozen by Circle",
                       sources="USDC contract freeze events (on-chain replay)"))
    build(src, tmp_path / "freezes.db")
    return LabelStore(tmp_path / "freezes.db")


def test_a_store_freeze_carries_its_token_and_issuer(freeze_store):
    # Audit r1-labels-data-0: the store's freezes are other issuers', and say so.
    matcher = RiskMatcher({}, chain="ethereum", store=freeze_store)
    graph = nx.DiGraph()
    graph.add_node(CIRCLE_FROZEN, depth=1)
    graph.add_edge(addr("51c7"), CIRCLE_FROZEN, value_native=1.0)
    [match] = matcher.annotate(graph)
    assert (match.category, match.token, match.issuer) == ("frozen", "USDC", "Circle")
    assert match.to_dict()["issuer"] == "Circle" and match.describe().startswith("Frozen by Circle (USDC):")


def test_a_store_row_is_marked_as_coming_from_the_store(store_path, freeze_store):
    assert RiskMatcher({}, chain="ethereum", store=freeze_store).lookup(CIRCLE_FROZEN)["origin"] == "label_store"
    assert RiskMatcher({}, chain="ethereum", store=LabelStore(store_path)).lookup(POISONER)["origin"] == "label_store"
