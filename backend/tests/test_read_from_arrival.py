"""A busy wallet is read from when the traced funds arrived (graph_builder +
etherscan_client.get_outgoing_transactions_since).

The provider returns the newest page of a wallet's transfers. When a wallet
has been busy since the funds arrived, that page can be entirely later than
the transfers that moved the funds on -- which the time rule then has
nothing to follow. These pin the second read and its limits.
"""
from __future__ import annotations

from app.etherscan_client import Transaction
from app.graph_builder import OUTGOING, TraceConfig, build_trace_graph

from conftest import addr

SEED, MID, EXCH, NOISE = addr("5eed"), addr("a1d"), addr("e8c4"), addr("0e5e")
T0, BLOCK0 = 1_700_000_000, 18_000_000


def tx(src, dst, value, ts, block, n=0):
    return Transaction(hash=f"0x{abs(hash((src, dst, ts, n))):064x}"[:66], from_address=src, to_address=dst,
                       value_native=value, value_wei=int(value * 1e18), timestamp=ts, block_number=block,
                       is_error=False, asset="ETH")


class BusyClient:
    """MID received the funds at T0+100, sent them to EXCH at T0+200, then made
    `later` small transfers -- so its newest page of `limit` misses the EXCH one."""

    def __init__(self, later: int, with_since: bool = True):
        self.history = {
            SEED: [tx(SEED, MID, 10.0, T0 + 100, BLOCK0 + 10)],
            MID: [tx(MID, EXCH, 9.9, T0 + 200, BLOCK0 + 20)]
                 + [tx(MID, NOISE, 0.5, T0 + 1000 + i, BLOCK0 + 100 + i, i) for i in range(later)],
        }
        self.since_calls: list[tuple[str, int]] = []
        if not with_since:
            self.get_outgoing_transactions_since = None  # a provider without the read

    def get_outgoing_transactions(self, address, limit=None):
        newest = sorted(self.history.get(address, []), key=lambda t: t.timestamp, reverse=True)
        return newest[:limit] if limit else newest

    def get_outgoing_transactions_since(self, address, start_block, limit=None):
        self.since_calls.append((address, start_block))
        oldest = sorted((t for t in self.history.get(address, []) if t.block_number >= start_block),
                        key=lambda t: t.timestamp)
        return oldest[:limit] if limit else oldest


CFG = TraceConfig(max_depth=2, max_txs_per_address=5)


def test_a_busy_wallet_is_read_again_from_the_arrival_and_the_exit_is_found():
    client = BusyClient(later=8)
    result = build_trace_graph(SEED, client, cfg=CFG, is_terminal=lambda a: a == EXCH, direction=OUTGOING)
    assert result.graph.has_edge(MID, EXCH)
    assert client.since_calls == [(MID, BLOCK0 + 10)]  # from the block the funds arrived in
    assert result.read_from_arrival == [MID]
    assert result.graph.nodes[MID]["read_from_arrival"] is True


def test_without_the_second_read_the_exit_was_missed():
    """The behaviour this fixes, pinned: a provider that cannot read from a
    block (NodeReal, Tron) still sees only the newest page."""
    client = BusyClient(later=8, with_since=False)
    result = build_trace_graph(SEED, client, cfg=CFG, is_terminal=lambda a: a == EXCH, direction=OUTGOING)
    assert not result.graph.has_edge(MID, EXCH)
    assert result.read_from_arrival == []


def test_a_quiet_wallet_costs_no_extra_request():
    client = BusyClient(later=2)  # 3 transfers, under the page size of 5
    result = build_trace_graph(SEED, client, cfg=CFG, is_terminal=lambda a: a == EXCH, direction=OUTGOING)
    assert result.graph.has_edge(MID, EXCH)
    assert client.since_calls == []


def test_the_seed_is_never_windowed_so_never_re_read():
    client = BusyClient(later=8)
    client.history[SEED] = [tx(SEED, MID, 10.0, T0 + 100 + i, BLOCK0 + 10 + i, i) for i in range(9)]
    build_trace_graph(SEED, client, cfg=CFG, is_terminal=lambda a: a == EXCH, direction=OUTGOING)
    assert all(address != SEED for address, _ in client.since_calls)


def test_the_etherscan_request_reads_forward_from_the_block_and_keeps_only_sends():
    import httpx

    from app import api_budget
    from app.etherscan_client import EtherscanClient

    api_budget.reset()
    sender = "0xaaaa0000000000000000000000000000000000aa"
    raw = lambda frm, to, value, block: {  # noqa: E731
        "hash": f"0x{block:064x}", "from": frm, "to": to, "value": str(value), "timeStamp": "1700000000",
        "blockNumber": str(block), "isError": "0", "txreceipt_status": "1", "input": "0x",
    }
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": [
            raw(sender, "0xbbbb0000000000000000000000000000000000bb", 10**18, 18_000_005),
            raw("0xcccc0000000000000000000000000000000000cc", sender, 10**18, 18_000_006),  # incoming: dropped
            raw(sender, "0xdddd0000000000000000000000000000000000dd", 0, 18_000_007),       # zero value: dropped
        ]})

    client = EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, include_internal=False,
                             client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = client.get_outgoing_transactions_since(sender, 18_000_000, limit=200)
    assert [t.to_address for t in out] == ["0xbbbb0000000000000000000000000000000000bb"]
    assert seen[0]["startblock"] == "18000000" and seen[0]["sort"] == "asc" and seen[0]["offset"] == "200"
    api_budget.reset()


class CollectingClient(BusyClient):
    """A scam wallet that mostly receives: after sending the funds on at T0+200
    it took in many victim payments. Etherscan's page holds both directions, so
    the newest page is full of inflows and carries no transfer MID sent."""

    def __init__(self, inflows: int):
        super().__init__(later=0)
        self.inflows = [tx(NOISE, MID, 0.2, T0 + 1000 + i, BLOCK0 + 100 + i, i) for i in range(inflows)]

    def get_outgoing_transactions(self, address, limit=None):
        page = sorted(self.history.get(address, []) + (self.inflows if address == MID else []),
                      key=lambda t: t.timestamp, reverse=True)[:limit]
        self.page = {**getattr(self, "page", {}), address: (len(page) >= limit, min((t.timestamp for t in page), default=None))}
        return [t for t in page if t.from_address == address]

    def newest_page_info(self, address):
        return self.page.get(address)


def test_a_wallet_whose_page_is_full_of_inflows_is_still_read_from_the_arrival():
    client = CollectingClient(inflows=8)
    result = build_trace_graph(SEED, client, cfg=CFG, is_terminal=lambda a: a == EXCH, direction=OUTGOING)
    assert result.graph.has_edge(MID, EXCH)
    assert client.since_calls == [(MID, BLOCK0 + 10)]
    # And its outgoing history is not called complete.
    assert result.graph.nodes[MID]["outgoing_history_capped"] is True


def test_the_etherscan_client_reports_a_full_page_whatever_its_direction():
    import httpx

    from app import api_budget
    from app.etherscan_client import EtherscanClient

    api_budget.reset()
    me = "0xaaaa0000000000000000000000000000000000aa"
    rows = [{"hash": f"0x{i:064x}", "from": "0xcccc0000000000000000000000000000000000cc", "to": me,
             "value": "1", "timeStamp": str(1_700_000_000 + i), "blockNumber": str(18_000_000 + i),
             "isError": "0", "txreceipt_status": "1", "input": "0x"} for i in range(3)]
    client = EtherscanClient(api_key="k2", chain_id=1, min_interval=0.0, include_internal=False,
                             client=httpx.Client(transport=httpx.MockTransport(
                                 lambda r: httpx.Response(200, json={"status": "1", "message": "OK", "result": rows}))))
    assert client.get_outgoing_transactions(me, limit=3) == []  # all incoming
    assert client.newest_page_info(me) == (True, 1_700_000_000)
    api_budget.reset()
