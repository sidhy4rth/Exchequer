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

Four independent brakes stop a busy wallet from blowing the trace up. Each is
a deliberate, documented investigative choice, not an arbitrary cap:

  1. max_depth (default 4)
        Laundering hops that matter happen close to the source. Past ~4 hops
        the graph is mostly unrelated exchange traffic.
  2. max_branches_per_node (default 10)
        We follow the highest-value destinations first. Laundering follows the
        money; dust and airdrop spam do not carry the stolen funds.
  3. min_value_native (default 0.001)
        Below this, a transfer is dust/spam rather than a real movement of
        value, and following it wastes API budget.
  4. is_terminal(address)
        Expansion stops at addresses we have already attributed -- in practice
        exchange hot wallets. Once funds reach an exchange the trace has found
        its answer, and those wallets have millions of transactions that would
        swamp the graph with noise.

The graph is a networkx.DiGraph. One edge per (sender -> recipient) pair,
carrying the aggregate value plus the individual transactions, so pattern
detection can look at the individual amounts later.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Iterable

import networkx as nx

from . import config
from .etherscan_client import (
    EtherscanClient,
    EtherscanError,
    Transaction,
    is_valid_address,
    normalize_address,
)

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
    min_value_native: float = 0.001


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
    warnings: list[str] = field(default_factory=list)

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


def build_trace_graph(
    seed_address: str,
    client: EtherscanClient,
    cfg: TraceConfig | None = None,
    is_terminal: Callable[[str], bool] | None = None,
    direction: str = OUTGOING,
) -> TraceResult:
    """Breadth-first trace of funds to or from `seed_address`.

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

    seed = normalize_address(seed_address)
    graph = nx.DiGraph()
    graph.add_node(seed, address=seed, depth=0, is_seed=True, expanded=False)

    result = TraceResult(graph=graph, seed=seed, direction=direction)

    queue: deque[tuple[str, int]] = deque([(seed, 0)])
    visited: set[str] = {seed}

    while queue:
        address, depth = queue.popleft()

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

        # Brake 2/3 budget: stop growing once the graph is big enough to read.
        if graph.number_of_nodes() >= cfg.max_nodes:
            result.note_truncation(f"node limit of {cfg.max_nodes} addresses reached")
            break

        try:
            transfers = fetch(address, limit=cfg.max_txs_per_address)
            result.api_calls += 1
        except EtherscanError as exc:
            # If we cannot even read the address the victim reported, we have
            # no trace at all. Surfacing that as a real error matters: an empty
            # graph would otherwise be indistinguishable from "this wallet
            # never sent anything", and the caller would draw the wrong
            # conclusion from an API outage or a rate limit.
            if depth == 0:
                raise
            # Deeper in, one unreachable address must not kill the whole trace:
            # record it and carry on with the partial picture we have.
            logger.warning("Could not fetch %s: %s", address, exc)
            result.warnings.append(f"Could not fetch transactions for {address}: {exc}")
            graph.nodes[address]["fetch_failed"] = True
            continue

        graph.nodes[address]["expanded"] = True
        result.addresses_expanded += 1
        result.depth_reached = max(result.depth_reached, depth)

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
        if len(branches) > cfg.max_branches_per_node:
            result.note_truncation(
                f"fan-out limit of {cfg.max_branches_per_node} counterparties "
                f"per address applied at {address[:10]}..."
            )
            branches = branches[: cfg.max_branches_per_node]

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
                # Keep the shortest known distance from the seed -- confidence
                # scoring rewards short paths, so this must not drift upward.
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

            graph.add_edge(
                source,
                target,
                value_native=total_value,
                tx_count=len(txs),
                first_seen=min(tx.timestamp for tx in txs),
                last_seen=max(tx.timestamp for tx in txs),
                # Individual transfers, newest first -- pattern detection reads these.
                transactions=[
                    {
                        "hash": tx.hash,
                        "value_native": tx.value_native,
                        "timestamp": tx.timestamp,
                        "block_number": tx.block_number,
                    }
                    for tx in sorted(txs, key=lambda t: t.timestamp, reverse=True)
                ],
            )

            if counterparty not in visited:
                visited.add(counterparty)
                queue.append((counterparty, depth + 1))

    _annotate_node_totals(graph)
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
            "total_in_native": round(data.get("total_in_native", 0.0), 6),
            "total_out_native": round(data.get("total_out_native", 0.0), 6),
            "activity_count": data.get("activity_count", 0),
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
            "first_seen": data.get("first_seen"),
            "last_seen": data.get("last_seen"),
            "flags": sorted(data.get("flags", [])),
        }
        for src, dst, data in graph.edges(data=True)
    ]
    return {"nodes": nodes, "edges": edges}
