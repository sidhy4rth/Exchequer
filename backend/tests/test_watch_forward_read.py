"""A watch reads forward from its cursor (r2-g2-watchlist-alerts-0-0).

It used to re-read the newest 50 records and move its cursor to the newest
one, so anything between the old cursor and that page was skipped for good.
On Etherscan the 50 cover both directions and zero-value records: 50
incoming 1-wei transfers, which anyone can send, hid a cash-out. A busy
deposit address did the same with no attacker at all. Every check also
re-ran the trace's full history read (dozens of NodeReal calls on a quiet
BSC wallet). These run the real clients over httpx.MockTransport; nothing
leaves the machine.
"""
from __future__ import annotations

from contextlib import contextmanager

import httpx
import pytest
from sqlalchemy import create_engine

from app import models, ownership, watchlist
from app.etherscan_client import EtherscanClient

KEY = "a" * 32
W = "0x" + "7" * 40
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"
STRANGER = "0x" + "9" * 40
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
HEAD = 100


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'f.db'}", future=True))
    models.init_db()


class Etherscan:
    """txlist / tokentx / txlistinternal over `records`, as Etherscan pages them."""

    def __init__(self, head=HEAD):
        self.records: list[dict] = []
        self.internal: list[dict] = []
        self.requests: list[dict] = []
        self.head = head

    def add(self, block, frm, to, value, token=False, n=0, internal=False):
        rec = {"blockNumber": str(block), "timeStamp": str(1_800_000_000 + block), "from": frm, "to": to,
               "value": str(value), "isError": "0", "hash": f"0x{block:060x}{n:04x}"}
        if token:
            rec.update(contractAddress=USDT, tokenDecimal="6", tokenSymbol="USDT")
        (self.internal if internal else self.records).append(rec)

    def handler(self, request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        self.requests.append(q)
        if q.get("module") == "proxy":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(self.head)})
        token = q["action"] == "tokentx"
        lo, hi = int(q.get("startblock", 0)), int(q.get("endblock", 99999999))
        pool = self.internal if q["action"] == "txlistinternal" else self.records
        rows = [r for r in pool if lo <= int(r["blockNumber"]) <= hi and bool(r.get("contractAddress")) == token
                and W in (r["from"], r["to"])]
        rows.sort(key=lambda r: int(r["blockNumber"]), reverse=q.get("sort") == "desc")
        rows = rows[:int(q.get("offset", 10000))]
        if not rows:
            return httpx.Response(200, json={"status": "0", "message": "No transactions found", "result": []})
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})

    def source(self, token=False, internal=False):
        client = EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, include_internal=internal,
                                 contract_address=USDT if token else None, asset_symbol="USDT" if token else "ETH",
                                 token_decimals=6 if token else None,
                                 client=httpx.Client(transport=httpx.MockTransport(self.handler)))

        @contextmanager
        def open_(chain, asset):
            yield client
        return open_


def watch(eth, asset="ETH"):
    owner = ownership.owner_hash(KEY)
    return watchlist.create_watch(owner, W, "ethereum", asset,
                                  read_head=lambda chain, a: watchlist.chain_head(chain, a, source=eth.source()))


def cursor_of(w):
    with models.session() as s:
        return s.get(models.Watch, w.id).last_seen_block


def test_fifty_incoming_dust_records_after_a_cash_out_do_not_hide_it(store):
    eth = Etherscan()
    w = watch(eth)
    assert cursor_of(w) == HEAD  # starts at the head when it was set
    eth.add(200, W, BINANCE_14, 25 * 10**18)
    for i in range(50):
        eth.add(201 + i, "0x" + f"{i + 1:040x}", W, 1)
    alerts = watchlist.check_watch(w.id, source=eth.source())
    assert [(a["kind"], a["value"]) for a in alerts] == [("exchange", 25.0)]
    assert cursor_of(w) == 250


def test_fifty_zero_value_token_records_do_not_hide_a_usdt_cash_out(store):
    eth = Etherscan()
    w = watch(eth, "USDT")
    eth.add(200, W, BINANCE_14, 25_000 * 10**6, token=True)
    for i in range(50):
        eth.add(201 + i, W, "0x" + f"{i + 1:040x}", 0, token=True)
    alerts = watchlist.check_watch(w.id, source=eth.source(token=True))
    assert [(a["kind"], a["value"]) for a in alerts] == [("exchange", 25_000.0)]


def test_a_busy_wallet_with_sixty_deposits_after_its_sweep_still_alerts_the_sweep(store):
    eth = Etherscan()
    w = watch(eth)
    eth.add(150, W, BINANCE_14, 3 * 10**18)
    for i in range(60):
        eth.add(151 + i, "0x" + f"{i + 1:040x}", W, 10**17)
    kinds = [a["kind"] for a in watchlist.check_watch(w.id, source=eth.source())]
    assert kinds == ["exchange"]


def test_the_cursor_never_passes_a_block_it_did_not_read(store):
    eth = Etherscan()
    w = watch(eth)
    for i in range(200):  # four full pages of sends
        eth.add(101 + i, W, STRANGER, 10**18)
    first = watchlist.check_watch(w.id, source=eth.source())
    moved = [a for a in first if a["kind"] == "moved"]
    more = [a for a in first if a["kind"] == "more"]
    assert len(more) == 1 and "Check now again" in more[0]["message"]
    reached = cursor_of(w)
    assert reached < 300 and len(moved) == reached - 100
    second = watchlist.check_watch(w.id, source=eth.source())
    blocks = sorted(int(a["tx_hash"][2:62], 16) for a in first + second if a["kind"] == "moved")
    assert blocks == list(range(101, 301))  # every send once, none twice


def test_a_split_block_is_read_whole_on_the_next_page(store):
    eth = Etherscan()
    w = watch(eth)
    for i in range(48):
        eth.add(101 + i, W, STRANGER, 10**18)
    for n in range(3):  # three sends in block 149: the page boundary cuts it
        eth.add(149, W, STRANGER, 10**18, n=n)
    alerts = watchlist.check_watch(w.id, source=eth.source())
    hashes = [a["tx_hash"] for a in alerts if a["kind"] == "moved"]
    assert len(hashes) == 51 and len(set(hashes)) == 51


def test_a_check_on_a_dormant_wallet_costs_one_request(store):
    eth = Etherscan()
    w = watch(eth)
    eth.requests.clear()
    assert watchlist.check_watch(w.id, source=eth.source()) == []
    assert len(eth.requests) == 1 and eth.requests[0]["sort"] == "asc"
    assert eth.requests[0]["startblock"] == str(HEAD + 1)


def test_a_block_that_fills_a_page_on_its_own_is_read_whole(store):
    # One transaction can emit fifty token records into the wallet, and the
    # cash-out can sit in the same block after them: the page is that block
    # alone. It used to count as read, and the cash-out was never seen.
    eth = Etherscan()
    w = watch(eth, "USDT")
    for n in range(50):
        eth.add(200, "0x" + f"{n + 1:040x}", W, 1, token=True, n=n)
    eth.add(200, W, BINANCE_14, 25_000 * 10**6, token=True, n=99)
    alerts = watchlist.check_watch(w.id, source=eth.source(token=True))
    assert [(a["kind"], a["value"]) for a in alerts] == [("exchange", 25_000.0)]
    assert cursor_of(w) == 200


def test_a_watch_reads_blocks_above_one_hundred_million(store):
    # Arbitrum One passed block 99,999,999 in 2023: a read capped there asked
    # for an empty range from the head on, and the watch never saw anything.
    eth = Etherscan(head=400_000_000)
    w = watch(eth)
    assert cursor_of(w) == 400_000_000
    eth.add(400_000_050, W, BINANCE_14, 25 * 10**18)
    assert [a["kind"] for a in watchlist.check_watch(w.id, source=eth.source())] == ["exchange"]
    assert int(eth.requests[-1]["endblock"]) > 10**9


def test_a_block_too_full_to_read_whole_is_counted_as_read_and_said_so(store, monkeypatch):
    # More records in one block than a read of that block can return: the
    # cursor must move past it (or it would stall), and the watch must say
    # some may be missing rather than miss them quietly.
    from app import etherscan_client
    monkeypatch.setattr(etherscan_client, "WHOLE_BLOCK", 60)
    eth = Etherscan()
    w = watch(eth, "USDT")
    for n in range(70):
        eth.add(200, "0x" + f"{n + 1:040x}", W, 1, token=True, n=n)
    alerts = watchlist.check_watch(w.id, source=eth.source(token=True))
    assert [a["kind"] for a in alerts] == ["more"]
    assert "block 200" in alerts[0]["message"] and "may be missing" in alerts[0]["message"]
    assert cursor_of(w) == 200


def test_an_internal_cash_out_beside_a_signed_send_in_one_window_alerts_both(store):
    # The watched wallet (an address with code, e.g. EIP-7702 delegated) cashes
    # out 25 ETH as an internal transfer inside a relayer's transaction, and
    # signs one 1-wei send after it. Internal transfers were read only when
    # the signed list held no send, yet the cursor moved past both: the
    # cash-out was never alerted (8 Nov check).
    eth = Etherscan()
    w = watch(eth)
    eth.add(205, W, BINANCE_14, 25 * 10**18, internal=True)
    eth.add(210, W, STRANGER, 1)
    alerts = watchlist.check_watch(w.id, source=eth.source(internal=True))
    assert sorted((a["kind"], a["value"]) for a in alerts) == [("exchange", 25.0), ("moved", 1e-18)]
    assert cursor_of(w) == 210
    assert watchlist.check_watch(w.id, source=eth.source(internal=True)) == []


def test_internal_transfers_are_read_over_the_span_the_signed_read_covered(store):
    # Full signed pages stop the check inside the range; an internal send
    # above where it stopped must wait for the next check, not be skipped
    # or read twice.
    eth = Etherscan()
    w = watch(eth)
    for i in range(200):  # more sends than one check reads
        eth.add(101 + i, W, STRANGER, 10**18)
    eth.add(120, W, BINANCE_14, 25 * 10**18, internal=True, n=1)
    eth.add(290, W, BINANCE_14, 30 * 10**18, internal=True, n=1)
    first = watchlist.check_watch(w.id, source=eth.source(internal=True))
    assert cursor_of(w) < 290 and [a["value"] for a in first if a["kind"] == "exchange"] == [25.0]
    later = []
    for _ in range(3):
        later += watchlist.check_watch(w.id, source=eth.source(internal=True))
    assert [a["value"] for a in later if a["kind"] == "exchange"] == [30.0]
    moved = [a for a in first + later if a["kind"] == "moved"]
    assert len(moved) == 200 and len({a["tx_hash"] for a in moved}) == 200
