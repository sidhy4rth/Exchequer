"""Matches addresses in a trace against sanctioned entities and mixers.

This answers a different question from `exchange_matcher`. That module asks
"where was the money cashed out", which is the end of the trail. This one asks
"what did the money touch on the way", which is what determines whether a case
is ordinary fraud or something an investigator must escalate.

Two categories, both carrying the same evidentiary weight but very different
investigative meaning:

  sanctioned  The address is on a published sanctions list. For an Indian
              investigator this is the point at which a fraud case acquires an
              international dimension, because the counterparty is a
              designated entity rather than an anonymous wallet.

  mixer       The address is a tumbler: it pools deposits from many users and
              pays out from that pool, deliberately severing the link between
              input and output.

The mixer category carries a consequence the exchange labels do not have, and
it is the reason this module exists rather than being another label type.
**A trace must stop at a mixer.** Following outgoing transfers from a tumbler
does not follow the money -- the outputs are funded from a commingled pool and
have no established relationship to the deposit we arrived on. Expanding
through one would manufacture a trail that the transactions do not support,
and would then hand an investigator a confident-looking graph built on a false
premise. Stopping and saying so is the honest answer.

The matching rule is identical to the exchange matcher's, and identical for
the same reason: an exact lookup of the address in a data file a human can
open and read. An address is called sanctioned if and only if a published
government list says so.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import networkx as nx

from . import config
from .etherscan_client import normalize_address
from .graph_builder import OUTGOING

logger = logging.getLogger(__name__)

SANCTIONED = "sanctioned"
MIXER = "mixer"

# Categories whose addresses end a trace. See the module docstring: a mixer
# breaks the link between deposit and withdrawal, so anything past it is not
# the same money in any sense a report could defend.
TERMINAL_CATEGORIES = frozenset({MIXER})


@dataclass(frozen=True)
class RiskMatch:
    """One address in the trace that appears on a risk list."""

    address: str
    category: str  # sanctioned | mixer
    entity: str  # the designated entity or mixer service
    label: str  # human-readable, e.g. "Tornado Cash: 10 ETH pool"
    source: str  # which published list, and when it was read
    depth: int  # hops from the victim-reported address
    value_received_native: float  # value that reached it within this trace

    @property
    def is_terminal(self) -> bool:
        return self.category in TERMINAL_CATEGORIES

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "category": self.category,
            "entity": self.entity,
            "label": self.label,
            "source": self.source,
            "depth": self.depth,
            "value_received_native": round(self.value_received_native, 6),
            "is_terminal": self.is_terminal,
        }

    def describe(self, native_symbol: str = "ETH") -> str:
        """One sentence an investigator can paste into a report."""
        # The label usually is the entity name; repeating it as "X (X)" reads
        # like a bug in a document meant to be quoted.
        named = self.label if self.label == self.entity else f"{self.label} ({self.entity})"

        # For the reported address itself there is no "value that reached it
        # within this trace" -- the trace starts there, so the graph holds no
        # inbound edge and the figure would always be a misleading 0.0000.
        if self.depth == 0:
            placement = "It is the reported address itself"
        else:
            hops = f"{self.depth} hop{'s' if self.depth != 1 else ''}"
            placement = (
                f"It received {self.value_received_native:.4f} {native_symbol} "
                f"within this trace, {hops} from the reported address"
            )

        if self.category == SANCTIONED:
            return (
                f"Sanctioned entity: {self.address} is listed as {named} on "
                f"{self.source}. {placement}."
            )
        return (
            f"Mixer: {self.address} is {named}, per {self.source}. {placement}. "
            f"The trace stops here — a mixer pays out from a commingled pool, "
            f"so transfers leaving it have no established link to the funds "
            f"that arrived."
        )


class RiskMatcher:
    """Exact-match lookup of addresses against the risk-label database."""

    def __init__(
        self,
        labels: dict[str, dict[str, str]] | None = None,
        chain: str | None = None,
    ) -> None:
        self._labels: dict[str, dict[str, str]] = labels or {}
        self.chain = chain or config.DEFAULT_CHAIN.key

    # -- loading -----------------------------------------------------------
    @classmethod
    def from_file(cls, path: Path | None = None, chain: str | None = None) -> "RiskMatcher":
        """Load one chain's risk labels.

        A missing file is not an error. Risk labels are an overlay on the
        trace: without them a trace still runs and still attributes an
        exchange, it just cannot warn about what the funds passed through.
        """
        if path is None:
            logger.warning("No risk label path given; risk screening disabled")
            return cls({}, chain=chain)
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            logger.warning(
                "No risk label file at %s -- traces on this chain will not be "
                "screened against sanctions or mixer lists",
                path,
            )
            return cls({}, chain=chain)
        except json.JSONDecodeError as exc:
            logger.error("Risk label file at %s is not valid JSON: %s", path, exc)
            return cls({}, chain=chain)

        entries = raw.get("labels", raw) if isinstance(raw, dict) else {}
        default_source = (raw.get("_meta") or {}).get("source", "unspecified list")

        labels: dict[str, dict[str, str]] = {}
        for address, value in entries.items():
            if address.startswith("_"):  # metadata keys
                continue
            if not isinstance(value, dict):
                logger.warning("Risk entry for %s is not an object; skipped", address)
                continue

            category = (value.get("category") or "").strip().lower()
            if category not in (SANCTIONED, MIXER):
                # An unrecognised category must not silently become a warning
                # of the wrong kind. Dropping it is the safe failure.
                logger.warning(
                    "Risk entry for %s has unknown category %r; skipped", address, category
                )
                continue

            entity = value.get("entity") or value.get("name")
            if not entity:
                logger.warning("Risk entry for %s names no entity; skipped", address)
                continue

            labels[normalize_address(address)] = {
                "category": category,
                "entity": entity,
                "label": value.get("label", entity),
                "source": value.get("source", default_source),
            }

        logger.info("Loaded %d risk labels from %s", len(labels), path)
        return cls(labels, chain=chain)

    # -- lookup ------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._labels)

    @property
    def entities(self) -> list[str]:
        """Distinct entities covered, for the /risk-labels endpoint."""
        return sorted({meta["entity"] for meta in self._labels.values()})

    def counts_by_category(self) -> dict[str, int]:
        counts = {SANCTIONED: 0, MIXER: 0}
        for meta in self._labels.values():
            counts[meta["category"]] = counts.get(meta["category"], 0) + 1
        return counts

    def lookup(self, address: str) -> dict[str, str] | None:
        return self._labels.get(normalize_address(address))

    def entries(self) -> list[tuple[str, dict[str, str]]]:
        """Every (address, record) pair, for anything that lists the database."""
        return list(self._labels.items())

    def is_flagged(self, address: str) -> bool:
        return normalize_address(address) in self._labels

    def is_terminal(self, address: str) -> bool:
        """True if a trace must stop expanding at `address`.

        Passed to the graph builder alongside the exchange matcher's own
        terminal test. Only mixers qualify: a sanctioned address is still an
        ordinary wallet whose outgoing transfers mean exactly what they say,
        so there is no reason to stop following the money there.
        """
        meta = self.lookup(address)
        return bool(meta) and meta["category"] in TERMINAL_CATEGORIES

    # -- graph annotation --------------------------------------------------
    def annotate(self, graph: nx.DiGraph, direction: str = OUTGOING) -> list[RiskMatch]:
        """Tag every risk-listed address in `graph` and return the matches.

        Sorted by depth (closest to the victim first), then by value, matching
        the exchange matcher so both lists read the same way in a report.
        """
        matches: list[RiskMatch] = []

        for node, data in graph.nodes(data=True):
            meta = self.lookup(node)
            if meta is None:
                continue

            edges = (
                graph.in_edges(node, data=True) if direction == OUTGOING
                else graph.out_edges(node, data=True)
            )
            value_in = sum(edge.get("value_native", 0.0) for _, _, edge in edges)
            data["risk_category"] = meta["category"]
            data["risk_entity"] = meta["entity"]
            data["risk_label"] = meta["label"]
            data["risk_source"] = meta["source"]
            data.setdefault("flags", set()).add(meta["category"])
            if meta["category"] in TERMINAL_CATEGORIES:
                data["is_terminal"] = True

            matches.append(
                RiskMatch(
                    address=node,
                    category=meta["category"],
                    entity=meta["entity"],
                    label=meta["label"],
                    source=meta["source"],
                    depth=data.get("depth", 0),
                    value_received_native=value_in,
                )
            )

        matches.sort(key=lambda m: (m.depth, -m.value_received_native))
        return matches


@lru_cache(maxsize=None)
def get_risk_matcher(chain_key: str | None = None) -> RiskMatcher:
    """Risk matcher for one chain. Cached so each label file is read once."""
    chain = config.get_chain(chain_key)
    return RiskMatcher.from_file(chain.risk_labels_path, chain=chain.key)
