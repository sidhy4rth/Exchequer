"""A case has a request budget per provider, beside its clock (r1-providers-2).

Nothing counted provider requests: one trace of a branching neighbourhood at
depth 6 measured 2,252 NodeReal requests (~551k compute units) and 367
Etherscan calls, with follow-ons on top, so a handful of anonymous traces could
spend the shared free-tier quota the live site depends on. Each case now has a
per-provider unit budget (compute units on NodeReal), charged at every network
request a client makes and shared with its follow-ons. Past it the walk stops,
marked truncated with the reason, as the time limit does.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi import HTTPException

from app import api_budget, pipeline
from app.api_budget import BudgetSpent, TraceBudget
from app.etherscan_client import EtherscanClient
from app.nodereal_client import METHOD_CU, NoderealClient
from app.pipeline import TraceRequest, run_trace
from app.tron_tags import TronScanTags

T0 = 1_700_000_000


def _tree(fan: int, depth: int) -> dict[str, list[tuple[str, int]]]:
    """address -> [(recipient, n)]: every wallet pays `fan` new wallets."""
    out: dict[str, list[tuple[str, int]]] = {}
    level, n = ["0x" + "5e" * 20], 0
    for _ in range(depth):
        nxt = []
        for a in level:
            for _ in range(fan):
                n += 1
                child = "0x" + f"{n:040x}"
                out.setdefault(a, []).append((child, n))
                nxt.append(child)
        level = nxt
    return out


TREE = _tree(3, 6)
SEED = "0x" + "5e" * 20


def _etherscan(calls: list) -> EtherscanClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        q = request.url.params
        address = q.get("address")
        rows = [{"hash": f"0x{n:064x}", "from": address, "to": child, "value": str(10**18),
                 "timeStamp": str(T0 + n), "blockNumber": str(18_000_000 + n), "isError": "0"}
                for child, n in TREE.get(address, [])]
        if not rows:
            return httpx.Response(200, json={"status": "0", "message": "No transactions found", "result": []})
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})
    return EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, include_internal=False,
                           client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture
def etherscan_tree(monkeypatch):
    calls: list = []

    @contextmanager
    def open_source(chain, asset):
        client = _etherscan(calls)
        try:
            yield client
        finally:
            client.close()
    monkeypatch.setattr(pipeline, "open_source", open_source)
    return calls


def test_an_etherscan_trace_stops_at_its_request_budget_and_says_why(etherscan_tree):
    budget = TraceBudget(120, 30, limits={"etherscan": 20})
    r = run_trace(TraceRequest(address=SEED, chain="ethereum", max_depth=6, follow_swaps=False), budget=budget)
    assert len(etherscan_tree) <= 20  # without a budget: one read per address, ~364
    assert r["truncated"] is True and r["stopped_by"] == "budget"
    assert any("Etherscan request budget for this trace (20 requests) reached" in t
               for t in r["truncation_reasons"])
    assert r["addresses_unexpanded_by_budget"] > 0
    assert r["provider_units"]["etherscan"]["requests"] == len(etherscan_tree)
    assert r["provider_units"]["etherscan"]["case_limit"] == 20


def test_a_trace_within_its_budget_is_not_stopped(etherscan_tree):
    r = run_trace(TraceRequest(address=SEED, chain="ethereum", max_depth=2, follow_swaps=False),
                  budget=TraceBudget(120, 30, limits={"etherscan": 600}))
    assert r["stopped_by"] is None
    assert not any("request budget" in t for t in r["truncation_reasons"])
    assert r["provider_units"]["etherscan"]["requests"] == len(etherscan_tree)


def test_a_seed_beyond_the_budget_is_a_clear_503_with_no_request(etherscan_tree):
    budget = TraceBudget(120, 30, limits={"etherscan": 2})
    budget.charge("etherscan", 2)  # e.g. spent by the trace this one follows on from
    with pytest.raises(HTTPException) as exc:
        run_trace(TraceRequest(address=SEED, chain="ethereum", follow_swaps=False), budget=budget)
    assert exc.value.status_code == 503
    assert "request budget" in exc.value.detail
    assert etherscan_tree == []


def test_the_walk_leaves_part_of_the_budget_for_the_reads_after_it():
    budget = TraceBudget(60, 10, limits={"etherscan": 10})
    budget.walking = True
    for _ in range(int(10 * api_budget.WALK_UNIT_SHARE)):
        budget.charge("etherscan", 1)
    with pytest.raises(BudgetSpent):
        budget.charge("etherscan", 1)
    budget.walking = False
    budget.charge("etherscan", 1)  # a receipt, a balance: still allowed
    assert budget.stopped_by == "budget"


def test_a_follow_on_is_skipped_once_the_case_budget_is_spent(monkeypatch):
    budget = TraceBudget(60, 10, limits={"etherscan": 1})
    with pytest.raises(BudgetSpent):
        budget.charge("etherscan", 5)
    monkeypatch.setattr(pipeline, "run_trace", lambda *a, **k: pytest.fail("a follow-on was traced"))
    from app import config
    import networkx as nx
    chain = config.get_chain("ethereum")
    swap = {"sender": SEED, "output_read": True, "asset_out": "USDT", "amount_out": 10.0, "timestamp": T0}
    out = pipeline._follow_swaps(TraceRequest(address=SEED, chain="ethereum"), chain, "ETH",
                                 nx.DiGraph(), [swap], 4, budget=budget, seed=SEED)
    assert "request budget was spent" in out[0]["error"]


# -- NodeReal: compute units --------------------------------------------------
HEAD = 50_000_000


def _nodereal(cu: list) -> NoderealClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        cu.append(METHOD_CU.get(body["method"], 25))
        if body["method"] == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(HEAD)})
        if body["method"] == "eth_getTransactionCount":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x0"})
        if body["method"] == "eth_getBlockByNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"timestamp": hex(T0)}})
        params = body["params"][0]
        address = params.get("fromAddress")
        lo, hi = int(params["fromBlock"], 16), int(params["toBlock"], 16)
        rows = [{"hash": f"0x{n:064x}", "from": address, "to": child, "value": hex(10**18), "decimal": 18,
                 "blockNum": hex(HEAD - 1000 + n), "blockTimeStamp": T0 + n, "asset": "BNB", "receiptsStatus": 1}
                for child, n in TREE.get(address or "", []) if lo <= HEAD - 1000 + n <= hi]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"transfers": rows}})
    return NoderealClient(api_key="k", min_interval=0, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_a_bsc_trace_stops_at_its_compute_unit_budget(monkeypatch):
    cu: list = []

    @contextmanager
    def open_source(chain, asset):
        yield _nodereal(cu)
    monkeypatch.setattr(pipeline, "open_source", open_source)
    r = run_trace(TraceRequest(address=SEED, chain="bsc", max_depth=6, follow_swaps=False),
                  budget=TraceBudget(120, 30, limits={"nodereal": 5_000}))
    assert sum(cu) <= 5_000
    assert r["stopped_by"] == "budget"
    assert any("NodeReal request budget for this trace (5,000 compute units)" in t for t in r["truncation_reasons"])
    assert r["provider_units"]["nodereal"]["units"] == sum(cu)
    assert r["provider_units"]["nodereal"]["unit"] == "compute units"


# -- every client counts, and a cache hit costs nothing -----------------------
def test_a_cache_hit_costs_no_units():
    calls: list = []
    client = _etherscan(calls)
    client.budget = TraceBudget(60, 10, limits={"etherscan": 5})
    client.get_outgoing_transactions(SEED)
    client.get_outgoing_transactions(SEED)
    assert len(calls) == 1 and client.budget.requests == {"etherscan": 1}


def test_a_tronscan_tag_past_its_budget_is_skipped_without_a_request():
    calls: list = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"publicTag": ""})
    tags = TronScanTags("k", client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0)
    tags.budget = TraceBudget(60, 10, limits={"tronscan": 1})
    tags.account("T" + "1" * 33)
    assert tags.account("T" + "2" * 33) is None
    assert len(calls) == 1


def test_a_trongrid_request_past_the_budget_is_never_sent():
    from app.tron_client import TronClient

    calls: list = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [], "success": True})
    client = TronClient(api_key="k", min_interval=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.budget = TraceBudget(60, 10, limits={"trongrid": 1})
    client._get("/v1/accounts/T1", {})
    with pytest.raises(BudgetSpent):
        client._get("/v1/accounts/T2", {})
    assert len(calls) == 1
