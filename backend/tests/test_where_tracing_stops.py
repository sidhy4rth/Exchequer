"""Where tracing stops, said plainly on every victim flow (app/victim_flow.py).

Silence reads as "nothing happened". Each estimated flow lists `stops`:
where the trace stopped following the victim's share and why, from the
case's own limits (`max_depth`, the fan-out limit's `untraced` and reasons)
and the kind of wallet it ended at, each with the share that stopped there
and one plain sentence.

Recorded data and small built graphs only: no network.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import models, victim_flow
from app.contracts import upgrade
from app.main import app
from app.victim_flow import build
from test_victim_flow import case

DATA = Path(__file__).resolve().parent.parent / "data"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contract"
BY_DEMO = {d["demo"]: d["result"] for d in json.loads((DATA / "recorded_demos.json").read_text())}
TZ7L = "TZ7LmC6zBipRx6tDMavbzaF8piBpw89cNz"


def stops(flow):
    return {s["kind"]: s for s in flow["stops"]}


def bucket(flow, kind):
    return next(b for b in flow["buckets"] if b["kind"] == kind)


def test_demo_11_stops_at_two_hops_at_the_fan_out_limit_and_at_binance():
    flow = build(BY_DEMO[11])
    got = stops(flow)
    assert [s["kind"] for s in flow["stops"]] == ["hop_limit", "fanout_limit", "exchange"]
    hops = got["hop_limit"]
    assert hops["note"] == "The trace stopped at 2 hops."
    assert round(hops["amount"], 2) == 8732.34
    assert hops["addresses"] == bucket(flow, "beyond_limit")["addresses"]
    fan = got["fanout_limit"]
    assert fan["addresses"] == [TZ7L] and round(fan["amount"], 2) == 196.78
    assert fan["note"] == "Only the 10 largest destinations were followed at TZ7LmC…9cNz."
    end = got["exchange"]
    assert round(end["amount"], 2) == 959.58 and end["addresses"] == bucket(flow, "exchange")["addresses"]
    assert end["note"].startswith("Reached an exchange: tracing ends here")
    assert "mixer" not in got and "no_outflow" not in got


@pytest.mark.parametrize("category,note", [("mixer", "Reached a mixer: tracing ends here."),
                                           ("bridge", "Reached a bridge to another chain: tracing ends here."),
                                           ("privacy", "Reached a privacy service: tracing ends here.")])
def test_money_that_reaches_a_mixer_stops_there(category, note):
    result = case([("S", "A", [(1, 100)]), ("A", "M", [(2, 60)]), ("A", "E", [(3, 40)])], exchange="E")
    next(n for n in result["graph"]["nodes"] if n["address"] == "M")["risk_category"] = category
    flow = build(result)
    assert stops(flow)[category] == {"kind": category, "addresses": ["M"], "amount": 60, "note": note,
                                     "inferred": False}
    assert bucket(flow, "risk")["amount"] == 60 and stops(flow)["exchange"]["amount"] == 40


def test_a_probable_deposit_address_stops_as_a_guess_not_as_an_exchange():
    result = case([("S", "A", [(1, 100)]), ("A", "E", [(2, 60)]), ("A", "D", [(3, 40)])], exchange="E")
    next(n for n in result["graph"]["nodes"] if n["address"] == "D")["inferred_exchange"] = "Binance"
    ends = [s for s in build(result)["stops"] if s["kind"] == "exchange"]
    assert ends == [
        {"kind": "exchange", "addresses": ["E"], "amount": 60, "inferred": False,
         "note": "Reached an exchange: tracing ends here, and a letter to the exchange is the next step."},
        {"kind": "exchange", "addresses": ["D"], "amount": 40, "inferred": True,
         "note": "Reached a probable exchange deposit address, inferred and not confirmed: "
                 "a letter asking the exchange to confirm it is the next step."}]


def test_the_recorded_inferred_deposits_read_as_probable_in_the_contract_fixture():
    # Demo 3: two probable Binance deposit addresses, which the walk read on past.
    case_ = json.loads((FIXTURES / "deposit_inferred.json").read_text())
    ends = [s for s in case_["victim_flow"]["stops"] if s["kind"] == "exchange"]
    assert [s["inferred"] for s in ends] == [True]
    assert set(ends[0]["addresses"]) == {d["address"] for d in case_["inferred_deposits"]}
    assert ends[0]["note"] == ("Reached probable exchange deposit addresses, inferred and not confirmed: "
                               "a letter asking the exchange to confirm them is the next step.")
    assert all(s["inferred"] is False for s in case_["victim_flow"]["stops"] if s is not ends[0])


def test_a_wallet_that_sent_nothing_on_is_said_to_still_hold_it():
    flow = build(case([("S", "A", [(1, 70)]), ("S", "B", [(1, 30)]), ("B", "C", [(2, 30)])], max_depth=4))
    assert stops(flow)["no_outflow"] == {
        "kind": "no_outflow", "addresses": ["A", "C"], "amount": 100, "inferred": False,
        "note": "Nothing was seen leaving after the money arrived, so it may still be there."}
    assert "hop_limit" not in stops(flow)


def test_the_fan_out_note_names_its_rule_and_every_wallet_it_cut():
    flow = build(case([("S", "A", [(1, 80)]), ("A", "B", [(2, 50)])], untraced=[("S", 20), ("A", 30)],
                      max_depth=2))
    fan = stops(flow)["fanout_limit"]
    assert fan["addresses"] == ["A", "S"] and fan["amount"] == pytest.approx(20 + 30)
    assert fan["note"] == "Only the largest destinations were followed at A and 1 other wallet."
    assert stops(flow)["hop_limit"]["note"] == "The trace stopped at 2 hops."
    shared = case([("S", "A", [(1, 80)])], untraced=[("S", 20)])
    shared["untraced"][0]["rule"] = "min_share"
    assert stops(build(shared))["fanout_limit"]["note"] == (
        "Only destinations that each took at least a set share of what it sent were followed at S.")


def test_an_older_case_cut_by_the_fan_out_limit_says_so_too():
    # Demo 2 predates `untraced`: its reasons name the wallet the limit cut.
    fan = stops(build(BY_DEMO[2]))["fanout_limit"]
    assert fan["addresses"] == ["0xc68191d4d5ea55d3299c71107be135ac8b278f0a"]
    assert fan["note"] == "Only the 10 largest destinations were followed at 0xc681…8f0a."
    assert round(fan["amount"], 4) == 107.8738


def test_one_hop_is_one_hop():
    flow = build(case([("S", "A", [(1, 10)])], max_depth=1))
    assert stops(flow)["hop_limit"]["note"] == "The trace stopped at 1 hop."


@pytest.mark.parametrize("name", sorted(BY_DEMO))
def test_no_stop_claims_more_than_its_buckets(name):
    flow = build(BY_DEMO[name])
    if flow["status"] != "estimated":
        assert "stops" not in flow
        return
    totals = {b["kind"]: b["amount"] for b in flow["buckets"]}
    by_bucket = {"hop_limit": "beyond_limit", "fanout_limit": "not_followed", "exchange": "exchange",
                 "mixer": "risk", "bridge": "risk", "privacy": "risk"}
    for stop in flow["stops"]:
        assert stop["addresses"] and stop["amount"] > 0 and stop["note"].endswith("."), stop
        if stop["kind"] in by_bucket:
            assert stop["amount"] <= totals[by_bucket[stop["kind"]]] + 1e-6, stop


# -- the version: a flow stored before stops existed is rebuilt -----------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))
    with TestClient(app) as c:
        yield c


def test_a_flow_stored_before_stops_is_rebuilt_on_every_read(client):
    assert victim_flow.VERSION >= 2
    old = {k: v for k, v in build(BY_DEMO[11]).items() if k != "stops"}
    old["version"] = 1  # what g/victim-flow-read's build stored
    stored = {**copy.deepcopy(BY_DEMO[11]), "victim_flow": old}
    models.save_case("v1-flow", BY_DEMO[11]["address"], stored)
    for flow in (upgrade(stored)["victim_flow"], client.get("/trace/v1-flow").json()["victim_flow"]):
        assert flow["version"] == victim_flow.VERSION and stops(flow)["hop_limit"]["note"] == "The trace stopped at 2 hops."
    assert models.get_case("v1-flow").result["victim_flow"] == old, "the stored case is never rewritten"
