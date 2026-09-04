"""Laundering-pattern heuristics.

Design rule for this module: every finding must be explainable to a
non-technical investigator, and every threshold must be visible, named, and
attached to the finding as evidence. A commercial tool says "suspicious, 0.87".
TraceChain says "these four wallets each appear 1-3 times, each forwarded
between 50% and 100% of what it received, and the amounts declined from
10.00 to 8.60 ETH -- that is a peel chain."

Nothing here is machine-learned. Every rule is a handful of arithmetic
comparisons you can re-check by hand from the transaction list, which is what
makes the output defensible if it ever reaches a courtroom.

Two patterns are implemented:

  PEEL CHAIN
    Stolen funds are walked through a series of throwaway wallets. At each
    hop a small amount is "peeled" off and the bulk moves on, so the chain
    shows steadily declining amounts through wallets with almost no other
    activity. Distinguishing feature vs. an ordinary transfer chain: the
    wallets are single-use and the money keeps most of its value at each hop.

  AMOUNT SPLIT (structuring)
    One address receives a sum and immediately fans it out into several
    smaller transfers, to stay under reporting thresholds and to multiply the
    paths an investigator must follow. Distinguishing feature vs. ordinary
    spending: nearly all of what came in goes straight back out, split across
    several recipients, none of which individually receives the whole amount.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import networkx as nx

logger = logging.getLogger(__name__)

PEEL_CHAIN = "peel_chain"
AMOUNT_SPLIT = "amount_split"


@dataclass(frozen=True)
class PatternConfig:
    """Every threshold the heuristics use, in one auditable place.

    These are investigative judgement calls, not tuned parameters. Each is
    justified in the comment beside it and is reported as evidence alongside
    any finding it produces.
    """

    # The chain's native currency symbol, used only when writing a finding's
    # human-readable description. It is configuration, not a threshold: the
    # arithmetic is identical on every EVM chain, but a description that says
    # "ETH" about a BNB transfer misstates the evidence it is reporting.
    native_symbol: str = "ETH"

    # -- peel chain --------------------------------------------------------
    # "Low activity" = the wallet appears in at most this many transfers within
    # the trace. The brief specifies 1-3 uses: a wallet created to pass money
    # along once, not a wallet somebody actually lives in.
    low_activity_max: int = 3
    # Minimum number of consecutive throwaway wallets before we call it a
    # chain. Two intermediates (a three-hop path) is the shortest sequence that
    # is a deliberate pattern rather than an ordinary A->B->C payment.
    min_chain_intermediates: int = 2
    # Each hop must forward at least this fraction of what it received. A peel
    # skims a little off the top; if a hop keeps half the money it is a split,
    # not a peel, and the amount-split rule should be the one to fire.
    min_hop_retention: float = 0.5
    # Amounts must not grow along the chain. A small tolerance absorbs gas
    # rounding and top-ups rather than treating them as a broken pattern.
    growth_tolerance: float = 0.02

    # -- amount split ------------------------------------------------------
    # Fewer than three recipients is ordinary behaviour (paying someone and
    # keeping change). Three or more is deliberate fragmentation.
    min_split_branches: int = 3
    # Of what came in, this fraction or more must go straight back out.
    # A wallet that keeps most of the money is a destination, not a splitter.
    min_forwarded_ratio: float = 0.5
    # Allow slightly more out than in (the wallet may hold a prior balance),
    # but not so much that we are looking at an unrelated funding source.
    max_forwarded_ratio: float = 1.10
    # No single outgoing transfer may carry more than this share of the total,
    # otherwise the money was forwarded whole with dust attached, not split.
    max_single_branch_share: float = 0.90


@dataclass
class PatternFinding:
    """One detected pattern, carrying the evidence that triggered it."""

    pattern: str
    addresses: list[str]
    description: str  # plain-English, safe to paste into a report
    evidence: dict[str, Any] = field(default_factory=dict)
    strength: float = 0.0  # 0-1, how cleanly the rule was satisfied

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _short(address: str) -> str:
    """Abbreviate an address for human-readable descriptions."""
    return f"{address[:8]}...{address[-4:]}"


# ---------------------------------------------------------------------------
# Peel chain
# ---------------------------------------------------------------------------
def _passthrough_nodes(
    graph: nx.DiGraph, cfg: PatternConfig, is_exchange: Callable[[str], bool]
) -> set[str]:
    """Wallets that only pass money along: one source in, one destination out,
    almost no other activity, and not an exchange.

    Exchange wallets are excluded explicitly: they are high-activity by nature
    and would never qualify, but stating it makes the rule self-documenting.
    """
    result = set()
    for node, data in graph.nodes(data=True):
        if data.get("is_seed") or data.get("is_exchange") or is_exchange(node):
            continue
        if graph.in_degree(node) != 1 or graph.out_degree(node) != 1:
            continue
        if data.get("activity_count", 0) > cfg.low_activity_max:
            continue
        result.add(node)
    return result


def _walk_chains(graph: nx.DiGraph, passthrough: set[str]) -> list[list[str]]:
    """Group consecutive pass-through wallets into maximal runs."""
    chains: list[list[str]] = []
    seen: set[str] = set()

    for node in passthrough:
        if node in seen:
            continue

        # Rewind to the first pass-through wallet in this run.
        start = node
        while True:
            preds = list(graph.predecessors(start))
            if len(preds) == 1 and preds[0] in passthrough and preds[0] != start:
                start = preds[0]
                if start == node:  # defensive: a cycle
                    break
            else:
                break

        # Walk forward collecting the run.
        run: list[str] = []
        cur = start
        while cur in passthrough and cur not in seen:
            seen.add(cur)
            run.append(cur)
            succs = list(graph.successors(cur))
            if not succs:
                break
            cur = succs[0]

        if run:
            chains.append(run)
    return chains


def detect_peel_chains(
    graph: nx.DiGraph,
    cfg: PatternConfig,
    is_exchange: Callable[[str], bool],
) -> list[PatternFinding]:
    """Find sequences of single-use wallets carrying steadily declining amounts.

    The rule, stated plainly:
      1. Take every wallet that has exactly one source and one destination in
         the trace and appears in at most `low_activity_max` transfers.
      2. Join consecutive such wallets into a run.
      3. Keep runs of at least `min_chain_intermediates` wallets.
      4. Require the amounts along the run to never grow (within tolerance),
         to end lower than they started, and for each hop to forward at least
         `min_hop_retention` of what it received.
    """
    findings: list[PatternFinding] = []
    passthrough = _passthrough_nodes(graph, cfg, is_exchange)

    for run in _walk_chains(graph, passthrough):
        if len(run) < cfg.min_chain_intermediates:
            continue

        # Extend the run to the wallet that fed it and the one it paid out to,
        # so we can see the full money path including entry and exit amounts.
        preds = list(graph.predecessors(run[0]))
        succs = list(graph.successors(run[-1]))
        if not preds or not succs:
            continue
        path = [preds[0]] + run + [succs[0]]

        # Amounts along each hop of the path.
        try:
            amounts = [
                graph.edges[path[i], path[i + 1]]["value_native"]
                for i in range(len(path) - 1)
            ]
        except KeyError:  # defensive: path broken by a concurrent edit
            continue

        if len(amounts) < 2 or amounts[0] <= 0:
            continue

        # Rule 4a: amounts must not grow along the chain.
        non_increasing = all(
            amounts[i + 1] <= amounts[i] * (1 + cfg.growth_tolerance)
            for i in range(len(amounts) - 1)
        )
        # Rule 4b: the chain must actually shed value -- that is the "peel".
        net_decline = amounts[-1] < amounts[0]
        # Rule 4c: each hop keeps most of the money. A hop that forwards only
        # a fraction is a split, and belongs to the other rule.
        retentions = [
            (amounts[i + 1] / amounts[i]) if amounts[i] > 0 else 0.0
            for i in range(len(amounts) - 1)
        ]
        holds_value = all(r >= cfg.min_hop_retention for r in retentions)

        if not (non_increasing and net_decline and holds_value):
            continue

        peeled = amounts[0] - amounts[-1]
        peeled_pct = (peeled / amounts[0]) * 100 if amounts[0] else 0.0

        # Strength: a longer chain of quieter wallets is a cleaner signal.
        # Capped at 1.0; deliberately simple so it can be explained.
        length_score = min(len(run) / 4.0, 1.0)
        quietness = 1.0 - (
            max(graph.nodes[n].get("activity_count", 0) for n in run)
            / (cfg.low_activity_max + 1)
        )
        strength = round(min(0.5 * length_score + 0.5 * max(quietness, 0.0), 1.0), 3)

        findings.append(
            PatternFinding(
                pattern=PEEL_CHAIN,
                addresses=path,
                description=(
                    f"Peel chain: {len(run)} single-use wallets "
                    f"({' -> '.join(_short(a) for a in run)}) forwarded funds in "
                    f"sequence from {_short(path[0])} to {_short(path[-1])}. "
                    f"The amount declined from {amounts[0]:.4f} {cfg.native_symbol} "
                    f"to {amounts[-1]:.4f} {cfg.native_symbol} "
                    f"({peeled_pct:.1f}% peeled off across "
                    f"{len(amounts)} hops), and each wallet forwarded at least "
                    f"{min(retentions) * 100:.0f}% of what it received."
                ),
                evidence={
                    "chain_length": len(run),
                    "path": path,
                    "hop_amounts_native": [round(a, 6) for a in amounts],
                    "hop_retention_ratios": [round(r, 4) for r in retentions],
                    "total_peeled_native": round(peeled, 6),
                    "peeled_percent": round(peeled_pct, 2),
                    "wallet_activity_counts": [
                        graph.nodes[n].get("activity_count", 0) for n in run
                    ],
                    "thresholds_applied": {
                        "low_activity_max": cfg.low_activity_max,
                        "min_chain_intermediates": cfg.min_chain_intermediates,
                        "min_hop_retention": cfg.min_hop_retention,
                        "growth_tolerance": cfg.growth_tolerance,
                    },
                },
                strength=strength,
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Amount split
# ---------------------------------------------------------------------------
def detect_amount_splits(
    graph: nx.DiGraph,
    cfg: PatternConfig,
    is_exchange: Callable[[str], bool],
) -> list[PatternFinding]:
    """Find addresses that fan an incoming sum out into several smaller ones.

    The rule, stated plainly:
      1. The address sent to at least `min_split_branches` distinct recipients.
      2. Between `min_forwarded_ratio` and `max_forwarded_ratio` of what it
         received went straight back out -- it forwarded, it did not keep.
      3. No single recipient took more than `max_single_branch_share` of the
         total, so the money was genuinely divided rather than passed along
         whole with dust attached.
      4. The address is not itself a known exchange. Exchanges fan out to
         thousands of customers by design; that is not structuring.
    """
    findings: list[PatternFinding] = []

    for node, data in graph.nodes(data=True):
        if data.get("is_exchange") or is_exchange(node):
            continue

        out_edges = list(graph.out_edges(node, data=True))
        # Rule 1: enough recipients to count as fragmentation.
        if len(out_edges) < cfg.min_split_branches:
            continue

        total_in = sum(
            edge.get("value_native", 0.0) for _, _, edge in graph.in_edges(node, data=True)
        )
        total_out = sum(edge.get("value_native", 0.0) for _, _, edge in out_edges)
        if total_in <= 0 or total_out <= 0:
            # The seed address has no observed inflow inside the trace, so the
            # forwarded-ratio test cannot be applied to it. Skipping keeps the
            # rule honest rather than guessing.
            continue

        # Rule 2: most of what arrived was passed on.
        forwarded_ratio = total_out / total_in
        if not (cfg.min_forwarded_ratio <= forwarded_ratio <= cfg.max_forwarded_ratio):
            continue

        amounts = sorted((edge.get("value_native", 0.0) for _, _, edge in out_edges), reverse=True)
        largest_share = amounts[0] / total_out if total_out else 1.0
        # Rule 3: genuinely divided, not forwarded whole.
        if largest_share > cfg.max_single_branch_share:
            continue

        # Strength: more branches and a more even division is a stronger
        # signal of deliberate structuring.
        branch_score = min(len(out_edges) / 5.0, 1.0)
        evenness = 1.0 - largest_share  # 0 = one branch took everything
        strength = round(min(0.5 * branch_score + 0.5 * evenness, 1.0), 3)

        findings.append(
            PatternFinding(
                pattern=AMOUNT_SPLIT,
                addresses=[node] + [dst for _, dst, _ in out_edges],
                description=(
                    f"Amount split: {_short(node)} received {total_in:.4f} "
                    f"{cfg.native_symbol} and forwarded {total_out:.4f} "
                    f"{cfg.native_symbol} ({forwarded_ratio * 100:.0f}% of "
                    f"the inflow) across {len(out_edges)} separate recipients, "
                    f"ranging from {amounts[-1]:.4f} to {amounts[0]:.4f} "
                    f"{cfg.native_symbol}. "
                    f"No single transfer carried more than "
                    f"{largest_share * 100:.0f}% of the total."
                ),
                evidence={
                    "address": node,
                    "branch_count": len(out_edges),
                    "total_in_native": round(total_in, 6),
                    "total_out_native": round(total_out, 6),
                    "forwarded_ratio": round(forwarded_ratio, 4),
                    "branch_amounts_native": [round(a, 6) for a in amounts],
                    "largest_branch_share": round(largest_share, 4),
                    "recipients": [dst for _, dst, _ in out_edges],
                    "thresholds_applied": {
                        "min_split_branches": cfg.min_split_branches,
                        "min_forwarded_ratio": cfg.min_forwarded_ratio,
                        "max_forwarded_ratio": cfg.max_forwarded_ratio,
                        "max_single_branch_share": cfg.max_single_branch_share,
                    },
                },
                strength=strength,
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def detect_patterns(
    graph: nx.DiGraph,
    cfg: PatternConfig | None = None,
    is_exchange: Callable[[str], bool] | None = None,
) -> list[PatternFinding]:
    """Run every heuristic and tag the graph with what was found.

    Nodes and edges involved in a pattern get a `flags` set, which the frontend
    uses to highlight them. Returns the findings sorted strongest-first.
    """
    cfg = cfg or PatternConfig()
    is_exchange = is_exchange or (lambda _a: False)

    findings = detect_peel_chains(graph, cfg, is_exchange)
    findings += detect_amount_splits(graph, cfg, is_exchange)

    # Tag the graph so the UI can highlight exactly what the rules matched.
    for finding in findings:
        for address in finding.addresses:
            if address in graph.nodes:
                graph.nodes[address].setdefault("flags", set()).add(finding.pattern)
        if finding.pattern == PEEL_CHAIN:
            path = finding.evidence.get("path", [])
            for i in range(len(path) - 1):
                if graph.has_edge(path[i], path[i + 1]):
                    graph.edges[path[i], path[i + 1]].setdefault("flags", set()).add(PEEL_CHAIN)
        elif finding.pattern == AMOUNT_SPLIT:
            source = finding.evidence.get("address")
            for _, dst in graph.out_edges(source):
                graph.edges[source, dst].setdefault("flags", set()).add(AMOUNT_SPLIT)

    findings.sort(key=lambda f: f.strength, reverse=True)
    return findings


def flag_names(findings: list[PatternFinding]) -> list[str]:
    """Distinct pattern names, for the API's `flags` field."""
    return sorted({f.pattern for f in findings})
