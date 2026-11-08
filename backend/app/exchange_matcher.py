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
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import networkx as nx

from . import config
from .etherscan_client import is_valid_address, normalize_address
from .graph_builder import OUTGOING

logger = logging.getLogger(__name__)

# The wallet_type of an attribution that was inferred from an address's
# behaviour (deposit_inference.py) rather than read from a label file. Scoring
# treats it as weaker, and the report says so.
INFERRED_DEPOSIT = "inferred_deposit"
DEPOSIT_WALLET = "deposit_wallet"

# A per-customer deposit address, said so explicitly: "Binance Dep: 0x..." (the
# deposit label sets) or "<Exchange>: Deposit Address|Wallet". The word
# "deposit" alone also names the exchange's own infrastructure ("Deposit
# Funder", "Eth2 Depositor", "Batch Deposit") and other firms' accounts at the
# exchange ("AltCoinTrader: Binance Deposit 1"), and a deposit address is what
# makes a letter ask the exchange for an account holder's KYC.
DEPOSIT_LABEL = re.compile(r"\bDep:\s|^[^:]+:\s*Deposit (?:Address|Wallet)\b", re.IGNORECASE)


def is_deposit_label(label: str | None) -> bool:
    """True if the label itself says the address is one customer's deposit address."""
    return bool(DEPOSIT_LABEL.search(label or ""))


@dataclass(frozen=True)
class ExchangeMatch:
    """One address in the trace that belongs to a known exchange."""

    address: str
    exchange: str
    label: str
    wallet_type: str
    depth: int  # hops from the victim-reported address
    # Value that moved between this wallet and the rest of the trace. On a
    # forward trace that is what reached it; on a reverse trace the exchange
    # sits upstream and has no inbound edges, so it is what the wallet sent
    # into the trace. Summing the wrong side would report a confident 0.
    value_received_native: float
    # Present only on an inferred match: everything the inference looked at.
    evidence: dict[str, Any] | None = None

    @property
    def inferred(self) -> bool:
        return self.wallet_type == INFERRED_DEPOSIT

    def to_dict(self) -> dict[str, Any]:
        out = {
            "address": self.address,
            "exchange": self.exchange,
            "label": self.label,
            "wallet_type": self.wallet_type,
            "depth": self.depth,
            "value_received_native": round(self.value_received_native, 6),
            "inferred": self.inferred,
        }
        if self.evidence is not None:
            out["evidence"] = self.evidence
        return out


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


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
            raw = json.loads(path.read_text(encoding="utf-8"))
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
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.error("Exchange label file at %s is not valid JSON: %s", path, exc)
            return cls({}, chain=chain)
        except OSError as exc:  # a directory, no permission: unusable, never fatal
            logger.error("Exchange label file at %s cannot be read: %s", path, exc)
            return cls({}, chain=chain)

        # Accept both the documented simple shape {"0x..": "Binance"} and the
        # richer shape {"0x..": {"exchange": ..., "label": ..., "type": ...}}.
        # One bad entry is logged and skipped, never raised: the lifespan
        # loads every chain's file, so an exception would stop the site.
        entries = raw.get("labels", raw) if isinstance(raw, dict) else None
        if not isinstance(entries, dict):
            logger.error("Exchange label file at %s: labels is not an object; file not used", path)
            return cls({}, chain=chain)
        labels: dict[str, dict[str, str]] = {}
        for address, value in entries.items():
            if not isinstance(address, str) or address.startswith("_"):  # metadata keys
                continue
            key = normalize_address(address)
            if not is_valid_address(key):
                logger.warning("Label entry key %r is not an address; skipped", address)
                continue
            if isinstance(value, str) and value.strip():
                labels[key] = {"exchange": value.strip(), "label": value.strip(), "type": "unknown"}
            elif isinstance(value, dict):
                exchange = _text(value.get("exchange")) or _text(value.get("name"))
                if not exchange:
                    logger.warning("Label entry for %s has no exchange name; skipped", address)
                    continue
                labels[key] = {
                    "exchange": exchange,
                    "label": _text(value.get("label")) or exchange,
                    "type": _text(value.get("type")) or "unknown",
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

    def entries(self) -> list[tuple[str, dict[str, str]]]:
        """Every (address, record) pair, for anything that lists the database."""
        return list(self._labels.items())

    def is_exchange(self, address: str) -> bool:
        """True if `address` is a known exchange wallet.

        Passed to the graph builder as its `is_terminal` predicate: the trace
        stops expanding here, because the funds have reached their cash-out
        point and exchange hot wallets have millions of unrelated transactions.
        """
        return normalize_address(address) in self._labels

    # -- graph annotation --------------------------------------------------
    def annotate(self, graph: nx.DiGraph, direction: str = OUTGOING) -> list[ExchangeMatch]:
        """Tag every known exchange address in `graph` and return the matches.

        Sorted by depth (closest to the victim first), then by value, so the
        most investigatively relevant match leads.

        `direction` decides which side of the node carries the traced value:
        an exchange at the end of a forward trace received it, one found
        upstream of a reverse trace sent it.
        """
        matches: list[ExchangeMatch] = []

        for node, data in graph.nodes(data=True):
            meta = self.lookup(node)
            if meta is None:
                continue

            edges = (
                graph.in_edges(node, data=True) if direction == OUTGOING
                else graph.out_edges(node, data=True)
            )
            value_in = sum(edge.get("value_native", 0.0) for _, _, edge in edges)
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
    def primary_match(matches: list[ExchangeMatch],
                      shares: dict[str, float] | None = None) -> ExchangeMatch | None:
        """The match to attribute the case to.

        Rule: follow the money. With `shares` (each match's share of what the
        reported address sent; see pipeline.run_trace), the largest share
        wins; shares within one percentage point count as equal, and then the
        match fewest hops away wins, a label-file match before an inferred
        one, then the larger value received. Closest-first alone let one dust
        transfer to any exchange wallet, or to an innocent customer's deposit
        address, become the case's exchange. An inferred deposit address keeps
        its lead over the hot wallet it sweeps to: the hot wallet's share
        through it can never be larger. Without `shares` the order is the
        closest-first one, for callers that have no graph to measure.

        Shares saturate at 1.0 when the denominator is smaller than what the
        wallet sent (the victim's reported payments, a swap's output), so
        every branch carrying at least that much ties. `MatchShares.by_value`
        (each match's share of everything the wallet sent) breaks those ties
        before hops do: the larger branch wins, not the closer one.
        """
        if not matches:
            return None
        if shares is None:
            return min(matches, key=lambda m: (m.depth, m.inferred, -m.value_received_native))
        by_value = getattr(shares, "by_value", None) or {}
        return min(matches, key=lambda m: (-round(shares.get(m.address, 0.0), 2),
                                           -round(by_value.get(m.address, shares.get(m.address, 0.0)), 2),
                                           m.depth, m.inferred, -m.value_received_native))


class MatchShares(dict):
    """Each match's share of the traced funds (address -> share), as
    pipeline._materiality measures it, plus `by_value`: each match's share of
    everything the reported wallet sent, which breaks ties between shares that
    saturated at 1.0 (see ExchangeMatcher.primary_match)."""

    def __init__(self, shares: dict[str, float] | None = None, by_value: dict[str, float] | None = None):
        super().__init__(shares or {})
        self.by_value = dict(by_value or {})


def get_router_matcher(chain_key: str | None = None) -> ExchangeMatcher:
    """DEX routers for one chain, in the same file shape as exchange labels.

    Same class on purpose: an exact lookup in a file a human can open. The
    `exchange` field holds the protocol name (Uniswap, 1inch) and `type` is
    always "router". A chain with no router file gets an empty matcher, so
    swaps simply go undetected there rather than failing the trace.
    """
    return _router_matcher(config.get_chain(chain_key).key)


def get_matcher(chain_key: str | None = None) -> ExchangeMatcher:
    """Matcher for one chain. Cached so each label file is read once.

    Called with no argument it serves the default chain, which keeps every
    existing caller working unchanged.
    """
    return _matcher(config.get_chain(chain_key).key)


# Cached on the chain's own key, never on what the caller typed: None, "eth"
# and "ethereum" are one chain, and each spelling used to hold its own copy of
# that chain's label files (tens of MB on a 512 MB host).
@lru_cache(maxsize=None)
def _router_matcher(key: str) -> ExchangeMatcher:
    chain = config.get_chain(key)
    if chain.router_labels_path is None:
        return ExchangeMatcher({}, chain=chain.key)
    return ExchangeMatcher.from_file(chain.router_labels_path, chain=chain.key)


@lru_cache(maxsize=None)
def _matcher(key: str) -> ExchangeMatcher:
    chain = config.get_chain(key)
    return ExchangeMatcher.from_file(chain.labels_path, chain=chain.key)
