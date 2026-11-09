"""Every case read carries its victim flow (app/victim_flow.py).

A new trace stores its flow, built from every transfer it saw, before the
appendix trims them. Recorded demos and older cases were saved before the
flow existed, so it is built when they are read: by the contract's upgrade,
by GET /demos/recorded and by GET /trace/{id}, for the case and for each
follow-on. A flow the case carries is served as it is while its `version`
is current; an older one is rebuilt from the stored case on read.
It is built in the worker thread, never on the event loop, and for a reader
who is not the case's owner it is built from the copy that reader may see
(case_privacy.for_reader), so it shows them nothing that copy withholds.

Throwaway SQLite file, recorded data only: no network.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

import fastapi.routing
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import config, models, ownership, pipeline, victim_flow
from app.case_privacy import for_reader
from app.contracts import read_case, upgrade
from app.etherscan_client import Transaction
from app.main import app
from app.pipeline import TraceRequest
from app.routes import demos
from conftest import addr

DATA = Path(__file__).resolve().parent.parent / "data"
BY_DEMO = {d["demo"]: d["result"] for d in json.loads((DATA / "recorded_demos.json").read_text())}
TT4Y = "TT4yg2GguWvN5j8Xeb7nUB5Hg2wWd1dFp3"

OWNER_KEY = "f" * 32
OWNER_HASH = hashlib.sha256(OWNER_KEY.encode()).hexdigest()
OWNER = {ownership.OWNER_HEADER: OWNER_KEY}
STRANGERS = [{}, {ownership.OWNER_HEADER: "s" * 32}]
STORED = {"version": victim_flow.VERSION, "status": "estimated", "method": "prorata", "buckets": [],
          "notes": ["built at trace time"]}
STALE = [{k: v for k, v in STORED.items() if k != "version"}, {**STORED, "version": victim_flow.VERSION - 1}]
NOT_APPLICABLE = {"version": victim_flow.VERSION, "status": "not_applicable"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'f.db'}", future=True))
    with TestClient(app) as c:
        yield c


def demo(n: int) -> dict:
    return copy.deepcopy(BY_DEMO[n])


def amounts(flow: dict) -> dict[str, float]:
    return {b["kind"]: round(b["amount"], 6) for b in flow["buckets"]}


def test_recorded_demo_11_is_served_with_its_flow(client):
    flow = client.get("/demos/recorded/11").json()["victim_flow"]
    assert flow["status"] == "estimated" and flow["totals"]["denominator"] == 9891.0
    got = amounts(flow)
    assert round(got["exchange"], 2) == 959.58 and round(got["beyond_limit"], 2) == 8732.34
    assert round(got["not_followed"], 2) == 196.78 and got["left"] == 2.297459 and got["held"] == 0
    assert next(b for b in flow["buckets"] if b["kind"] == "left")["addresses"] == [TT4Y]
    assert flow == victim_flow.build(BY_DEMO[11])


def test_a_stored_case_read_gets_its_flow(client):
    models.save_case("flow-case", BY_DEMO[11]["address"], demo(11), owner_hash=OWNER_HASH)
    for headers in [OWNER, *STRANGERS]:
        assert client.get("/trace/flow-case", headers=headers).json()["victim_flow"] == victim_flow.build(BY_DEMO[11])
    assert "victim_flow" not in models.get_case("flow-case").result, "a read never changes the stored case"


def test_the_contract_upgrade_adds_the_flow():
    v2 = upgrade(BY_DEMO[11])
    assert v2["victim_flow"] == victim_flow.build(BY_DEMO[11])
    assert read_case(BY_DEMO[11]).victim_flow == v2["victim_flow"]


def _reads(client, monkeypatch, flow) -> list[dict]:
    """The flow each read path gives demo 11 stored with `flow`."""
    models.save_case("kept", BY_DEMO[11]["address"], {**demo(11), "victim_flow": flow}, owner_hash=OWNER_HASH)
    recording = {"demo": 11, "recorded_at": "2026-11-09T00:00:00Z", "result": {**demo(11), "victim_flow": flow}}
    monkeypatch.setattr(demos, "_recordings", lambda: {11: recording})
    return [client.get("/trace/kept", headers=OWNER).json()["victim_flow"],
            client.get("/trace/kept").json()["victim_flow"],
            client.get("/demos/recorded/11").json()["victim_flow"],
            upgrade({**demo(11), "victim_flow": flow})["victim_flow"]]


def test_a_current_stored_flow_is_never_rebuilt(client, monkeypatch):
    assert _reads(client, monkeypatch, STORED) == [STORED] * 4


@pytest.mark.parametrize("stale", STALE, ids=["no version", "older version"])
def test_a_stale_stored_flow_is_rebuilt_on_read(client, monkeypatch, stale):
    """A flow from before build() last changed is rebuilt from the stored
    case (its appendix may be trimmed). The stored case is never rewritten."""
    assert _reads(client, monkeypatch, stale) == [victim_flow.build(BY_DEMO[11])] * 4
    assert models.get_case("kept").result["victim_flow"] == stale


def test_every_flow_says_which_build_made_it():
    assert victim_flow.VERSION >= 1
    for result in [BY_DEMO[11], BY_DEMO[4], {"direction": "sideways"}, None]:
        assert victim_flow.build(result)["version"] == victim_flow.VERSION


def test_each_follow_on_is_served_with_its_flow(client):
    """A follow-on is a full case of its own, and upgrade() gives it a flow:
    every read does the same, and keeps a current flow the follow-on carries."""
    want = upgrade(BY_DEMO[3])["follow_ons"][0]["result"]["victim_flow"]
    assert want["status"] == "estimated"
    models.save_case("swap-case", BY_DEMO[3]["address"], demo(3), owner_hash=OWNER_HASH)
    for body in (client.get("/demos/recorded/3").json(), client.get("/trace/swap-case").json()):
        assert body["follow_ons"][0]["result"]["victim_flow"] == want
    carried = demo(3)
    carried["follow_ons"][0]["result"]["victim_flow"] = STORED
    models.save_case("swap-kept", BY_DEMO[3]["address"], carried, owner_hash=OWNER_HASH)
    assert client.get("/trace/swap-kept").json()["follow_ons"][0]["result"]["victim_flow"] == STORED
    assert "victim_flow" not in models.get_case("swap-case").result["follow_ons"][0]["result"]


# -- a new trace: its flow is built before the appendix trims the transfers --
SEED, HOP, SIDE, SINK = addr("5eed"), addr("a1"), addr("b1"), addr("c1")
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"  # data/exchange_labels.json
T = 1_700_000_000


def test_a_new_trace_stores_the_flow_built_before_trimming(monkeypatch):
    """SEED -> HOP -> Binance is the route; SEED -> SIDE -> SINK is a side
    branch whose 60 small transfers the appendix trims. Built from every
    transfer, SIDE's window is read from them (traced_only); built from the
    trimmed appendix, it would fall back to the link's bounds (edge_bounds)."""
    n = iter(range(1, 10**6))

    def tx(s, d, v, t):
        return Transaction(hash="0x%064x" % next(n), from_address=s, to_address=d, value_native=v,
                           value_wei=int(v * 1e18), timestamp=t, block_number=t - T + 10**6, is_error=False,
                           asset="ETH")
    history = [tx(SEED, HOP, 10.0, T + 1), tx(HOP, BINANCE_14, 9.0, T + 2), tx(SEED, SIDE, 5.0, T + 3),
               *(tx(SIDE, SINK, 0.05, T + 10 + i) for i in range(60))]

    class Fake:
        def get_outgoing_transactions(self, address, limit=None):
            return [t for t in history if t.from_address == address]

        def get_incoming_transactions(self, address, limit=None):
            return [t for t in history if t.to_address == address]

    @contextmanager
    def open_source(chain, asset):
        yield Fake()
    monkeypatch.setattr(pipeline, "open_source", open_source)
    monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
    monkeypatch.setattr(config, "TRANSFERS_APPENDIX_MAX", 10)
    r = pipeline.run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=3,
                                        follow_swaps=False))
    assert r["exchange"] == "Binance" and r["transfers_omitted"] > 0
    flow = r["victim_flow"]
    assert flow["version"] == victim_flow.VERSION and flow["status"] == "estimated"
    side = next(x for x in flow["nodes"] if x["address"] == SIDE)
    assert side["basis"] == "traced_only"
    assert not any("not listed" in note for note in flow["notes"])
    # The trimmed case alone would have given the dashed fallback.
    trimmed = victim_flow.build(r)
    assert next(x for x in trimmed["nodes"] if x["address"] == SIDE)["basis"] == "edge_bounds"


@pytest.mark.parametrize("n", [4, 5])
def test_a_reverse_trace_is_not_applicable(client, n):
    assert BY_DEMO[n]["direction"] == "incoming"
    assert client.get(f"/demos/recorded/{n}").json()["victim_flow"] == NOT_APPLICABLE
    models.save_case(f"reverse-{n}", BY_DEMO[n]["address"], demo(n), owner_hash=OWNER_HASH)
    assert client.get(f"/trace/reverse-{n}").json()["victim_flow"] == NOT_APPLICABLE


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def test_the_flow_is_built_and_encoded_off_the_event_loop(client, monkeypatch):
    seen, real = [], victim_flow.build

    def spy(result, *args, **kwargs):
        seen.append(_on_event_loop())
        return real(result, *args, **kwargs)

    def refuse(*_a, **_k):
        raise AssertionError("a case went through jsonable_encoder on the event loop")
    monkeypatch.setattr(victim_flow, "build", spy)
    monkeypatch.setattr(fastapi.routing, "jsonable_encoder", refuse)
    models.save_case("loop-case", BY_DEMO[11]["address"], demo(11), owner_hash=OWNER_HASH)
    assert client.get("/trace/loop-case").status_code == 200
    assert client.get("/demos/recorded/11").status_code == 200
    assert seen == [False, False]


# -- privacy: a stranger's flow shows nothing for_reader withholds -------------
# Demo 11 as a payment-mode complaint: the victim's payment hash, block, time,
# paying wallet and NCRP number are in the stored case, and each leads a block
# explorer back to the victim.
NCRP = "31911250098765"
PAYER = "TVictimPaidFromThisWa11et000000001"
PAY_HASH = "9e1f" + "ab" * 28 + "77d2"
PAY_BLOCK = 68_391_002
PAID_AT = 1_734_355_560  # an hour before the reported wallet's first transfer out
NEEDLES = [NCRP, PAYER, PAY_HASH, PAY_HASH[:6], str(PAY_BLOCK), str(PAID_AT)]


def payment_case() -> dict:
    case = demo(11)
    case["intake"] = {"mode": "payment", "ncrp_ack": NCRP, "victim_address": PAYER, "payments": [
        {"tx_hash": PAY_HASH, "chain": "tron", "asset": "USDT", "amount": 9891.0, "from": PAYER,
         "to": case["address"], "block": PAY_BLOCK, "timestamp": PAID_AT, "found_by": "victim",
         "payer_label": None, "payer_is_victim": True}]}
    case["reported_amount"] = 9891.0
    for n in case["graph"]["nodes"]:
        if n["address"] == case["address"]:
            n["window_start"] = PAID_AT
    case["statement"] = {**case["statement"], "window_start": PAID_AT, "credits": [
        {"tx": PAY_HASH, "time": PAID_AT, "amount": 9891.0, "counterparty": PAYER, "before_window": False}]}
    case["warnings"] = [*case["warnings"], f"Payment {PAY_HASH[:6]}…{PAY_HASH[-4:]} reached the wallet."]
    return case


def addresses(flow: dict) -> set[str]:
    return ({n["address"] for n in flow["nodes"]} | {a for lk in flow["links"] for a in (lk["source"], lk["target"])}
            | {a for b in flow["buckets"] for a in b["addresses"]} | set(flow["lead"]["path"])
            | {p["address"] for p in flow["passed_through"]})


# "on read": stored before the flow existed. "at trace time": stored with a
# current flow built from the full, unredacted case, as run_trace stores one.
@pytest.mark.parametrize("stored", [payment_case(), upgrade(payment_case())], ids=["on read", "at trace time"])
def test_a_strangers_flow_leaks_nothing_new(client, stored):
    models.save_case("pay-flow", stored["address"], stored, owner_hash=OWNER_HASH)
    assert any(n in json.dumps(stored) for n in NEEDLES)
    for headers in STRANGERS:
        body = client.get("/trace/pay-flow", headers=headers).json()
        flow = body["victim_flow"]
        assert flow["status"] == "estimated"
        assert [n for n in NEEDLES if n in json.dumps(flow)] == []
        # Exactly what the copy this reader sees gives, naming only wallets it shows.
        assert flow == victim_flow.build(for_reader(stored, OWNER_HASH, None))
        assert addresses(flow) <= {n["address"] for n in body["graph"]["nodes"]}
    assert client.get("/trace/pay-flow", headers=OWNER).json()["victim_flow"]["status"] == "estimated"
