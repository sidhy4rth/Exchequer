"""Instant exchangers: no-KYC swap services, a common cash-out point.

A payment into one pays for an order: the customer is paid out in another
asset, at an address they give. So the trail does not end there for nothing:
the service can say which order a transfer paid for, and where the payout
went. It is a place a request can be sent, like an exchange, never a sanction
hit. These pin how an address is known to be one (the seed file, the label
store), the Flow bucket it lands in, and the two letters it gets.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import networkx as nx
import pytest

from app import config, exchange_matcher, label_store, victim_flow
from app.deposit_inference import infer_deposit_addresses
from app.exchange_matcher import INSTANT_EXCHANGER, ExchangeMatcher, read_instant_exchangers
from app.freeze_requests import KINDS as LOG_KINDS
from app.label_store import LabelStore
from app.request_letters import BLANK, LETTERS, NOT_VALID, LetterNotApplicable, available, draft
from app.risk_matcher import RiskMatcher
from scripts.build_label_store import build as build_store

from test_request_letters import SEED, case

REPO = Path(config.DATA_DIR).parent.parent
SEED_FILE = Path(config.DATA_DIR) / "instant_exchangers.json"
FIXEDFLOAT_BSC = "0x4727250679294802377dd6ca6541b8e459077c95"
SWAP = "0x" + "5a9".ljust(40, "0")
HOT = "0x" + "407".ljust(40, "0")
TX1, TX2 = "0x" + "a1" * 32, "0x" + "a2" * 32


# -- the seed: only addresses this repository already holds ------------------------
def test_every_seed_row_is_an_address_the_file_it_names_already_labels_as_that_service():
    rows = json.loads(SEED_FILE.read_text(encoding="utf-8"))["rows"]
    assert rows, "the seed is empty: say so in the commit and the report"
    for row in rows:
        assert set(row) == {"address", "chain", "service", "source", "checked_on"}
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["checked_on"])
        path = re.match(r"(backend/data/\S+\.json)", row["source"])
        assert path, f"{row['address']}: the source names no file in the repository"
        source = json.loads((REPO / path[1]).read_text(encoding="utf-8"))
        assert config.get_chain(row["chain"]).labels_path == REPO / path[1]
        entry = source["labels"].get(row["address"])
        assert entry and entry["exchange"] == row["service"], row


def test_the_seed_reads_per_chain_and_a_missing_file_is_an_empty_seed(tmp_path):
    bsc = read_instant_exchangers(SEED_FILE, "bsc")
    assert bsc[FIXEDFLOAT_BSC]["service"] == "FixedFloat"
    assert FIXEDFLOAT_BSC not in read_instant_exchangers(SEED_FILE, "ethereum")  # labels never cross chains
    assert read_instant_exchangers(tmp_path / "none.json", "bsc") == {}
    (tmp_path / "bad.json").write_text('{"rows": {"x": 1}}')
    assert read_instant_exchangers(tmp_path / "bad.json", "bsc") == {}


# -- classification ---------------------------------------------------------------------
def test_a_seeded_address_is_an_exchange_whose_category_says_instant_exchanger():
    record = exchange_matcher.get_matcher("bsc").lookup(FIXEDFLOAT_BSC)
    assert record["category"] == INSTANT_EXCHANGER == "instant_exchanger"
    assert record["exchange"] == "FixedFloat" and record["type"] == "hot_wallet"  # the label file's own type stays
    assert exchange_matcher.get_matcher("bsc").is_exchange(FIXEDFLOAT_BSC)  # a cash-out point: the walk stops


def test_an_empty_seed_leaves_every_exchange_as_it_was():
    plain = ExchangeMatcher({HOT: {"exchange": "Binance", "label": "Binance 1", "type": "hot_wallet"}}, chain="bsc",
                            instant={})
    assert "category" not in plain.lookup(HOT)
    graph = nx.DiGraph()
    graph.add_edge(SEED, HOT, value_native=1.0)
    match = plain.annotate(graph)[0]
    assert "category" not in match.to_dict() and graph.nodes[HOT].get("exchange_category") is None


def annotated(matcher):
    graph = nx.DiGraph()
    graph.add_node(SEED, depth=0)
    graph.add_node(SWAP, depth=1)
    graph.add_edge(SEED, SWAP, value_native=2.0)
    return graph, matcher.annotate(graph)


def test_a_match_and_its_node_carry_the_category():
    seed = {SWAP: {"service": "ChangeNOW", "source": "backend/data/x.json", "checked_on": "2026-11-10"}}
    graph, matches = annotated(ExchangeMatcher({}, chain="ethereum", instant=seed))
    assert matches[0].to_dict()["category"] == INSTANT_EXCHANGER and matches[0].exchange == "ChangeNOW"
    assert graph.nodes[SWAP]["exchange_category"] == INSTANT_EXCHANGER and graph.nodes[SWAP]["is_terminal"]


def test_a_deposit_address_that_sweeps_into_one_is_an_inferred_instant_exchanger():
    seed = {HOT: {"service": "ChangeNOW", "source": "backend/data/x.json", "checked_on": "2026-11-10"}}
    matcher = ExchangeMatcher({HOT: {"exchange": "ChangeNOW", "label": "ChangeNOW 6", "type": "exchange_wallet"}},
                              chain="ethereum", instant=seed)
    graph = nx.DiGraph()
    graph.add_node(SEED, depth=0, is_seed=True)
    graph.add_node(SWAP, depth=1, outflows_by_counterparty={HOT: {"count": 3, "total": 3.0, "min": 1.0}})
    graph.add_edge(SEED, SWAP, value_native=3.0)
    graph.add_edge(SWAP, HOT, value_native=3.0)
    found = infer_deposit_addresses(graph, matcher)
    assert [m.to_dict()["category"] for m in found] == [INSTANT_EXCHANGER]
    assert graph.nodes[SWAP]["exchange_category"] == INSTANT_EXCHANGER


# -- the label store: the next release can add rows, and they are never risk rows ----------
FIELDS = ["address", "chain", "category", "entity_or_incident", "sources", "source_refs", "date",
          "exchequer_supported_chain"]


@pytest.fixture
def store(tmp_path):
    src = tmp_path / "flagged.csv"
    with open(src, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerow(dict.fromkeys(FIELDS, "") | {"address": SWAP, "chain": "ethereum", "category": "instant exchanger",
                                                "entity_or_incident": "SideShift",
                                                "sources": "Explorer tag via dawsbot/eth-labels"})
    out = tmp_path / "label_store.db"
    assert build_store(src, out)["rows"] == 1
    return LabelStore(out)


def test_a_store_row_makes_an_unlabelled_address_an_instant_exchanger(store):
    matcher = ExchangeMatcher({}, chain="ethereum", instant={}, store=store)
    record = matcher.lookup(SWAP)
    assert record["exchange"] == "SideShift" and record["category"] == INSTANT_EXCHANGER
    assert matcher.is_exchange(SWAP) and not matcher.is_exchange(HOT)
    assert ExchangeMatcher({}, chain="bsc", instant={}, store=store).lookup(SWAP) is None  # the chain it was read on


def test_a_store_row_for_one_is_not_a_sanction_or_risk_hit(store):
    assert store.lookup("ethereum", SWAP) is None
    assert RiskMatcher({}, chain="ethereum", store=store).lookup(SWAP) is None


def test_the_category_has_a_name_when_its_list_gives_none():
    from app.label_rules import DEFAULT_ENTITY
    assert DEFAULT_ENTITY[INSTANT_EXCHANGER] == "Instant exchanger"
    assert label_store.TIERS  # the store's tiers still word its source


# -- the Flow bucket ----------------------------------------------------------------------
def flow_case(*, inferred=False):
    nodes = [{"address": SEED, "depth": 0, "is_seed": True},
             {"address": SWAP, "depth": 1, "is_terminal": True, "exchange": None if inferred else "ChangeNOW",
              "inferred_exchange": "ChangeNOW" if inferred else None, "exchange_category": INSTANT_EXCHANGER},
             {"address": HOT, "depth": 1, "is_terminal": True, "exchange": "Binance"}]
    edges = [{"source": SEED, "target": SWAP, "value_native": 60.0, "tx_count": 1, "first_seen": 1, "last_seen": 1},
             {"source": SEED, "target": HOT, "value_native": 40.0, "tx_count": 1, "first_seen": 1, "last_seen": 1}]
    match = {"address": SWAP, "exchange": "ChangeNOW", "category": INSTANT_EXCHANGER}
    return {"address": SEED, "direction": "outgoing", "max_depth": 2, "graph": {"nodes": nodes, "edges": edges},
            "untraced": [], "transfers": [], "trace_path": [], "matches": [] if inferred else [match],
            "inferred_deposits": [{**match, "wallet_type": "inferred_deposit"}] if inferred else [],
            "materiality": {"denominator": 100.0, "basis": "seed_outflow"}}


def test_money_at_an_instant_exchanger_has_its_own_bucket_and_a_letter_to_draft():
    flow = victim_flow.build(flow_case())
    buckets = {b["kind"]: b for b in flow["buckets"]}
    assert buckets["instant_exchanger"] == {"kind": "instant_exchanger", "amount": 60.0, "share": 0.6,
                                            "addresses": [SWAP], "action": "draft_letter",
                                            "bounded_amount": 0.0}
    assert buckets["exchange"]["amount"] == 40.0 and buckets["exchange"]["addresses"] == [HOT]
    assert victim_flow.KINDS.index("instant_exchanger") == victim_flow.KINDS.index("exchange") + 1
    stop = next(s for s in flow["stops"] if s["kind"] == "instant_exchanger")
    assert stop["amount"] == 60.0 and not stop["inferred"] and "order" in stop["note"]


def test_an_inferred_one_is_drawn_dashed_and_said_as_a_guess():
    flow = victim_flow.build(flow_case(inferred=True))
    assert next(b for b in flow["buckets"] if b["kind"] == "instant_exchanger")["addresses"] == [SWAP]
    assert next(lk for lk in flow["links"] if lk["target"] == SWAP)["style"] == "dashed"
    stop = next(s for s in flow["stops"] if s["kind"] == "instant_exchanger")
    assert stop["inferred"] and "inferred and not confirmed" in stop["note"]


def test_the_flow_version_moved_on_so_stored_flows_are_rebuilt():
    assert victim_flow.VERSION == 3
    assert not victim_flow.is_current({"version": 2})


# -- the letters --------------------------------------------------------------------------
PRORATA = {"status": "estimated", "estimated": 1.75, "arrived_total": 1.75, "hops": []}


def instant_case(**over):
    """The case's exchange is ChangeNOW's wallet, an instant exchanger."""
    return case(exchange="ChangeNOW", exchange_label="ChangeNOW 6", exchange_address=SWAP, prorata=PRORATA,
                estimates={"prorata": 1.75, "conservative": 1.75},
                matches=[{"address": SWAP, "exchange": "ChangeNOW", "label": "ChangeNOW 6", "depth": 1,
                          "wallet_type": "exchange_wallet", "category": INSTANT_EXCHANGER}],
                trace_path=[{"address": SEED, "depth": 0},
                            {"address": SWAP, "depth": 1, "label": "ChangeNOW 6", "value_native": 2.5, "tx_count": 2,
                             "first_seen": 1_758_000_000, "last_seen": 1_758_003_600, "tx_hashes": [TX1, TX2]}],
                transfers=[{"hash": TX1, "from": SEED, "to": SWAP, "value_native": 1.75, "timestamp": 1_758_000_000},
                           {"hash": TX2, "from": SEED, "to": SWAP, "value_native": 0.75, "timestamp": 1_758_003_600}],
                **over)


def test_a_case_that_reached_one_is_offered_its_two_letters_in_place_of_the_exchange_ones():
    # Each names the wallet it is about, so the requests log can record it.
    assert available(instant_case()) == [
        {"to": "instant-freeze", "title": "Urgent freeze request to ChangeNOW", "address": SWAP},
        {"to": "instant", "title": "Request to ChangeNOW", "address": SWAP}]
    assert LETTERS == ("exchange-freeze", "instant-freeze", "tether-freeze", "exchange", "instant", "tether")
    assert {"instant", "instant-freeze"} <= set(LOG_KINDS)  # each can be logged as sent under its own name


def test_one_the_trace_passed_beside_the_named_exchange_gets_letters_too():
    side = {"address": SWAP, "exchange": "FixedFloat", "label": "FixedFloat: Hot Wallet", "depth": 1,
            "wallet_type": "hot_wallet", "category": INSTANT_EXCHANGER}
    result = case(matches=[side], transfers=[{"hash": TX1, "from": SEED, "to": SWAP, "value_native": 0.5,
                                              "timestamp": 1_758_000_000}])
    assert [x["to"] for x in available(result)] == ["exchange-freeze", "instant-freeze", "exchange", "instant"]
    assert {x.get("address") for x in available(result) if x["to"].startswith("instant")} == {SWAP}
    text = draft("case-1", result, "instant-freeze")
    # The case's estimate is Binance's: this letter states no figure of its own.
    assert "Amount    : [" in text and TX1 in text and "FixedFloat" in text


def test_the_information_letter_asks_for_the_order_the_payout_and_who_placed_it():
    text = draft("case-1", instant_case(), "instant")
    flat = " ".join(text.split())
    assert text.startswith("DRAFT") and NOT_VALID in text
    assert "instant exchange" in flat and SWAP in text and TX1 in text and TX2 in text
    assert "about 1.750000" in flat  # the conservative estimate, never the gross 2.5
    assert re.search(r"\d IST.*\d UTC", text)
    for asked in ("order (exchange) ID", "payout address", "asset and amount paid out",
                  "the account, e-mail address, IP addresses"):
        assert asked in flat, asked
    assert "KYC documents" not in text  # not the exchange letter's account-holder questions
    assert BLANK in text


def test_the_urgent_letter_holds_the_payout_and_carries_only_hashes_and_the_amount():
    text = draft("case-1", instant_case(), "instant-freeze")
    flat = " ".join(text.split())
    assert text.startswith("DRAFT — URGENT") and NOT_VALID in text
    assert "hold, now, any payout or refund not yet made" in flat
    for asked in ("order ID", "payout address and asset", "account, e-mail address and IP address"):
        assert asked in flat, asked
    assert "Amount    : about 1.750000 ETH" in text and TX1 in text and re.search(r"\d IST.*\d UTC", text)
    assert "3. The transfers" not in text  # no narrative: it goes first


def test_a_case_with_no_instant_exchanger_has_neither_letter():
    assert all(x["to"] not in ("instant", "instant-freeze") for x in available(case()))
    for to in ("instant", "instant-freeze"):
        with pytest.raises(LetterNotApplicable):
            draft("case-1", case(), to)
    with pytest.raises(LetterNotApplicable):
        draft("case-1", instant_case(direction="incoming"), "instant")


def test_an_inferred_order_deposit_address_is_asked_about_as_the_guess_it_is():
    guess = {"address": SWAP, "exchange": "ChangeNOW", "label": "probable ChangeNOW deposit address (inferred)",
             "wallet_type": "inferred_deposit", "category": INSTANT_EXCHANGER}
    flat = " ".join(draft("case-1", case(inferred_deposits=[guess]), "instant").split())
    assert "reason to believe is an order deposit address of ChangeNOW" in flat
    assert "which only ChangeNOW can confirm" in flat
