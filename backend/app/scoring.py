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

import heapq
import logging
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from .exchange_matcher import INFERRED_DEPOSIT, ExchangeMatch
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


# Hop proximity is scored against this fixed distance (the default trace
# depth), never the depth a request asked for: asking for a deeper trace must
# not raise the score of the same path (audit r1-attribution-integrity-8).
PROXIMITY_REFERENCE_HOPS = 4


def _hop_proximity(depth: int, direction: str = OUTGOING, offset: int = 0) -> ScoreComponent:
    """Linear decay with distance from the victim's address.

    depth 1 scores 1.0 (a direct deposit to the exchange) and each further hop
    costs an equal share of PROXIMITY_REFERENCE_HOPS, reaching 0 at one hop
    beyond it. Linear rather than exponential so the penalty stays easy to
    explain. `offset` is the hops before this trace began: a follow-on after a
    swap starts at the swapping wallet, which may sit hops from the reported
    address.
    """
    hops = depth + offset
    raw = max(0.0, min(1.0, 1.0 - (hops - 1) / PROXIMITY_REFERENCE_HOPS))
    if hops <= 1 and direction == OUTGOING:
        explanation = (
            "The exchange wallet received funds directly from the reported "
            "address, with no intermediary."
        )
    elif hops <= 1:
        explanation = (
            "The exchange wallet sent funds directly to the reported address, "
            "with no intermediary."
        )
    else:
        after = f" ({depth} after the swap)" if offset else ""
        explanation = (
            f"The exchange wallet is {hops} hops from the reported address{after}. "
            f"Each hop adds a wallet we cannot independently account for, so "
            f"confidence decays with distance, scored against a fixed reference of "
            f"{PROXIMITY_REFERENCE_HOPS} hops ({PROXIMITY_REFERENCE_HOPS + 1} or more score 0)."
        )
    return ScoreComponent("hop_proximity", raw, WEIGHT_HOP_PROXIMITY, explanation)


def principal_path(graph: nx.DiGraph, source: str, destination: str) -> list[str]:
    """The route the attribution is read along, chosen the same way every time.

    The widest route from `source` to `destination`: the one whose narrowest
    hop carried the most value -- the route that could have moved the most of
    the traced funds -- with ties going to fewer hops, then to address order.
    It used to be the widest among the *shortest* routes only, so a dust
    transfer that happened to reach the same exchange in fewer hops could be
    the path the pro-rata estimate, the score and the report were read from;
    and listing every shortest route grew exponentially on a lattice of
    wallets built to do that. This is O(E log V) and agrees with
    `reach_bottlenecks`.

    Raises the same exceptions as nx.shortest_path when there is no route.
    """
    if destination not in graph:
        raise nx.NodeNotFound(f"{destination} is not in the graph")
    best, prev = _widest(graph, source, forward=True)
    if destination == source:
        return [source]
    if destination not in best:
        raise nx.NetworkXNoPath(f"no path from {source} to {destination}")
    path = [destination]
    while path[-1] != source:
        path.append(prev[path[-1]])
    return path[::-1]

def _widest(graph: nx.DiGraph, source: str, forward: bool = True,
            ) -> tuple[dict[str, float], dict[str, str]]:
    """Widest paths from `source`: for every address, the most value that
    could have reached it along any route (the largest narrowest hop), and the
    address before it on that route. Ties go to fewer hops, then to address
    order, so the route is reproducible. Dijkstra on the bottleneck: O(E log V).

    `forward=False` reads incoming edges -- money moving towards `source`, as
    on a reverse trace -- taking each edge's value from the farther address to
    the nearer one."""
    if source not in graph:
        raise nx.NodeNotFound(f"{source} is not in the graph")
    step = graph.successors if forward else graph.predecessors

    def value(near: str, far: str) -> float:
        edge = graph.edges[near, far] if forward else graph.edges[far, near]
        return float(edge.get("value_native", 0.0))

    best: dict[str, float] = {source: float("inf")}
    hops: dict[str, int] = {source: 0}
    prev: dict[str, str] = {}
    done: set[str] = set()
    heap: list[tuple[float, int, str]] = [(-float("inf"), 0, source)]
    while heap:
        _, h, near = heapq.heappop(heap)
        if near in done:
            continue
        done.add(near)
        for far in step(near):
            if far in done:
                continue
            width = min(best[near], value(near, far))
            key = (-width, h + 1, near)
            if far not in best or key < (-best[far], hops[far], prev.get(far, "")):
                best[far], hops[far], prev[far] = width, h + 1, near
                heapq.heappush(heap, (-width, h + 1, far))
    best.pop(source, None)
    return best, prev


def reach_bottlenecks(graph: nx.DiGraph, source: str, direction: str = OUTGOING) -> dict[str, float]:
    """For every address, the most value that could have reached it from
    `source`: the narrowest hop of its widest route (see `_widest`). A route
    through a dust transfer can never carry more than the dust, so a decoy
    near the source cannot outweigh the route the money took, however short
    the decoy's route is. On a reverse trace the routes run towards `source`.
    `source` itself is not in the result."""
    if source not in graph:
        return {}
    return _widest(graph, source, forward=direction == OUTGOING)[0]


def seed_outflow(graph: nx.DiGraph, seed: str, direction: str = OUTGOING,
                 untraced: list[dict[str, Any]] | None = None) -> float:
    """What the reported wallet sent (or, on a reverse trace, received), as
    the trace saw it: its edges, plus value it sent to counterparties the
    trace did not follow, minus value that came back to it from wallets the
    trace did follow (a round trip must not count twice). Never below its
    largest single transfer.
    """
    if seed not in graph:
        return 0.0
    if direction == OUTGOING:
        out = [d.get("value_native", 0.0) for _, _, d in graph.out_edges(seed, data=True)]
        back = sum(d.get("value_native", 0.0) for _, _, d in graph.in_edges(seed, data=True))
    else:
        out = [d.get("value_native", 0.0) for _, _, d in graph.in_edges(seed, data=True)]
        back = sum(d.get("value_native", 0.0) for _, _, d in graph.out_edges(seed, data=True))
    left = sum(u.get("value_native", 0.0) for u in (untraced or []) if u.get("address") == seed)
    if not out:
        return float(left)
    return max(max(out), sum(out) + left - back)


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


def _prorata_component(prorata: dict[str, Any], native_symbol: str) -> ScoreComponent:
    """Amount correlation measured pro-rata (see prorata.py)."""
    sent, est, ratio = prorata["sent"], prorata["estimated"], prorata["ratio"]
    lines = [
        f"Pro-rata estimate: about {est:,.4f} of the {sent:,.4f} {native_symbol} that left the "
        f"reported address on this path likely reached the exchange ({ratio * 100:.1f}%)."
    ]
    for h in prorata.get("hops") or []:
        lines.append(
            f"At {h['address']} the traced funds were {h['victim_share'] * 100:.1f}% of the "
            f"{h['received_in_window']:,.4f} {native_symbol} it received before sending on, so "
            f"{h['victim_on']:,.4f} of the {h['sent_on']:,.4f} it passed along is counted as theirs."
        )
    arrived = prorata.get("arrived_total")
    if arrived and arrived > est * 1.05:
        lines.append(
            f"{arrived:,.4f} {native_symbol} reached the exchange along this path in total; the rest "
            f"came from other sources."
        )
    return ScoreComponent("amount_correlation", ratio, WEIGHT_AMOUNT_CORRELATION, " ".join(lines))


def _not_estimated(prorata: dict[str, Any], materiality: dict[str, Any] | None,
                   native_symbol: str) -> ScoreComponent:
    """Pro-rata could not be read along the path, so the amount earns nothing.

    The fallback used to be the last hop over the first, capped at 1, which
    scores the most diluted paths highest: a read cut short by a busy wallet
    scored above a complete one on the same path (audit
    r2-g2-documented-claims-vs-code-7-2). With no credit, a less complete
    read can never score above a complete one.
    """
    lines = [f"Not estimated: {prorata.get('reason') or 'the wallets on the path could not be read'}."]
    if materiality and materiality.get("denominator") and materiality.get("primary_reach") is not None:
        reach, of = materiality["primary_reach"], materiality["denominator"]
        lines.append(f"At most {reach:,.4f} of the {of:,.4f} {native_symbol} ({min(1.0, reach / of) * 100:.1f}%) "
                     "could have reached it along this route;")
    else:
        lines.append("Whatever reached it along this route may include other people's money;")
    lines.append("no credit is given for an amount that could not be measured.")
    return ScoreComponent("amount_correlation", 0.0, WEIGHT_AMOUNT_CORRELATION, " ".join(lines))


def _match_directness(match: ExchangeMatch) -> ScoreComponent:
    """Exact hot-wallet match vs. a weaker attribution.

    An exact lookup against the labelled database scores 1.0. An inferred
    deposit address (deposit_inference.py) scores 0.5, so at the same distance
    it always scores 0.125 below a labelled hot wallet. It sits one hop closer
    than the hot wallet it sweeps to, which hop proximity rewards by 0.1 at
    the default depth, so against that particular wallet the two come out
    within a few hundredths of each other -- the report shows both.
    """
    if match.wallet_type == INFERRED_DEPOSIT:
        e = match.evidence or {}
        return ScoreComponent(
            "match_directness",
            0.5,
            WEIGHT_MATCH_DIRECTNESS,
            f"Inferred, not labelled: {match.address} is not in the attribution "
            f"database. It is called a probable {match.exchange} deposit address "
            f"because every one of its {e.get('sweep_count')} outgoing transfers "
            f"went to the labelled {match.exchange} wallet "
            f"{e.get('sweep_destination')} and nowhere else. Only "
            f"{match.exchange} can confirm this.",
        )
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
    internal_transfers_read: bool = False,
    prorata: dict[str, Any] | None = None,
    materiality: dict[str, Any] | None = None,
    depth_offset: int = 0,
) -> ConfidenceScore:
    """Compute the confidence score for one traced case.

    `max_depth` is kept for callers but no longer moves the score: hop
    proximity is measured against PROXIMITY_REFERENCE_HOPS. `depth_offset`
    is the hops between the reported address and where this trace started
    (a follow-on after a swap).

    On a reverse trace the three components measure the same quantities, but
    the claim they support is the mirror image: not "the funds reached this
    exchange" but "the funds came from it".

    `internal_transfers_read` says whether value moved by contract calls was
    part of the data (Ethereum native traces read Etherscan's internal
    transaction list); the limitations paragraph is worded to match.
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
            caveats=_caveats(findings, truncated, matched=False, asset=native_symbol,
                             internal_transfers_read=internal_transfers_read),
        )

    status = (prorata or {}).get("status")
    components = [
        _hop_proximity(primary_match.depth, direction, depth_offset),
        (_prorata_component(prorata, native_symbol) if status == "estimated"
         else _not_estimated(prorata, materiality, native_symbol) if status == "unknown"
         else _amount_correlation(graph, seed, primary_match.address, native_symbol, direction)),
        _match_directness(primary_match),
    ]
    score = round(sum(c.contribution for c in components), 4)
    band = _band(score)
    capped = _materiality_cap(band, materiality)
    material_caveat = []
    if capped != band and materiality:
        material_caveat = [
            f"Only {materiality['primary_share'] * 100:.1f}% of what the reported address sent "
            f"(about {materiality.get('primary_reach', 0):g} of {materiality.get('denominator', 0):g} "
            f"{native_symbol}) reached this exchange, so confidence is capped at {capped}: the rest of "
            "the funds went elsewhere."
        ]
        band = capped

    hops = f"{primary_match.depth} hop{'s' if primary_match.depth != 1 else ''}"
    if direction == OUTGOING and depth_offset:
        claim = (
            f"the swapped funds reached {primary_match.exchange} at {primary_match.address}, "
            f"{hops} after the swap ({primary_match.depth + depth_offset} from the reported address)"
        )
    elif direction == OUTGOING:
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
    # The band, not the decimal: the weights are judgement, so "0.80" would read as
    # a measured probability it is not (R10). The number stays in `score`.
    summary = f"{band.capitalize()} confidence that {claim}."

    return ConfidenceScore(
        score=score,
        band=band,
        components=components,
        summary=summary,
        caveats=material_caveat + _caveats(findings, truncated, matched=True, asset=native_symbol,
                                           internal_transfers_read=internal_transfers_read)
        + _prorata_caveats(prorata, native_symbol),
    )


_BAND_ORDER = ("very low", "low", "moderate", "high")


def _materiality_cap(band: str, materiality: dict[str, Any] | None) -> str:
    """Below the material share the band can be at most low; below a majority, at most moderate."""
    if not materiality or materiality.get("primary_share") is None:
        return band
    share = materiality["primary_share"]
    cap = ("low" if share < materiality.get("threshold", 0.10)
           else "moderate" if share < materiality.get("majority", 0.50) else "high")
    return band if _BAND_ORDER.index(band) <= _BAND_ORDER.index(cap) else cap


def _prorata_caveats(prorata: dict[str, Any] | None, native_symbol: str) -> list[str]:
    if not prorata or prorata.get("status") == "not_applicable":
        return []
    out = []
    if prorata.get("status") == "unknown":
        out.append(
            f"How much of the value at the exchange was the traced funds could not be "
            f"estimated: {prorata.get('reason')}. No amount credit was given."
        )
    if prorata.get("diluted") and prorata.get("hops"):
        low = min(prorata["hops"], key=lambda h: h["victim_share"])
        out.append(
            f"At {low['address']} the traced funds were only {low['victim_share'] * 100:.1f}% of "
            f"what the wallet received before sending on; most of what it moved came from elsewhere."
        )
    for h in prorata.get("hops") or []:
        netted = (h.get("self_transfers") or 0.0) + (h.get("recycled_in_window") or 0.0)
        if netted > 0:
            parts = []
            if h.get("self_transfers"):
                parts.append(f"sent {h['self_transfers']:,.4f} {native_symbol} to itself")
            if h.get("recycled_in_window"):
                via = ", ".join(v["address"] for v in h.get("recycled_via") or [])
                parts.append(f"got {h['recycled_in_window']:,.4f} {native_symbol} back from wallets it had "
                             f"paid in the window ({via})")
            out.append(f"{h['address']} {' and '.join(parts)}; that was its own money moving, not anyone "
                       "else's, and was netted out of what it received.")
    if prorata.get("status") == "estimated" and prorata.get("hops"):
        out.append(
            "The pro-rata estimate counts what each wallet received while the traced funds "
            "passed through it. Money a wallet already held before they arrived is not counted; "
            "counting it would lower the estimate."
        )
    return out


def _caveats(
    findings: list[PatternFinding], truncated: bool, matched: bool, asset: str = "ETH",
    internal_transfers_read: bool = False,
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
    # What was not looked at. The internal-transaction clause has to match
    # what the trace actually read: on an Ethereum native trace contract-moved
    # value is in the data, and saying it is not would contradict the report's
    # own transfer list.
    if internal_transfers_read:
        caveats.append(
            f"Only {asset} transfers were followed. Value that moved as a "
            "different asset (for example after a swap into another token) or "
            "across a bridge to another chain is not covered. Value moved by a "
            "contract call was read for addresses that signed no outgoing "
            "transfer of their own (contracts) and for every address on a "
            "reverse trace; a wallet's own signed transfers were read in full."
        )
    else:
        caveats.append(
            f"Only direct {asset} transfers were followed. Value that moved as a "
            "different asset (for example after a swap into another token), "
            "through an internal contract call, or across a bridge to another "
            "chain is not covered."
        )
    return caveats
