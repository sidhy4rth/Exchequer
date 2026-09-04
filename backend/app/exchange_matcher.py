"""Matches addresses in a trace against known exchange hot wallets.

This is the step that turns "the money went to 0x28c6..." into "the money was
cashed out at Binance" -- the answer an investigator actually needs in order to
send a legal request to the right company.

The matching rule itself is deliberately trivial and auditable: an exact
lookup of the lowercased address in that chain's label file. There is no
clustering, no heuristic ownership inference, and no machine learning here. An
address is attributed to an exchange if and only if a human put it in that
file. That is the point -- every attribution this tool makes can be traced to a
specific, checkable line in a data file.

Labels are per chain and never shared between them. Binance's hot wallet on
Ethereum and Binance's hot wallet on BNB Smart Chain are different addresses,
and matching an address seen on one chain against the other chain's labels
would manufacture an attribution that no transaction supports.
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

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExchangeMatch:
    """One address in the trace that belongs to a known exchange."""

    address: str
    exchange: str
    label: str
    wallet_type: str
    depth: int  # hops from the victim-reported address
    value_received_native: float  # value that reached it *within this trace*

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "exchange": self.exchange,
            "label": self.label,
            "wallet_type": self.wallet_type,
            "depth": self.depth,
            "value_received_native": round(self.value_received_native, 6),
        }


class ExchangeMatcher:
    """Exact-match lookup of addresses against the labelled exchange database."""

    def __init__(
        self,
        labels: dict[str, dict[str, str]] | None = None,
        chain: str | None = None,
    ) -> None:
        self._labels: dict[str, dict[str, str]] = labels or {}
        self.chain = chain or config.DEFAULT_CHAIN.key

    # -- loading -----------------------------------------------------------
    @classmethod
    def from_file(cls, path: Path | None = None, chain: str | None = None) -> "ExchangeMatcher":
        path = path or config.EXCHANGE_LABELS_PATH
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            # Not fatal: a chain with no label file still traces, it just
            # cannot attribute. Saying so beats pretending the funds went
            # nowhere known.
            logger.warning(
                "No exchange label file at %s -- traces on this chain will "
                "produce a graph but no attribution",
                path,
            )
            return cls({}, chain=chain)
        except json.JSONDecodeError as exc:
            logger.error("Exchange label file at %s is not valid JSON: %s", path, exc)
            return cls({}, chain=chain)

        # Accept both the documented simple shape {"0x..": "Binance"} and the
        # richer shape {"0x..": {"exchange": ..., "label": ..., "type": ...}}.
        entries = raw.get("labels", raw) if isinstance(raw, dict) else {}
        labels: dict[str, dict[str, str]] = {}
        for address, value in entries.items():
            if address.startswith("_"):  # metadata keys
                continue
            key = normalize_address(address)
            if isinstance(value, str):
                labels[key] = {"exchange": value, "label": value, "type": "unknown"}
            elif isinstance(value, dict):
                exchange = value.get("exchange") or value.get("name")
                if not exchange:
                    logger.warning("Label entry for %s has no exchange name; skipped", address)
                    continue
                labels[key] = {
                    "exchange": exchange,
                    "label": value.get("label", exchange),
                    "type": value.get("type", "unknown"),
                }
            else:
                logger.warning("Unrecognised label entry for %s; skipped", address)

        logger.info("Loaded %d exchange labels from %s", len(labels), path)
        return cls(labels, chain=chain)

    # -- lookup ------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._labels)

    @property
    def exchanges(self) -> list[str]:
        """Distinct exchange names covered by the database."""
        return sorted({meta["exchange"] for meta in self._labels.values()})

    def lookup(self, address: str) -> dict[str, str] | None:
        """Return the label record for `address`, or None if unknown."""
        return self._labels.get(normalize_address(address))

    def is_exchange(self, address: str) -> bool:
        """True if `address` is a known exchange wallet.

        Passed to the graph builder as its `is_terminal` predicate: the trace
        stops expanding here, because the funds have reached their cash-out
        point and exchange hot wallets have millions of unrelated transactions.
        """
        return normalize_address(address) in self._labels

    # -- graph annotation --------------------------------------------------
    def annotate(self, graph: nx.DiGraph) -> list[ExchangeMatch]:
        """Tag every known exchange address in `graph` and return the matches.

        Sorted by depth (closest to the victim first), then by value received,
        so the most investigatively relevant match leads.
        """
        matches: list[ExchangeMatch] = []

        for node, data in graph.nodes(data=True):
            meta = self.lookup(node)
            if meta is None:
                continue

            value_in = sum(
                edge.get("value_native", 0.0) for _, _, edge in graph.in_edges(node, data=True)
            )
            data["exchange"] = meta["exchange"]
            data["label"] = meta["label"]
            data["wallet_type"] = meta["type"]
            data["is_exchange"] = True
            data["is_terminal"] = True

            matches.append(
                ExchangeMatch(
                    address=node,
                    exchange=meta["exchange"],
                    label=meta["label"],
                    wallet_type=meta["type"],
                    depth=data.get("depth", 0),
                    value_received_native=value_in,
                )
            )

        matches.sort(key=lambda m: (m.depth, -m.value_received_native))
        return matches

    @staticmethod
    def primary_match(matches: list[ExchangeMatch]) -> ExchangeMatch | None:
        """The match to attribute the case to.

        Rule: the exchange reached in the fewest hops from the victim's
        address. Rationale -- the shortest path is the least diluted by
        intermediate mixing, so it is the strongest attribution. Ties are
        broken by the larger value received.

        `annotate` already sorts by exactly that key, so this is the head.
        """
        return matches[0] if matches else None


@lru_cache(maxsize=None)
def get_matcher(chain_key: str | None = None) -> ExchangeMatcher:
    """Matcher for one chain. Cached so each label file is read once.

    Called with no argument it serves the default chain, which keeps every
    existing caller working unchanged.
    """
    chain = config.get_chain(chain_key)
    return ExchangeMatcher.from_file(chain.labels_path, chain=chain.key)
