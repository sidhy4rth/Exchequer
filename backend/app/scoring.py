"""Confidence scoring for an attribution.

The score answers one question: how much weight should an investigator put on
"these funds were cashed out at this exchange"? It is NOT a measure of how
criminal the activity looks.

Three components, exactly as specified, each independently explainable and each
reported with its own raw value, weight and contribution so the final number
can always be taken apart:

  HOP PROXIMITY (40%)
      Fewer hops between the victim's address and the exchange means less room
      for the trail to have been broken by an intermediary we cannot see.
      A direct deposit is near-certain; four hops of separation is not.

  AMOUNT CORRELATION (35%)
      How much of the money that left the victim's address actually arrived at
      the exchange along this path. If 95% of the value survived the journey,
      it is very likely the same money. If 2% did, we may be following an
      incidental transfer that happens to end at an exchange.

  MATCH DIRECTNESS (25%)
      Whether we landed on a known exchange hot wallet by exact match, or only
      inferred the destination. An exact match against a labelled address is
      the strongest evidence this tool can produce.

A deliberately conservative choice: no component can rescue a case with no
exchange match. If nothing matched, the score is 0.0 and the verdict is
"no attribution", not a low-but-nonzero number that might get over-read.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import networkx as nx

from .exchange_matcher import ExchangeMatch
from .graph_builder import OUTGOING
from .pattern_detection import PatternFinding

logger = logging.getLogger(__name__)

# Component weights. They sum to 1.0; the assertion below keeps that true if
# anyone edits them.
WEIGHT_HOP_PROXIMITY = 0.40
WEIGHT_AMOUNT_CORRELATION = 0.35
WEIGHT_MATCH_DIRECTNESS = 0.25
assert abs(WEIGHT_HOP_PROXIMITY + WEIGHT_AMOUNT_CORRELATION + WEIGHT_MATCH_DIRECTNESS - 1.0) < 1e-9

# Bands used in the report so a reader is not left interpreting a bare decimal.
BAND_THRESHOLDS = ((0.75, "high"), (0.50, "moderate"), (0.25, "low"))


@dataclass
class ScoreComponent:
    """One weighted input to the confidence score."""

    name: str
    raw_value: float  # 0-1 before weighting
    weight: float
    explanation: str

    @property
    def contribution(self) -> float:
        return self.raw_value * self.weight

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "raw_value": round(self.raw_value, 4),
            "weight": self.weight,
            "contribution": round(self.contribution, 4),
            "explanation": self.explanation,
        }


@dataclass
class ConfidenceScore:
    """The final score plus the full working behind it.

    `score` is None when no exchange was attributed. That is deliberate and is
    not the same as zero: the score measures how confident we are *in an
    attribution*, so with nothing attributed there is no score to state. A 0.0
    would read as "we are certain this is worthless", which misdescribes a
    trace that may have mapped the network and found laundering patterns
    perfectly well.
    """

    score: float | None
    band: str
    components: list[ScoreComponent] = field(default_factory=list)
    summary: str = ""
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "band": self.band,
            "summary": self.summary,
            "components": [c.to_dict() for c in self.components],
            "caveats": self.caveats,
        }


def _band(score: float) -> str:
    for threshold, name in BAND_THRESHOLDS:
        if score >= threshold:
            return name
    return "very low"


def _hop_proximity(depth: int, max_depth: int, direction: str = OUTGOING) -> ScoreComponent:
    """Linear decay with distance from the victim's address.

    depth 1 scores 1.0 (a direct deposit to the exchange) and each further hop
    costs an equal share, reaching 0 at one hop beyond the traversal limit.
    Linear rather than exponential so the penalty stays easy to explain.
    """
    span = max(max_depth, 1)
    raw = max(0.0, min(1.0, 1.0 - (depth - 1) / span))
    if depth <= 1 and direction == OUTGOING:
        explanation = (
            "The exchange wallet received funds directly from the reported "
            "address, with no intermediary."
        )
    elif depth <= 1:
        explanation = (
            "The exchange wallet sent funds directly to the reported address, "
            "with no intermediary."
        )
    else:
        explanation = (
            f"The exchange wallet is {depth} hops from the reported address. "
            f"Each hop adds a wallet we cannot independently account for, so "
            f"confidence decays with distance (limit: {max_depth} hops)."
        )
    return ScoreComponent("hop_proximity", raw, WEIGHT_HOP_PROXIMITY, explanation)


def principal_path(graph: nx.DiGraph, source: str, destination: str) -> list[str]:
    """The route the attribution is read along, chosen the same way every time.

    Among the shortest paths from `source` to `destination`, the one whose
    narrowest hop carried the most value -- the path that could have moved the
    most of the traced funds. networkx's own shortest_path picks one of several
    equal-length routes by insertion order, which is arbitrary from an
    investigator's point of view: a dust transfer that happens to reach the
    same exchange could be the path the score and the report were read from.
    Ties are broken by address order so the choice is reproducible.

    Raises the same exceptions as nx.shortest_path when there is no route.
    """
    def bottleneck(path: list[str]) -> float:
        return min(
            graph.edges[path[i], path[i + 1]].get("value_native", 0.0)
            for i in range(len(path) - 1)
        ) if len(path) > 1 else 0.0

    paths = list(nx.all_shortest_paths(graph, source, destination))
    return min(paths, key=lambda p: (-bottleneck(p), p))


def _amount_correlation(
    graph: nx.DiGraph, seed: str, exchange_address: str, native_symbol: str = "ETH",
    direction: str = OUTGOING,
) -> ScoreComponent:
    """Fraction of the value that survived the route between seed and exchange.

    Measured along the principal path (see `principal_path`), comparing the
    amount on the first hop with the amount on the final hop. A high ratio
    means the money largely survived the journey intact and is very likely
    the same money.

    The path is read the way the money moved, which depends on the direction
    of the trace: seed -> exchange when following funds out, exchange -> seed
    when following them back. Taking the fixed seed -> exchange path in both
    cases would find no route on a reverse trace and silently score every one
    of them at the neutral 0.5 below.
    """
    if seed == exchange_address:
        return ScoreComponent(
            "amount_correlation",
            1.0,
            WEIGHT_AMOUNT_CORRELATION,
            "The reported address is itself a labelled exchange wallet.",
        )

    source, destination = (
        (seed, exchange_address) if direction == OUTGOING else (exchange_address, seed)
    )
    try:
        path = principal_path(graph, source, destination)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        # Defensive: the matcher found the address in the graph, so a path
        # should exist. Score neutrally rather than inventing a number.
        return ScoreComponent(
            "amount_correlation",
            0.5,
            WEIGHT_AMOUNT_CORRELATION,
            "No directed path from the reported address to the exchange wallet "
            "was available, so amount correlation could not be measured. "
            "Scored neutrally.",
        )

    amounts = [
        graph.edges[path[i], path[i + 1]].get("value_native", 0.0)
        for i in range(len(path) - 1)
    ]
    if not amounts or amounts[0] <= 0:
        return ScoreComponent(
            "amount_correlation",
            0.0,
            WEIGHT_AMOUNT_CORRELATION,
            "No value was observed leaving the reported address along this path.",
        )

    sent = amounts[0]
    arrived = amounts[-1]
    raw = max(0.0, min(1.0, arrived / sent))

    if direction == OUTGOING:
        explanation = (
            f"{arrived:.4f} {native_symbol} reached the exchange out of "
            f"{sent:.4f} {native_symbol} that left the reported address on this "
            f"path ({raw * 100:.1f}% of the value survived the route). A high "
            f"proportion indicates the same funds; a low one may indicate an "
            f"unrelated transfer that merely ends at an exchange."
        )
    else:
        explanation = (
            f"{arrived:.4f} {native_symbol} reached the reported address out of "
            f"{sent:.4f} {native_symbol} that left the exchange wallet on this "
            f"path ({raw * 100:.1f}% of the value survived the route). A high "
            f"proportion indicates the reported address was funded from that "
            f"withdrawal; a low one may indicate an unrelated transfer that "
            f"merely happens to originate at an exchange."
        )

    return ScoreComponent(
        "amount_correlation", raw, WEIGHT_AMOUNT_CORRELATION, explanation
    )


def _match_directness(match: ExchangeMatch) -> ScoreComponent:
    """Exact hot-wallet match vs. a weaker attribution.

    Today every match is an exact lookup against the labelled database, so this
    scores 1.0. The component exists as a distinct, weighted input because the
    upgrade path (clustering, deposit-address inference) will produce weaker
    attributions, and those must score lower rather than being silently blended
    in with exact matches.
    """
    if match.wallet_type in ("hot_wallet", "cold_wallet"):
        raw = 1.0
        explanation = (
            f"Exact match: {match.address} is a labelled {match.exchange} "
            f"{match.wallet_type.replace('_', ' ')} ({match.label}) in the "
            f"attribution database."
        )
    else:
        # Labelled, but the wallet's role is not recorded -- slightly weaker.
        raw = 0.8
        explanation = (
            f"Exact address match against {match.exchange} ({match.label}), but "
            f"the wallet's role is not recorded in the label database."
        )
    return ScoreComponent("match_directness", raw, WEIGHT_MATCH_DIRECTNESS, explanation)


def score_case(
    graph: nx.DiGraph,
    seed: str,
    primary_match: ExchangeMatch | None,
    findings: list[PatternFinding] | None = None,
    max_depth: int = 4,
    truncated: bool = False,
    native_symbol: str = "ETH",
    direction: str = OUTGOING,
) -> ConfidenceScore:
    """Compute the confidence score for one traced case.

    On a reverse trace the three components measure the same quantities, but
    the claim they support is the mirror image: not "the funds reached this
    exchange" but "the funds came from it".
    """
    findings = findings or []

    if primary_match is None:
        return ConfidenceScore(
            score=None,
            band="no attribution",
            components=[],
            summary=(
                "No address in the trace matched a known exchange wallet, so no "
                "cash-out point could be attributed. This is not evidence that "
                "the funds were not cashed out -- it may mean the exchange used "
                "is absent from the label database, or that the funds have not "
                "yet reached one within the traced depth."
            ) if direction == OUTGOING else (
                "No address upstream of the reported address matched a known "
                "exchange wallet, so the funds could not be traced back to a "
                "point of purchase or withdrawal. The senders found are still "
                "the substantive result of a reverse trace."
            ),
            caveats=_caveats(findings, truncated, matched=False, asset=native_symbol),
        )

    components = [
        _hop_proximity(primary_match.depth, max_depth, direction),
        _amount_correlation(graph, seed, primary_match.address, native_symbol, direction),
        _match_directness(primary_match),
    ]
    score = round(sum(c.contribution for c in components), 4)
    band = _band(score)

    hops = f"{primary_match.depth} hop{'s' if primary_match.depth != 1 else ''}"
    if direction == OUTGOING:
        claim = (
            f"funds from the reported address reached {primary_match.exchange} "
            f"at {primary_match.address}, {hops} from the source"
        )
    else:
        claim = (
            f"funds reaching the reported address came from "
            f"{primary_match.exchange} at {primary_match.address}, {hops} "
            f"upstream"
        )
    summary = f"{band.capitalize()} confidence ({score:.2f}) that {claim}."

    return ConfidenceScore(
        score=score,
        band=band,
        components=components,
        summary=summary,
        caveats=_caveats(findings, truncated, matched=True, asset=native_symbol),
    )


def _caveats(
    findings: list[PatternFinding], truncated: bool, matched: bool, asset: str = "ETH"
) -> list[str]:
    """Limitations a reader must know before acting on the score.

    These deliberately do not change the number. They are stated separately so
    the score stays a simple, reproducible function of its three inputs, and so
    an investigator is never quietly nudged by a hidden adjustment.
    """
    caveats: list[str] = []

    if findings:
        patterns = sorted({f.pattern.replace("_", " ") for f in findings})
        caveats.append(
            f"Deliberate obfuscation was detected along the trace ({', '.join(patterns)}). "
            "This supports the conclusion that the movement was intentional, but it also "
            "means intermediate wallets may hide additional splits not visible here."
        )
    if truncated:
        caveats.append(
            "The traversal hit a depth, fan-out or size limit, so the graph is a "
            "sample of the address's activity rather than a complete picture. "
            "Funds may also have reached other exchanges along paths not expanded."
        )
    if matched:
        caveats.append(
            "An exchange match identifies where funds arrived, not who controls the "
            "receiving account. Only the exchange can link a deposit address to a "
            "customer identity, via a lawful request."
        )
    caveats.append(
        f"Only direct {asset} transfers were followed. Value that moved as a "
        "different asset (for example after a swap into another token), "
        "through an internal contract call, or across a bridge to another "
        "chain is not covered."
    )
    return caveats
