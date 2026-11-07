"""A page of spam is read past, within a fixed number of pages (r1-attribution-integrity-3).

Flagging a capped read says the trail may be missing; it does not find it.
On Etherscan a full page that held nothing the walk could follow is now
followed by the next page of the same query, up to max_pages_per_address
(1,000 records, what Tron and NodeReal already scan), so 200 zero-value
records no longer hide a cash-out behind them.
"""
from __future__ import annotations

import httpx

from app.etherscan_client import EtherscanClient
from app.graph_builder import TraceConfig, build_trace_graph
from conftest import addr

SEED, HOP, EXIT, SPAMMER = addr("5eed"), addr("a1"), addr("e8c4"), addr("bad")
T0 = 1_700_000_000
LIMIT = 50


def _row(n, src, dst, wei, ts):
    return {"hash": f"0x{n:064x}", "from": src, "to": dst, "value": str(wei), "timeStamp": str(ts),
            "blockNumber": str(ts - T0 + 1000), "isError": "0"}


class Chain:
    def __init__(self, rows):
        self.rows = rows
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        self.requests.append(q)
        mine = [r for r in self.rows if q["address"] in (r["from"], r["to"])
                and int(r["blockNumber"]) >= int(q.get("startblock", 0))]
        mine.sort(key=lambda r: int(r["timeStamp"]), reverse=q["sort"] == "desc")
        page, size = int(q["page"]), int(q["offset"])
        chunk = mine[(page - 1) * size: page * size]
        if not chunk:
            return httpx.Response(200, json={"status": "0", "message": "No transactions found", "result": []})
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": chunk})

    def client(self) -> EtherscanClient:
        return EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, include_internal=False,
                               client=httpx.Client(transport=httpx.MockTransport(self.handler)))


def _trace(chain: Chain, depth: int = 1):
    return build_trace_graph(SEED, chain.client(), TraceConfig(max_depth=depth, max_txs_per_address=LIMIT),
                             is_terminal=lambda a: a == EXIT)


def test_a_spam_filled_page_is_paged_past_and_the_exit_is_found():
    rows = [_row(1, SEED, EXIT, 10 * 10**18, T0)] + [_row(10 + i, SPAMMER, SEED, 0, T0 + 100 + i)
                                                    for i in range(LIMIT)]
    chain = Chain(rows)
    result = _trace(chain)
    assert result.graph.has_edge(SEED, EXIT)
    assert [q["page"] for q in chain.requests if q["address"] == SEED] == ["1", "2"]
    assert not any("history read limit" in r for r in result.truncation_reasons)


def test_dust_outflows_do_not_stop_paging():
    rows = ([_row(1, SEED, EXIT, 10 * 10**18, T0), _row(2, SEED, SPAMMER, 10**9, T0 + 50)]
            + [_row(10 + i, SPAMMER, SEED, 0, T0 + 100 + i) for i in range(LIMIT - 1)])
    chain = Chain(rows)
    assert _trace(chain).graph.has_edge(SEED, EXIT)


def test_a_page_with_a_real_outflow_costs_no_extra_request():
    rows = ([_row(1, SEED, EXIT, 10 * 10**18, T0 + 500)]
            + [_row(10 + i, SPAMMER, SEED, 0, T0 + 100 + i) for i in range(LIMIT * 3)])
    chain = Chain(rows)
    _trace(chain)
    assert [q["page"] for q in chain.requests if q["address"] == SEED] == ["1"]


def test_paging_stops_after_five_pages_and_says_so():
    rows = [_row(1, SEED, EXIT, 10 * 10**18, T0)] + [_row(10 + i, SPAMMER, SEED, 0, T0 + 100 + i)
                                                    for i in range(LIMIT * 8)]
    chain = Chain(rows)
    result = _trace(chain)
    assert len([q for q in chain.requests if q["address"] == SEED]) == 5
    assert not result.graph.has_edge(SEED, EXIT)
    assert any(r.startswith(f"history read limit at {SEED[:10]}") for r in result.truncation_reasons)


def test_a_hops_read_from_arrival_is_paged_past_dust_too():
    rows = ([_row(1, SEED, HOP, 10 * 10**18, T0)]
            # HOP: dust from the arrival on, then the exit, then a newest page of later dust.
            + [_row(100 + i, HOP, SPAMMER, 10**9, T0 + 10 + i) for i in range(LIMIT)]
            + [_row(2, HOP, EXIT, 9 * 10**18, T0 + 10 + LIMIT + 1)]
            + [_row(1000 + i, HOP, SPAMMER, 10**9, T0 + 10_000 + i) for i in range(LIMIT)])
    chain = Chain(rows)
    result = _trace(chain, depth=2)
    assert result.graph.has_edge(HOP, EXIT)
    forward = [q["page"] for q in chain.requests if q["address"] == HOP and q["sort"] == "asc"]
    assert forward == ["1", "2"]
