"""Builds a directed transaction graph from a seed address via BFS.

The traversal runs in one of two directions, and which one is chosen is an
investigative decision, not a detail:

  outgoing  Follows where the reported address sent money. This is the
            cash-out question -- given a victim's report, which exchange did
            the funds reach.

  incoming  Follows who sent money *to* the reported address. This is the
            source question, and on a scammer's wallet it enumerates the
            addresses that funded it. Those senders are candidate victims of
            the same operation, which is how one report becomes a picture of
            a whole campaign.

Edges always point the way the money moved, whichever direction the walk
runs. A reverse trace therefore produces a graph whose arrows flow *into* the
seed, so every downstream consumer -- the pattern rules, the amount
arithmetic, the renderer -- keeps reading value flow the same way rather than
having to know which direction produced the graph.

Six independent brakes stop a busy wallet from blowing the trace up. Each is
a deliberate, documented investigative choice, not an arbitrary cap:

  1. max_depth (default 4)
        A cost limit, and an engineering judgement rather than a finding from
        the literature: each level multiplies the API calls, and in the demo
        traces the attributions were found within three hops. Meiklejohn et
        al. (2013) followed peeling chains for 100 hops, so a launderer who
        goes deeper is simply not followed -- the README says so.
  2. max_branches_per_node (default 10)
        We follow the highest-value destinations first. Laundering follows the
        money; dust and airdrop spam do not carry the stolen funds. A split
        into more parts than this hides the smallest, so with R5's flag on
        the rule becomes "every destination carrying at least
        branch_min_share of what the address sent", capped at
        max_branches_hard. Either way the value not followed is recorded in
        TraceResult.untraced and reported, never dropped silently.
  3. min_value_native (default 0.001)
        Below this, a transfer is dust/spam rather than a real movement of
        value, and following it wastes API budget.
  4. is_terminal(address)
        Expansion stops at addresses we have already attributed -- in practice
        exchange hot wallets. Once funds reach an exchange the trace has found
        its answer, and those wallets have millions of transactions that would
        swamp the graph with noise.

  5. max_contract_payout_recipients (default 3)
        Applies only to contracts, recognised by having no signed outgoing
        transfer. One paying out to more distinct addresses than this is a
        service (WETH, a pool, a router) and is not expanded: its payouts are
        other people's money. See TraceConfig for the measurement behind it.

  6. time_budget_seconds (default None -- off)
        A wall-clock cap the caller opts into. On the free tiers a busy wallet
        at four hops can take minutes; with a budget the walk stops expanding
        once the time is spent and reports what it has, marked truncated. It
        never changes what an address yields, only how much of the graph was
        reached before the clock ran out, and the report says so.

One more rule is about *when*, and it is a correctness rule rather than a
brake. Money cannot be forwarded before it arrives. When the walk reaches an
address at hop N, it knows the moment the traced funds landed there (the
earliest transfer on the edge that brought them), and only transfers leaving
at or after that moment can carry them. Anything the address sent earlier is
its own prior business and is left out of the graph. Walking backwards the
rule mirrors: only money that reached a sender at or before it paid the next
hop can have funded that payment. Without this rule a wallet's unrelated
history would be reported as the victim's money, which is exactly the kind
of claim this tool must never make. The seed itself is not windowed: the
trace starts there and does not know when the victim's funds arrived.

The graph is a networkx.DiGraph. One edge per (sender -> recipient) pair,
carrying the aggregate value plus the individual transactions, so pattern
detection can look at the individual amounts later.
"""
from __future__ import annotations

import contextlib
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator

import networkx as nx

from . import config, log_safety, progress
from .api_budget import BudgetSpent, Cancelled, TraceStopped, fresh_reads
from .etherscan_client import (
    EtherscanClient,
    Transaction,
    is_valid_address,
    normalize_address,
)
from .provider_errors import public_reason

logger = logging.getLogger(__name__)

# Which way the walk runs. See the module docstring.
OUTGOING = "outgoing"
INCOMING = "incoming"
DIRECTIONS = (OUTGOING, INCOMING)


class InvalidDirectionError(ValueError):
    """Raised when a caller asks for a traversal direction that does not exist."""


class InvalidAddressError(ValueError):
    """Raised when the submitted address is not a valid Ethereum address."""


@dataclass(frozen=True)
class TraceConfig:
    """Tunable limits for one traversal. Defaults come from the environment."""

    max_depth: int = config.TRACE_MAX_DEPTH
    max_nodes: int = config.TRACE_MAX_NODES
    max_txs_per_address: int = config.TRACE_MAX_TXS_PER_ADDRESS
    max_branches_per_node: int = 10
    # R5, taint-driven expansion: when set, brake 2 follows every counterparty
    # carrying at least this share of what the address sent, instead of the
    # top `max_branches_per_node`; `max_branches_hard` caps it for cost.
    branch_min_share: float | None = None
    max_branches_hard: int = 50
    min_value_native: float = 0.001
    # How many addresses at one depth may be in flight at once. This is not a
    # fifth brake: it changes how long the same requests take, never which
    # requests are made or what the resulting graph contains. The provider's
    # rate limit is still enforced by the client's own throttle.
    max_concurrent_fetches: int = config.TRACE_CONCURRENCY
    # Brake 5, for contracts only. An address with no signed outgoing transfer
    # but with contract-originated ones is a contract (a wallet cannot start an
    # internal transfer). A contract that pays out to more distinct addresses
    # than this is a service -- WETH, a liquidity pool, a router -- and its
    # payouts are other people's money, so it is not expanded. A multisig or
    # smart-contract wallet forwarding to a few recipients still is. Measured
    # on the README's flagship address at depth 4: without this, reading
    # internal transactions made the trace expand WETH and nine pools and
    # cost 249 requests instead of 41.
    max_contract_payout_recipients: int = 3
    # Brake 6. None means no cap: the walk runs until the other brakes stop
    # it. Checked between batches of fetches, so the overshoot is at most one
    # batch of concurrent requests.
    time_budget_seconds: float | None = None
    # The reported address is always read from the provider, never from the
    # response cache: it is the wallet whose newest moves the officer is
    # chasing, and a cached page of it could say "sent nothing" after the
    # money left. Its fresh answer replaces the cached one for later reads.
    fresh_seed: bool = True
    # Pages one read of an address may take when a full page held nothing the
    # walk could follow (zero-value or dust spam fills a page as well as real
    # transfers do): 5 x 200 is the 1,000 records Tron and NodeReal scan.
    # Only clients that read by page (Etherscan) page; each page is a request.
    max_pages_per_address: int = 5


@dataclass
class TraceResult:
    """Everything the traversal learned, ready for the rest of the pipeline."""

    graph: nx.DiGraph
    seed: str
    direction: str = OUTGOING
    depth_reached: int = 0
    addresses_expanded: int = 0
    api_calls: int = 0
    truncated: bool = False  # a limit stopped us before the graph was exhausted
    truncation_reasons: list[str] = field(default_factory=list)
    terminal_addresses: list[str] = field(default_factory=list)
    # Contracts recognised as services (see TraceConfig) and left unexpanded.
    service_contracts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Transfers left out because they happened on the wrong side of the moment
    # the traced funds passed through an address. See the module docstring.
    transfers_excluded_by_time: int = 0
    # Addresses reached but never expanded because the time budget ran out.
    addresses_unexpanded_by_time: int = 0
    # ... or because a provider's request budget refused their read.
    addresses_unexpanded_by_budget: int = 0
    seconds_elapsed: float = 0.0
    # Addresses whose transfers were fetched, including any read past the node
    # cap within the last batch (api_calls in a case counts the requests).
    addresses_read: int = 0
    # Busy wallets whose newest page did not reach the funds' arrival, so they
    # were also read from that block forward.
    read_from_arrival: list[str] = field(default_factory=list)
    # Value an address sent that the walk did not follow (brake 2), one entry
    # per address: {address, counterparties, value_native, share_of_outflow, rule}.
    untraced: list[dict[str, Any]] = field(default_factory=list)

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    def note_truncation(self, reason: str) -> None:
        self.truncated = True
        if reason not in self.truncation_reasons:
            self.truncation_reasons.append(reason)


def _choose_branches(
    branches: list[tuple[str, list[Transaction]]], address: str, cfg: TraceConfig, result: TraceResult,
) -> list[tuple[str, list[Transaction]]]:
    """Which counterparties of `address` the walk follows (brake 2), largest first.

    Top-N (the default): the `max_branches_per_node` largest. A launderer who
    splits the money into more parts than that hides the smallest ones.

    Share-based (R5, `branch_min_share` set): every counterparty that received
    at least that share of what `address` sent in the window, up to a hard
    safety cap of `max_branches_hard` so one wallet cannot spend the trace's
    API budget. Splitting 40 into twelve parts of 3.33 no longer hides any.

    Either way, what was not followed is recorded in `result.untraced` with
    its value, so a report states the untraced remainder instead of dropping
    it silently.
    """
    def value(item: tuple[str, list[Transaction]]) -> float:
        return sum(tx.value_native for tx in item[1])

    if cfg.branch_min_share is None:
        kept = branches[: cfg.max_branches_per_node]
        if len(branches) > len(kept):
            result.note_truncation(
                f"fan-out limit of {cfg.max_branches_per_node} counterparties "
                f"per address applied at {address[:10]}..."
            )
    else:
        total = sum(value(b) for b in branches)
        carrying = [b for b in branches if total > 0 and value(b) >= cfg.branch_min_share * total]
        kept = carrying[: cfg.max_branches_hard]
        if len(carrying) > len(kept):
            result.note_truncation(
                f"safety cap of {cfg.max_branches_hard} counterparties per address applied at "
                f"{address[:10]}..., each carrying at least {cfg.branch_min_share:.0%} of what it sent"
            )
    followed = {counterparty for counterparty, _ in kept}
    left = [b for b in branches if b[0] not in followed]
    if left:
        result.untraced.append({
            "address": address,
            "counterparties": len(left),
            "value_native": round(sum(value(b) for b in left), 6),
            "share_of_outflow": round(sum(value(b) for b in left) / (sum(value(b) for b in branches) or 1), 4),
            "rule": "top_n" if cfg.branch_min_share is None else "min_share",
        })
    return kept


def _aggregate_by_counterparty(
    txs: Iterable[Transaction], direction: str
) -> dict[str, list[Transaction]]:
    """Group transfers by the address at the far end.

    Which end that is depends on the direction of the walk: the recipient when
    following money out, the sender when following it back in.

    Grouping happens *before* the branch limit is applied, so an address that
    sent five separate transfers to the same recipient counts as one branch
    rather than five -- which is exactly the shape a peel chain produces.
    """
    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for tx in txs:
        counterparty = tx.to_address if direction == OUTGOING else tx.from_address
        if counterparty:
            grouped[counterparty].append(tx)
    return grouped


def _is_service_contract(
    transfers: list[Transaction], direction: str, cfg: TraceConfig
) -> bool:
    """True when `transfers` show a contract paying out to many addresses.

    Walking out, the address's own outflows are in hand: none signed and more
    than the cap of distinct recipients means a service. Walking back, the
    inflows are in hand instead, and the same shape reads as many distinct
    senders into a contract -- but an ordinary wallet also receives signed
    transfers from many people, so in that direction the test is only applied
    when every transfer in hand is contract-originated, which a wallet's
    inflows never all are.
    """
    if not transfers or any(not tx.internal for tx in transfers):
        return False
    far_end = {tx.to_address if direction == OUTGOING else tx.from_address for tx in transfers}
    return len(far_end - {None}) > cfg.max_contract_payout_recipients


class TimeBudgetExceeded(Exception):
    """Internal marker: the address was not fetched because the clock ran out."""


class _NotRead(Exception):
    """Internal marker: the address was not fetched because the walk had stopped (the node cap)."""


def _fetch_level(
    pending: list[tuple[str, int]],
    fetch: Callable[..., list[Transaction]],
    cfg: TraceConfig,
    deadline: float | None = None,
    stop: Callable[[], bool] | None = None,
    result: "TraceResult | None" = None,
) -> Iterator[tuple[list[Transaction], Exception | None]]:
    """Fetch every address at one depth together, preserving input order.

    The traversal used to make one request, wait for it, then make the next.
    Measured against Etherscan's free tier that costs about five seconds per
    address -- almost all of it waiting on the network, since the client's own
    throttle only spaces requests 0.34s apart. A fourteen-address trace took
    seventy-four seconds to do roughly four seconds of work.

    Addresses at the same depth have no dependency on each other, so they can
    be in flight together. The per-client throttle still applies and is
    lock-guarded, so the request *rate* is unchanged and the provider's limit
    is respected exactly as before -- what changes is that the waiting happens
    in parallel instead of end to end.

    Results come back positionally aligned with `pending` regardless of which
    request finished first, because the graph a trace produces must not depend
    on network timing: the same address must always yield the same graph.

    An exception is returned rather than raised so the caller can apply the
    rule it already had -- fatal at the seed, a warning deeper in -- with the
    depth in hand.

    The level is fetched one batch of `max_concurrent_fetches` at a time and
    yielded batch by batch, so the caller processes each batch before the
    next is sent. Before each batch `stop()` is asked (the node cap): once it
    says so, and once a `deadline` (a time.monotonic() instant) has passed,
    nothing more is read, and the addresses never fetched come back with
    _NotRead or TimeBudgetExceeded in place of a result. Reading the whole
    level first threw most of a wide trace's last level away (287 addresses
    read for 120 used). `result.addresses_read` counts what was read.
    """
    def counted() -> None:
        if result is not None:
            result.addresses_read += 1

    if len(pending) == 1:
        address, _ = pending[0]
        try:
            yield fetch(address, limit=cfg.max_txs_per_address), None
        except Exception as exc:  # noqa: BLE001 -- classified by the caller
            yield [], exc
        finally:
            counted()
            progress.report(level_read=1)
        return

    def one(index: int, address: str):
        try:
            return index, fetch(address, limit=cfg.max_txs_per_address), None
        except Exception as exc:  # noqa: BLE001 -- classified by the caller
            return index, [], exc

    read = 0
    workers = max(1, min(cfg.max_concurrent_fetches, len(pending)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trace") as pool:
        for start in range(0, len(pending), workers):
            unread: Exception | None = None
            if deadline is not None and time.monotonic() >= deadline:
                unread = TimeBudgetExceeded()
            elif stop is not None and stop():
                unread = _NotRead()
            if unread is not None:
                for _ in range(start, len(pending)):
                    yield [], unread
                return
            batch: list[tuple[list[Transaction], Exception | None]] = [([], None)] * len(pending[start:start + workers])
            futures = [pool.submit(one, index, address)
                       for index, (address, _depth) in enumerate(pending[start:start + workers])]
            for future in as_completed(futures):
                index, transfers, error = future.result()
                batch[index] = (transfers, error)
                read += 1
                counted()
                progress.report(level_read=read)
            yield from batch


def build_trace_graph(
    seed_address: str,
    client: EtherscanClient,
    cfg: TraceConfig | None = None,
    is_terminal: Callable[[str], bool] | None = None,
    direction: str = OUTGOING,
    seed_window: int | None = None,
    seed_window_block: int | None = None,
) -> TraceResult:
    """Breadth-first trace of funds to or from `seed_address`.

    `seed_window` applies the time rule to the seed itself: only transfers the
    seed made at or after that Unix time are followed. An address-only trace
    never windows its seed -- it cannot know when the victim's funds arrived --
    but two traces do know: a payment trace starts when the victim's first
    payment arrived, and a follow-on trace after a swap starts when the swap's
    output landed. Anything the wallet sent before then was not that money.

    `seed_window_block` is the block of that moment, when known (a payment
    trace). With it a busy seed whose newest page does not reach back to the
    payment is read again from that block forward, as any windowed address is.

    `direction` is OUTGOING (where the money went) or INCOMING (who sent it).
    See the module docstring for why that choice is investigative rather than
    cosmetic.

    `is_terminal` is injected rather than imported so this module stays
    independent of exchange matching; main.py passes in the exchange matcher.
    """
    if direction not in DIRECTIONS:
        raise InvalidDirectionError(
            f"'{direction}' is not a traversal direction. "
            f"Expected one of: {', '.join(DIRECTIONS)}."
        )
    if not is_valid_address(seed_address):
        raise InvalidAddressError(
            f"'{seed_address}' is not a valid Ethereum address "
            "(expected 0x followed by 40 hex characters)."
        )

    cfg = cfg or TraceConfig()
    is_terminal = is_terminal or (lambda _addr: False)
    fetch = (
        client.get_outgoing_transactions
        if direction == OUTGOING
        else client.get_incoming_transactions
    )

    # Walking out, a wallet whose newest page of transfers does not reach back
    # to when the traced funds arrived is read again from that block forward
    # (Etherscan; see get_outgoing_transactions_since), or from that time on
    # Tron. Without it a busy wallet hid exactly the transfers that moved the
    # funds on.
    since = getattr(client, "get_outgoing_transactions_since", None) if direction == OUTGOING else None
    # Tron's TRC-20 transfers carry no block number; there the read starts
    # from the arrival time instead (TronClient.get_outgoing_transactions_since_time).
    since_time = (getattr(client, "get_outgoing_transactions_since_time", None)
                  if direction == OUTGOING else None)
    page_info = getattr(client, "newest_page_info", None)
    # Whether a client's latest read of an address stopped at a record or scan
    # limit. Zero-value or dust spam fills those limits as well as real
    # transfers do, and is filtered out only after it has been counted.
    read_capped = getattr(client, "history_capped", None)
    newest_page = fetch

    def page_reach(address: str, transfers: list[Transaction], limit: int | None) -> tuple[bool, int | None]:
        """(older history went unread, time of the oldest record read).

        Asked of the client where it can say: Etherscan's page holds transfers
        in both directions, so a wallet that mostly receives -- a scam wallet
        collecting from many victims -- fills its page with inflows while
        returning only a few outflows, and counting those would call its
        history complete. Otherwise the transfers in hand are the page."""
        info = page_info(address) if page_info is not None else None
        if info is not None:
            return info
        capped = read_capped(address) if read_capped is not None else None
        full = capped if capped is not None else (limit is not None and len(transfers) >= limit)
        return full, min((tx.timestamp for tx in transfers), default=None)

    def later_capped(address: str, later: list[Transaction], limit: int) -> bool:
        capped = read_capped(address) if read_capped is not None else None
        return capped if capped is not None else len(later) >= limit

    paged = direction == OUTGOING and bool(getattr(client, "reads_pages", False))

    def past_spam(address: str, transfers: list[Transaction], arrived: int | None,
                  read: Callable[[int], list[Transaction]], capped: Callable[[list[Transaction]], bool],
                  ) -> list[Transaction]:
        """Read the next pages of the same query while the page was full and
        held nothing the walk could follow after `arrived`, up to
        max_pages_per_address. Spam must not be able to hide a cash-out
        behind one page; a page with a real outflow costs nothing extra."""
        page, latest = 1, transfers
        while (paged and page < cfg.max_pages_per_address and capped(latest)
               and not any(tx.value_native >= cfg.min_value_native and (arrived is None or tx.timestamp >= arrived)
                           for tx in transfers)
               and (deadline is None or time.monotonic() < deadline)):
            page += 1
            latest = read(page)
            known = {(tx.hash, tx.to_address, tx.value_wei) for tx in transfers}
            transfers = transfers + [tx for tx in latest if (tx.hash, tx.to_address, tx.value_wei) not in known]
        return transfers

    def fetch(address: str, limit: int | None = None) -> list[Transaction]:  # noqa: F811
        transfers = newest_page(address, limit=limit)
        start_block, arrived = window_block.get(address), window.get(address)
        if limit is None:
            return transfers
        if arrived is None:
            # Newest first, older pages while they held nothing to follow.
            transfers = past_spam(address, transfers, None, lambda p: newest_page(address, limit=limit, page=p),
                                  lambda page: page_reach(address, page, limit)[0])
        full, oldest = page_reach(address, transfers, limit)
        if arrived is None:
            # Read newest first and never from an arrival (the reported address
            # of an address-only trace): a full read left its older history unread.
            if full:
                capped_at[address] = "older"
            return transfers
        if not full:
            return transfers
        if oldest is not None and oldest <= arrived:
            if direction == INCOMING:
                capped_at[address] = "older"  # money it received before then still goes back further
            return transfers
        if since is not None and start_block is not None:
            def read_later() -> list[Transaction]:
                first = since(address, start_block, limit=limit)
                return past_spam(address, first, arrived,
                                 lambda p: since(address, start_block, limit=limit, page=p),
                                 lambda page: later_capped(address, page, limit))
        elif since_time is not None:
            def read_later() -> list[Transaction]:
                return since_time(address, arrived, limit=limit)
        else:
            # No way to read forward from the arrival: the transfers between it
            # and the oldest one read are missing, and the case must say so.
            not_read_back[address] = oldest
            return transfers
        later = read_later()
        if later_capped(address, later, limit):
            # The read from the arrival came back full too: what it sent between
            # that page's end and the newest page was not read.
            capped_at[address] = "later"
        known = {(tx.hash, tx.to_address, tx.value_wei) for tx in transfers}
        added = [tx for tx in later if (tx.hash, tx.to_address, tx.value_wei) not in known]
        read_from_arrival.add(address)
        return transfers + added

    read_from_arrival: set[str] = set()
    # Addresses whose read stopped at its record limit: which side went unread.
    capped_at: dict[str, str] = {}
    # Windowed addresses whose page stopped short of the arrival and could not
    # be read forward: address -> time of the oldest record read.
    not_read_back: dict[str, int | None] = {}
    seed = normalize_address(seed_address)
    graph = nx.DiGraph()
    graph.add_node(seed, address=seed, depth=0, is_seed=True, expanded=False)

    result = TraceResult(graph=graph, seed=seed, direction=direction)

    started = time.monotonic()
    deadline = started + cfg.time_budget_seconds if cfg.time_budget_seconds else None

    frontier: list[tuple[str, int]] = [(seed, 0)]
    visited: set[str] = {seed}
    # When the traced funds passed through each address: the earliest arrival
    # when walking out, the latest departure when walking back. Set when the
    # address is first reached, read when it is expanded one level later.
    window: dict[str, int] = {seed: seed_window} if seed_window else {}
    # The block of that arrival, for reading a busy wallet from it forward.
    window_block: dict[str, int] = {seed: seed_window_block} if seed_window and seed_window_block else {}

    # One level of the search at a time, so the addresses at a given depth can
    # be fetched together. See _fetch_level for why that matters.
    while frontier:
        pending: list[tuple[str, int]] = []
        for address, depth in frontier:
            # Brake 1: depth limit.
            if depth >= cfg.max_depth:
                result.note_truncation(f"depth limit of {cfg.max_depth} hops reached")
                continue

            # Brake 4: never expand an already-attributed address (exchange hot
            # wallet). The trace has reached its destination here.
            if depth > 0 and is_terminal(address):
                graph.nodes[address]["is_terminal"] = True
                if address not in result.terminal_addresses:
                    result.terminal_addresses.append(address)
                continue

            pending.append((address, depth))

        if not pending:
            break

        # Brake 2/3 budget: stop growing once the graph is big enough to read.
        if graph.number_of_nodes() >= cfg.max_nodes:
            result.note_truncation(f"node limit of {cfg.max_nodes} addresses reached")
            break

        # Brake 6: the clock. The seed is always fetched -- a budget so short
        # that not even the reported address was read would be no trace at
        # all -- so the check starts at the first level beyond it.
        if deadline is not None and pending[0][1] > 0 and time.monotonic() >= deadline:
            result.addresses_unexpanded_by_time += len(pending)
            result.note_truncation(
                f"time budget of {cfg.time_budget_seconds:.0f} s reached; "
                f"{len(pending)} reached address{'es' if len(pending) != 1 else ''} "
                "at the frontier were not expanded"
            )
            break

        progress.report(stage="walking", hop=pending[0][1] + 1, max_depth=cfg.max_depth,
                        level_size=len(pending), level_read=0,
                        addresses=graph.number_of_nodes())
        seed_level = pending[0][1] == 0
        # Read batch by batch as the loop below takes them, until the node cap.
        fetched = _fetch_level(pending, fetch, cfg, deadline=None if seed_level else deadline,
                               stop=lambda: graph.number_of_nodes() >= cfg.max_nodes, result=result)
        if seed_level:
            # One address, read now on this thread, so the context applies.
            with fresh_reads() if cfg.fresh_seed else contextlib.nullcontext():
                fetched = iter(list(fetched))
        next_frontier: list[tuple[str, int]] = []
        # Reads a request budget refused in this level, by the budget's reason.
        budget_stops: dict[str, int] = {}

        for (address, depth), (transfers, error) in zip(pending, fetched, strict=True):
            if graph.number_of_nodes() >= cfg.max_nodes:
                result.note_truncation(f"node limit of {cfg.max_nodes} addresses reached")
                break

            if isinstance(error, Cancelled):
                raise error  # a stop ends the whole trace, not just this branch
            if isinstance(error, BudgetSpent) and depth > 0:
                # The case's request budget (or the site's allowance) is spent:
                # reached, never read, like the clock below; the walk ends here.
                budget_stops[error.reason] = budget_stops.get(error.reason, 0) + 1
                result.addresses_unexpanded_by_budget += 1
                continue
            if isinstance(error, (TimeBudgetExceeded, TraceStopped)) and depth > 0:
                # Brake 6, mid-level: reached, never read. Not a failure of
                # the provider and not this address's fault; counted so the
                # report can say how much of the frontier the clock cut off.
                result.addresses_unexpanded_by_time += 1
                continue

            result.api_calls += 1

            if error is not None:
                # If we cannot even read the address the victim reported, we
                # have no trace at all. Surfacing that as a real error matters:
                # an empty graph would otherwise be indistinguishable from
                # "this wallet never sent anything", and the caller would draw
                # the wrong conclusion from an API outage or a rate limit.
                if depth == 0:
                    raise error
                # Deeper in, one unreachable address must not kill the whole
                # trace: record it and carry on with the partial picture. It
                # is also a truncation: everything past that address is
                # missing, and the report must say so rather than present the
                # partial graph as the complete picture.
                logger.warning("Could not fetch %s: %s", address, log_safety.redact(str(error)))
                result.warnings.append(
                    f"Could not fetch transactions for {address}: {public_reason(error)}"
                )
                result.note_truncation(
                    f"transactions of {address[:10]}... could not be fetched, so "
                    "the graph beyond it is missing"
                )
                graph.nodes[address]["fetch_failed"] = True
                continue

            graph.nodes[address]["expanded"] = True
            result.addresses_expanded += 1
            if address in capped_at:
                # Stated, never silent: spam can push the real cash-out past the limit.
                graph.nodes[address]["history_capped"] = True
                result.note_truncation(
                    f"history read limit at {address[:10]}...: the read stopped at its record limit, "
                    f"so {capped_at[address]} transfers were not read"
                )
            result.depth_reached = max(result.depth_reached, depth)

            # What this address does with money in general, from its complete
            # fetched outgoing history -- recorded before the time rule trims
            # the list, because deposit-address inference asks about the
            # wallet's behaviour, not about the traced funds.
            if direction == OUTGOING:
                outflows: dict[str, dict] = {}
                for tx in transfers:
                    if not tx.to_address or tx.to_address == address:  # a self-send is no outflow
                        continue
                    stats = outflows.setdefault(
                        tx.to_address, {"count": 0, "total": 0.0, "first": None, "last": None}
                    )
                    stats["count"] += 1
                    stats["total"] += tx.value_native
                    if tx.timestamp:
                        stats["first"] = min(stats["first"] or tx.timestamp, tx.timestamp)
                        stats["last"] = max(stats["last"] or tx.timestamp, tx.timestamp)
                graph.nodes[address]["outflows_by_counterparty"] = outflows
                # The provider returns at most this many transfers, so a list
                # this long means older history was not read.
                graph.nodes[address]["outgoing_history_capped"] = (
                    len(transfers) >= cfg.max_txs_per_address
                    or page_reach(address, transfers, cfg.max_txs_per_address)[0]
                )

            # Time rule: only transfers on the right side of the moment the
            # traced funds passed through this address can carry them.
            cutoff = window.get(address)
            if cutoff:
                before = len(transfers)
                if direction == OUTGOING:
                    transfers = [tx for tx in transfers if tx.timestamp >= cutoff]
                    graph.nodes[address]["window_start"] = cutoff
                else:
                    transfers = [tx for tx in transfers if tx.timestamp <= cutoff]
                    graph.nodes[address]["window_end"] = cutoff
                excluded = before - len(transfers)
                graph.nodes[address]["excluded_by_time"] = excluded
                result.transfers_excluded_by_time += excluded

            # A wallet paying itself moves nothing anywhere: no branch, no edge.
            # As a self-loop it took a fan-out slot, counted in the totals and
            # made the wallet's degrees 2, which hid a peel chain. Counted apart.
            own: list[Transaction] = []
            rest: list[Transaction] = []
            for tx in transfers:
                far_end = tx.to_address if direction == OUTGOING else tx.from_address
                (own if far_end == address else rest).append(tx)
            if own:
                transfers = rest
                graph.nodes[address]["self_transfer_count"] = len(own)
                graph.nodes[address]["self_transfer_value_native"] = round(sum(tx.value_native for tx in own), 6)

            # Brake 5: a service contract's payouts are not the traced money.
            # Only the reported address itself is exempt -- the trace starts
            # there whatever it is.
            if depth > 0 and _is_service_contract(transfers, direction, cfg):
                graph.nodes[address]["is_service_contract"] = True
                result.service_contracts.append(address)
                result.note_truncation(
                    f"{address[:10]}... is a contract that pays out to many addresses "
                    "(a pool, a wrapped-token contract or a router); its payouts are "
                    "not followed"
                )
                continue

            grouped = _aggregate_by_counterparty(transfers, direction)

            # Brake 3: drop dust before ranking, so tiny spam transfers cannot
            # crowd out a genuine movement of funds.
            branches = [
                (counterparty, txs)
                for counterparty, txs in grouped.items()
                if sum(tx.value_native for tx in txs) >= cfg.min_value_native
            ]

            # Brake 2: follow the money -- highest total value first.
            branches.sort(key=lambda item: sum(tx.value_native for tx in item[1]), reverse=True)
            branches = _choose_branches(branches, address, cfg, result)

            for counterparty, txs in branches:
                total_value = sum(tx.value_native for tx in txs)

                if counterparty not in graph:
                    graph.add_node(
                        counterparty,
                        address=counterparty,
                        depth=depth + 1,
                        is_seed=False,
                        expanded=False,
                    )
                else:
                    # Keep the shortest known distance from the seed: the walk's
                    # depth limit counts from it. (A match's hop count for the
                    # score is its widest route's instead; see scoring.widest_routes.)
                    graph.nodes[counterparty]["depth"] = min(
                        graph.nodes[counterparty].get("depth", depth + 1), depth + 1
                    )

                # The edge always points the way the money moved. Walking outward,
                # that is seed -> counterparty; walking back, it is counterparty ->
                # seed. Everything downstream reads value flow rather than walk
                # order because of this line.
                source, target = (
                    (address, counterparty) if direction == OUTGOING
                    else (counterparty, address)
                )

                # Record when the traced funds passed through the counterparty,
                # for the time rule when it is expanded. The seed is never
                # windowed: the trace starts there.
                if counterparty != seed:
                    stamps = [tx.timestamp for tx in txs if tx.timestamp > 0]
                    if stamps:
                        if direction == OUTGOING:
                            arrived = min(stamps)
                            window[counterparty] = min(
                                window.get(counterparty, arrived), arrived
                            )
                            blocks = [tx.block_number for tx in txs if tx.block_number > 0]
                            if blocks:
                                window_block[counterparty] = min(
                                    window_block.get(counterparty, min(blocks)), min(blocks)
                                )
                        else:
                            left = max(stamps)
                            window[counterparty] = max(
                                window.get(counterparty, left), left
                            )

                graph.add_edge(
                    source,
                    target,
                    value_native=total_value,
                    tx_count=len(txs),
                    # How many of those were moved by a contract call rather
                    # than a signed transfer. Reported, not treated differently.
                    internal_tx_count=sum(1 for tx in txs if tx.internal),
                    first_seen=min(tx.timestamp for tx in txs),
                    last_seen=max(tx.timestamp for tx in txs),
                    # Individual transfers, newest first -- pattern detection reads these.
                    transactions=[
                        {
                            "hash": tx.hash,
                            "value_native": tx.value_native,
                            "timestamp": tx.timestamp,
                            "block_number": tx.block_number,
                            "internal": tx.internal,
                        }
                        for tx in sorted(txs, key=lambda t: t.timestamp, reverse=True)
                    ],
                )

                if counterparty not in visited:
                    visited.add(counterparty)
                    next_frontier.append((counterparty, depth + 1))
        if hasattr(fetched, "close"):
            fetched.close()  # a level left at the node cap reads no further batch

        if budget_stops:
            for reason, count in sorted(budget_stops.items()):
                result.note_truncation(
                    f"{reason} reached; {count} reached address{'es' if count != 1 else ''} "
                    "were not expanded"
                )
            break

        # Anything the clock cut off mid-level is a truncation the report
        # must state; the frontier past it is also not walked.
        if result.addresses_unexpanded_by_time and deadline is not None and time.monotonic() >= deadline:
            result.note_truncation(
                f"time budget of {cfg.time_budget_seconds:.0f} s reached; "
                f"{result.addresses_unexpanded_by_time} reached address"
                f"{'es' if result.addresses_unexpanded_by_time != 1 else ''} "
                "were not expanded"
            )
            break

        frontier = next_frontier

    # Sorted: fetch runs in worker threads, and the reasons must come out in a fixed order.
    for address in sorted(not_read_back):
        if address in graph:
            graph.nodes[address]["history_capped"] = True
        oldest = not_read_back[address]
        upto = (datetime.fromtimestamp(oldest, tz=timezone.utc).strftime("%d %b %Y %H:%M UTC")
                if oldest else "the oldest one read")
        result.note_truncation(
            f"history read limit at {address[:10]}...: transfers between the funds' arrival "
            f"and {upto} were not read"
        )
    result.seconds_elapsed = round(time.monotonic() - started, 2)
    _annotate_node_totals(graph)
    result.read_from_arrival = sorted(read_from_arrival)
    for address in read_from_arrival:
        if address in graph:
            graph.nodes[address]["read_from_arrival"] = True
    return result


def _annotate_node_totals(graph: nx.DiGraph) -> None:
    """Attach per-address totals used by the pattern heuristics and the UI.

    `activity_count` counts only the transfers visible inside this trace. That
    is the honest number: it is what we actually observed, and the peel-chain
    heuristic is explicit that it means low activity *within the trace*.
    """
    for node in graph.nodes:
        in_edges = list(graph.in_edges(node, data=True))
        out_edges = list(graph.out_edges(node, data=True))

        total_in = sum(data["value_native"] for _, _, data in in_edges)
        total_out = sum(data["value_native"] for _, _, data in out_edges)
        tx_in = sum(data["tx_count"] for _, _, data in in_edges)
        tx_out = sum(data["tx_count"] for _, _, data in out_edges)

        graph.nodes[node].update(
            total_in_native=total_in,
            total_out_native=total_out,
            tx_in_count=tx_in,
            tx_out_count=tx_out,
            activity_count=tx_in + tx_out,
            in_degree=len(in_edges),
            out_degree=len(out_edges),
        )


def graph_to_dict(graph: nx.DiGraph) -> dict[str, list[dict]]:
    """Serialize the graph for the API / frontend.

    Per-transaction detail is deliberately dropped here: the frontend draws
    aggregate edges, and shipping every hash would bloat the response.
    """
    nodes = [
        {
            "id": node,
            "address": node,
            "depth": data.get("depth", 0),
            "is_seed": data.get("is_seed", False),
            "is_terminal": data.get("is_terminal", False),
            "label": data.get("label"),
            "exchange": data.get("exchange"),
            # Sanctions / mixer screening. Present on every node so the
            # frontend can style a flagged address without a second lookup;
            # None on the overwhelming majority that are not listed.
            "risk_category": data.get("risk_category"),
            "risk_entity": data.get("risk_entity"),
            "risk_label": data.get("risk_label"),
            # Set by deposit_inference when the address's outgoing history is
            # nothing but sweeps into one labelled exchange wallet.
            "inferred_exchange": data.get("inferred_exchange"),
            # A DEX router: funds sent here were swapped, not paid.
            "is_router": data.get("is_router", False),
            "router": data.get("router"),
            # A contract that pays out to many addresses; not expanded.
            "is_service_contract": data.get("is_service_contract", False),
            "total_in_native": round(data.get("total_in_native", 0.0), 6),
            "total_out_native": round(data.get("total_out_native", 0.0), 6),
            "activity_count": data.get("activity_count", 0),
            # The time rule's working for this address: from when (or until
            # when) its transfers were followed, and how many fell outside.
            "window_start": data.get("window_start"),
            "window_end": data.get("window_end"),
            "excluded_by_time": data.get("excluded_by_time", 0),
            # A read of this address stopped at its record limit (truncation_reasons says which side).
            "history_capped": data.get("history_capped", False),
            # Transfers the address made to itself: never an edge or a branch.
            "self_transfer_count": data.get("self_transfer_count", 0),
            "self_transfer_value_native": data.get("self_transfer_value_native", 0.0),
            "flags": sorted(data.get("flags", [])),
        }
        for node, data in graph.nodes(data=True)
    ]
    edges = [
        {
            "source": src,
            "target": dst,
            "value_native": round(data.get("value_native", 0.0), 6),
            "tx_count": data.get("tx_count", 0),
            "internal_tx_count": data.get("internal_tx_count", 0),
            "first_seen": data.get("first_seen"),
            "last_seen": data.get("last_seen"),
            "flags": sorted(data.get("flags", [])),
            # Present when the recipient is a swap router: what went in and,
            # if the receipt showed it, what came back to the sender.
            "swap": data.get("swap"),
        }
        for src, dst, data in graph.edges(data=True)
    ]
    return {"nodes": nodes, "edges": edges}
