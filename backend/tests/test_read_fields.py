"""Fields a case gains on read: freeze dates and which wallets the walk read.

`risk_matches[].frozen_on` and `.event_tx` say when an issuer froze a wallet
and which event did it, read from the freeze's own label and source.
`graph.nodes[].expanded` says whether the walk read a wallet's transfers.
A new trace records both; a case stored before them gets them on read
(`upgrade`, GET /trace/{id}, GET /demos/recorded/{n}), where the case can
tell, and the stored case is never changed.

Recorded data and stubs only: no network.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import models, ownership
from app.contracts import on_read, upgrade
from app.graph_builder import TraceConfig, build_trace_graph, graph_to_dict
from app.risk_matcher import RiskMatch, freeze_event
from app.main import app
from conftest import addr
from test_graph_builder import FakeClient, itx, tx

DATA = Path(__file__).resolve().parent.parent / "data"
BY_DEMO = {d["demo"]: d["result"] for d in json.loads((DATA / "recorded_demos.json").read_text())}
SEED_11 = "TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts"
TZ7L = "TZ7LmC6zBipRx6tDMavbzaF8piBpw89cNz"
FROZEN_11 = {SEED_11: "a7a163d21039fe8c378aaad209423a0825a4c66c65486f0d7a57609dd3237f2c",
             TZ7L: "98463d6ac7907828e56d49ece8ea4f34a362b8eeaa9fccaacd39f4c21a49354f"}
OWNER_KEY = "f" * 32
OWNER = {ownership.OWNER_HEADER: OWNER_KEY}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True))
    with TestClient(app) as c:
        yield c


def frozen(result):
    return {m["address"]: m for m in result["risk_matches"] if m["category"] == "frozen"}


def flags(result):
    return {n["address"]: n.get("expanded") for n in result["graph"]["nodes"]}


# -- freeze dates ------------------------------------------------------------

def test_demo_11_both_frozen_wallets_say_when_and_by_which_event():
    assert "frozen_on" not in BY_DEMO[11]["risk_matches"][0], "recorded before the field"
    got = frozen(upgrade(BY_DEMO[11]))
    assert set(got) == set(FROZEN_11)
    for address, event in FROZEN_11.items():
        assert got[address]["frozen_on"] == "2026-09-11"
        assert got[address]["event_tx"] == event


def test_a_fresh_freeze_match_carries_its_date_and_event():
    match = RiskMatch(address="0xabc", category="frozen", entity="Tether (USDT freeze)",
                      label="USDT frozen by Tether on 2021-08-05",
                      source="Tether USDT contract on Ethereum, AddedBlackList event, tx 0x" + "2b" * 32,
                      depth=1, value_received_native=5.0, token="USDT", issuer="Tether").to_dict()
    assert match["frozen_on"] == "2021-08-05" and match["event_tx"] == "0x" + "2b" * 32
    other = RiskMatch(address="0xdef", category="mixer", entity="Tornado Cash", label="Tornado Cash",
                      source="threat list", depth=2, value_received_native=1.0).to_dict()
    assert "frozen_on" not in other and "event_tx" not in other


@pytest.mark.parametrize("label,source,want", [
    ("USDC frozen by Circle", "Label store (sample tx 0x" + "ab" * 32 + ", 2024-01-02)", (None, None)),
    ("USDT frozen by Tether on 2026-02-30", "x", (None, None)),  # no such day
    ("USDT frozen by Tether on 2026-09-11", None, ("2026-09-11", None)),
    (None, "Tether USDT contract on Tron, AddedBlackList event, tx " + "9c" * 32, (None, "9c" * 32)),
])
def test_only_a_freeze_text_gives_a_date_and_only_its_event_gives_a_hash(label, source, want):
    # A store row's "sample tx" is a transfer, not the freeze: never called its event.
    assert freeze_event(label, source) == want


def test_an_old_case_gets_them_on_read_and_what_a_match_says_wins():
    old = copy.deepcopy(BY_DEMO[11])
    before = copy.deepcopy(old)
    old["risk_matches"][1]["frozen_on"] = "2026-09-10"  # recorded: kept as it is
    old["risk_matches"].append({"address": "0xmix", "category": "mixer", "label": "Tornado Cash", "source": "x"})
    v2 = upgrade(old)
    got = frozen(v2)
    assert got[SEED_11]["frozen_on"] == "2026-09-11" and got[TZ7L]["frozen_on"] == "2026-09-10"
    assert got[TZ7L]["event_tx"] == FROZEN_11[TZ7L]
    assert v2["risk_matches"][-1] == old["risk_matches"][-1], "a match that is not a freeze is unchanged"
    assert upgrade(v2) == v2
    assert BY_DEMO[11] == before, "upgrade never changes its input"


# -- expanded ------------------------------------------------------------------

def test_a_new_graph_says_which_wallets_the_walk_read():
    ledger = {addr("5eed"): [tx(addr("5eed"), addr("a1"), 10.0)],
              addr("a1"): [tx(addr("a1"), addr("b2"), 9.0)],
              addr("b2"): [tx(addr("b2"), addr("c3"), 8.0)]}
    result = build_trace_graph(addr("5eed"), FakeClient(ledger), TraceConfig(max_depth=2))
    got = {n["address"]: n["expanded"] for n in graph_to_dict(result.graph)["nodes"]}
    assert got == {addr("5eed"): True, addr("a1"): True, addr("b2"): False}


def test_demo_11_read_says_which_wallets_the_walk_read():
    nodes = upgrade(BY_DEMO[11])["graph"]["nodes"]
    for n in nodes:
        # Depth 0 and 1 were read; the walk stopped at its 2-hop limit, and
        # Binance ends a walk wherever it is met.
        assert n["expanded"] is (n["depth"] < 2), n["address"]
    assert sum(n["expanded"] for n in nodes) == BY_DEMO[11]["addresses_expanded"]


@pytest.mark.parametrize("name", sorted(BY_DEMO))
def test_every_recording_reads_as_many_wallets_as_its_walk_did(name):
    # Demo 3's WETH is a service contract: the walk read its payouts, then
    # declined to follow them, and counted it in addresses_expanded.
    read = upgrade(BY_DEMO[name])
    for result in (read, *(f["result"] for f in read.get("follow_ons") or [])):
        said = [n.get("expanded") for n in result["graph"]["nodes"]]
        assert said.count(True) == result["addresses_expanded"]


def test_the_walk_and_the_read_agree_at_a_service_contract():
    weth = addr("c02a")
    ledger = {addr("5eed"): [tx(addr("5eed"), weth, 10.0)],
              weth: [itx(weth, addr(f"a{i}"), 1.0) for i in range(1, 8)]}
    result = build_trace_graph(addr("5eed"), FakeClient(ledger), TraceConfig(max_depth=3))
    graph = graph_to_dict(result.graph)
    walk = {n["address"]: n["expanded"] for n in graph["nodes"]}
    assert walk == {addr("5eed"): True, weth: True} and result.addresses_expanded == 2
    old = {"address": addr("5eed"), "direction": "outgoing", "max_depth": 3,
           "graph": {"nodes": [{k: v for k, v in n.items() if k != "expanded"} for n in graph["nodes"]],
                     "edges": graph["edges"]}}
    assert flags(upgrade(old)) == walk
    # Only a read finds a service contract, so a walk the clock cut short read it too.
    assert flags(upgrade({**old, "stopped_by": "time"}))[weth] is True


def test_where_the_case_cannot_tell_the_field_is_left_out():
    """A walk the clock cut short may have left any wallet without an
    outflow unread: only the ones the case shows are said."""
    old = {"address": "S", "direction": "outgoing", "max_depth": 3, "stopped_by": "time",
           "truncation_reasons": ["transactions of F... could not be fetched, so the graph beyond it is missing"],
           "graph": {"nodes": [{"address": "S", "depth": 0}, {"address": "A", "depth": 1},
                               {"address": "B", "depth": 2}, {"address": "F", "depth": 1},
                               {"address": "C", "depth": 1, "history_capped": True},
                               {"address": "X", "depth": 1, "expanded": False}],
                     "edges": [{"source": "S", "target": "A"}, {"source": "A", "target": "B"},
                               {"source": "S", "target": "F"}, {"source": "S", "target": "C"},
                               {"source": "S", "target": "X"}]},
           "transfers": []}
    got = flags(upgrade(old))
    assert got == {"S": True, "A": True, "B": None, "F": False, "C": True, "X": False}
    complete = {**old, "stopped_by": None}
    assert flags(upgrade(complete))["B"] is True, "a walk nothing cut short read every wallet short of the limit"


def test_a_reverse_trace_reads_wallets_by_what_they_received():
    nodes = upgrade(BY_DEMO[5])["graph"]["nodes"]
    seed = next(n for n in nodes if n["depth"] == 0)
    assert seed["expanded"] is True
    assert all(n["expanded"] is False for n in nodes if n["depth"] >= BY_DEMO[5]["max_depth"])


# -- every read ----------------------------------------------------------------

def test_every_read_route_carries_them_and_the_stored_case_is_unchanged(client):
    models.save_case("read-11", SEED_11, copy.deepcopy(BY_DEMO[11]),
                     owner_hash=hashlib.sha256(OWNER_KEY.encode()).hexdigest())
    want = upgrade(BY_DEMO[11])
    for body in (client.get("/demos/recorded/11").json(), client.get("/trace/read-11").json(),
                 client.get("/trace/read-11", headers=OWNER).json()):
        assert frozen(body)[TZ7L]["frozen_on"] == "2026-09-11"
        assert frozen(body)[SEED_11]["event_tx"] == FROZEN_11[SEED_11]
        assert flags(body) == flags(want)
    stored = models.get_case("read-11").result
    assert "frozen_on" not in stored["risk_matches"][0] and "expanded" not in stored["graph"]["nodes"][0]


def test_a_follow_on_gets_them_too():
    got = on_read(BY_DEMO[3])["follow_ons"][0]["result"]
    assert all("expanded" in n for n in got["graph"]["nodes"])


@pytest.mark.parametrize("bad", [{"graph": {"nodes": [{"address": ["x"]}], "edges": "y"}},
                                 {"graph": "x", "risk_matches": "y"},
                                 {"risk_matches": [None, {"category": "frozen", "label": 3, "source": []}]}])
def test_a_malformed_case_still_reads(bad):
    assert on_read(bad)["victim_flow"]["status"] == "unavailable"
