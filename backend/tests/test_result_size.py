"""A case has a size bound (r1-trace-engine-5).

The transfers appendix listed every transfer on every followed edge: a dense
cluster of 380 wallets gave 71,283 rows and a 21 MB case, which filled Neon's
0.5 GB long before the case-count cap, and each finished job kept its full
payload in memory for 30 minutes, up to 500 jobs. The appendix is now capped
(the full count and a hash over every transfer are kept), an oversized case
is shown but not stored, and the job store keeps a stored case's id, not
its payload.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import networkx as nx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import config, jobs, models, ownership, victim_flow
from app.contracts import read_case, upgrade
from app.contracts.case_v2 import on_read
from app.main import app
from app.pipeline import _all_transfers, _appendix, appendix_sha256
from app.report import build_report, render_text_report
from app.request_letters import _transfers_into
from app.routes import cases
from app.pipeline import TraceRequest
from conftest import addr

DATA = Path(__file__).resolve().parent.parent / "data"

SEED, HOP, EXCH = addr("5eed"), addr("a1"), addr("e8c4")


def _dense(wallets: int = 60, per_edge: int = 50) -> nx.DiGraph:
    """SEED -> HOP -> EXCH, plus a cluster of wallets paying each other many times."""
    graph = nx.DiGraph()
    n = [0]

    def edge(src, dst, count, value=1.0):
        txs = []
        for _ in range(count):
            n[0] += 1
            txs.append({"hash": f"0x{n[0]:064x}", "value_native": value, "timestamp": 1_700_000_000 + n[0],
                        "block_number": n[0], "internal": False})
        graph.add_edge(src, dst, transactions=txs, value_native=value * count, tx_count=count)
    edge(SEED, HOP, 3, 10.0)
    edge(HOP, EXCH, 2, 9.0)
    cluster = [addr(f"c{i:x}") for i in range(wallets)]
    for i, a in enumerate(cluster):
        edge(SEED if i == 0 else cluster[i - 1], a, per_edge, 0.01)
    return graph


def test_a_dense_trace_lists_a_bounded_appendix_and_commits_to_all_of_it(monkeypatch):
    monkeypatch.setattr(config, "TRANSFERS_APPENDIX_MAX", 200)
    graph = _dense()
    rows = _all_transfers(graph)
    out = _appendix(rows, {(SEED, HOP), (HOP, EXCH)}, {EXCH})
    assert out["transfers_total"] == len(rows) > 2000
    assert out["transfers_omitted"] == len(rows) - len(out["transfers"]) > 0
    assert len(out["transfers"]) <= 200
    assert out["transfers_sha256"] == appendix_sha256(rows)
    # Everything on the route and into the exchange is listed, so a letter still cites it.
    listed = {(t["from"], t["to"], t["hash"]) for t in out["transfers"]}
    for t in rows:
        if (t["from"], t["to"]) in {(SEED, HOP), (HOP, EXCH)}:
            assert (t["from"], t["to"], t["hash"]) in listed
    assert len(_transfers_into(out, EXCH)) == 2
    assert len(json.dumps(out)) < 2 * 1024 * 1024


def test_a_small_trace_lists_every_transfer_unchanged():
    graph = _dense(wallets=2, per_edge=3)
    rows = _all_transfers(graph)
    out = _appendix(rows, set(), set())
    assert out["transfers"] == rows and out["transfers_omitted"] == 0


def test_the_hash_is_the_canonical_one_over_every_transfer():
    import hashlib

    rows = _all_transfers(_dense(wallets=2, per_edge=2))
    canonical = "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
    assert appendix_sha256(rows) == hashlib.sha256(canonical.encode()).hexdigest()


def test_the_report_says_the_appendix_is_partial(monkeypatch):
    monkeypatch.setattr(config, "TRANSFERS_APPENDIX_MAX", 50)
    rows = _all_transfers(_dense(wallets=10, per_edge=20))
    result = {"address": SEED, "chain": "ethereum", "asset": "ETH", "native_symbol": "ETH", "direction": "outgoing",
              "graph": {"nodes": [{"id": SEED}], "edges": []}, "truncation_reasons": [], "warnings": [],
              **_appendix(rows, set(), set())}
    case = models.Case(id="case-1", address=SEED, created_at="2026-11-07T12:00:00+00:00",
                       result_json=json.dumps(result))
    text = render_text_report(build_report(case))
    assert f"Individual transactions    : {len(rows)} (50 listed in Appendix B)" in text
    assert f"lists 50 of the trace's {len(rows)}" in text and result["transfers_sha256"] in text.replace("\n", "")


def test_old_cases_without_the_counts_still_read():
    assert read_case({"transfers": [], "address": SEED}).transfers_omitted is None


def test_upgrade_does_not_deep_copy_a_case():
    big = {"graph": {"nodes": [{"id": SEED}]}, "transfers": [], "follow_ons": [{"result": {"transfers": []}}]}
    out = upgrade(big)
    assert out["graph"] is big["graph"]  # shared, not copied
    assert "contract_version" not in big and "contract_version" not in big["follow_ons"][0]["result"]


def test_an_oversized_case_is_shown_but_not_stored(monkeypatch):
    monkeypatch.setattr(config, "MAX_CASE_BYTES", 1000)
    saved = []
    monkeypatch.setattr(models, "save_case", lambda *a, **k: saved.append(a))
    monkeypatch.setattr(models, "case_count", lambda: 0)
    monkeypatch.setattr(models, "case_count_for", lambda owner: 0)
    payload = {"address": SEED, "transfers": [{"hash": "0x" + "a" * 64}] * 50}
    out = cases.store_result(payload, TraceRequest(address=SEED), owner="o" * 64)
    assert out["case_id"] is None and not saved
    assert any("too large to save" in w for w in out["warnings"])


def test_a_stored_job_keeps_its_case_id_not_its_payload(monkeypatch):
    store = jobs.JobStore()
    job = store.create()
    store.finish(job, result={"case_id": "case-1", "transfers": [1] * 1000})
    assert job.snapshot(with_result=True)["result"]  # the page watching picks it up at once
    monkeypatch.setattr(time, "time", lambda: job.finished + jobs.RESULT_HOLD_SECONDS + 1)
    held = store.get(job.id)
    assert held is not None and held.result is None
    assert held.snapshot(with_result=True)["case_id"] == "case-1"


def test_an_unsaved_job_is_forgotten_after_five_minutes(monkeypatch):
    store = jobs.JobStore()
    job = store.create()
    store.finish(job, result={"case_id": None, "exchange": "Binance"})
    monkeypatch.setattr(time, "time", lambda: job.finished + jobs.UNSAVED_RESULT_TTL + 1)
    assert store.get(job.id) is None


def test_verify_case_says_what_a_capped_appendix_left_unchecked():
    from scripts.verify_case import appendix_note

    report = {"appendix": {"transactions": [{}] * 3, "transactions_total": 10, "transactions_omitted": 7}}
    assert appendix_note(report) == ("The report lists 3 of the trace's 10 transfers; the other 7 are not "
                                     "in Appendix B, so they were not checked.")
    assert appendix_note({"appendix": {"transactions": []}}) is None


def test_a_dense_case_near_the_limit_reads_back_with_the_flow_it_was_shown(tmp_path, monkeypatch):
    # The flow adds 15-20 % to a case, so a dense case that fitted before it
    # did is still stored: measured without its flows, kept with them. A flow
    # rebuilt on read from the trimmed appendix would differ from the one the
    # officer saw (pipeline.run_trace builds it from every transfer).
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True))
    demo = next(d["result"] for d in json.loads((DATA / "recorded_demos.json").read_text()) if d["demo"] == 8)
    rows = demo["transfers"]
    live = victim_flow.build({**demo, "transfers": rows, "transfers_omitted": 0})
    monkeypatch.setattr(config, "TRANSFERS_APPENDIX_MAX", len(rows) // 3)
    payload = {**demo, **_appendix(rows, set(), set()), "victim_flow": live}
    assert on_read({k: v for k, v in payload.items() if k != "victim_flow"})["victim_flow"] != live
    # store_result adds the case id and time (about 90 bytes) before it measures.
    bare = len(json.dumps({k: v for k, v in payload.items() if k != "victim_flow"}))
    assert bare + 150 < len(json.dumps(payload))
    monkeypatch.setattr(config, "MAX_CASE_BYTES", bare + 150)
    key = "k" * 32
    with TestClient(app) as client:
        out = cases.store_result(payload, TraceRequest(address=SEED), owner=ownership.owner_hash(key))
        assert out["case_id"] and out["victim_flow"] is live  # the officer sees it now
        got = client.get(f"/trace/{out['case_id']}", headers={ownership.OWNER_HEADER: key}).json()
    assert got["victim_flow"] == json.loads(json.dumps(live))
    # Past the limit even without its flows, the case is still refused.
    monkeypatch.setattr(config, "MAX_CASE_BYTES", bare - 1000)
    assert cases.store_result(dict(payload), TraceRequest(address=SEED), owner=ownership.owner_hash(key))["case_id"] is None
