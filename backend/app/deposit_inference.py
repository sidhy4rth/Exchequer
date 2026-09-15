"""Infers that an unlabelled address is an exchange's per-customer deposit address.

Why this exists. Most real cash-outs do not land on a labelled hot wallet.
The customer is given a deposit address that the exchange controls, the money
lands there, and the exchange later *sweeps* it into a hot wallet. The label
files know the hot wallet; they almost never know the deposit address. So the
trace reaches an unlabelled wallet one hop before the exchange, and the
lawful request an investigator then writes has to name *that* wallet -- a hot
wallet receives from thousands of customers and identifies nobody.

What can be observed from the data in hand. When the trace expands an address
it has fetched that address's outgoing transfers. An exchange deposit address
has a distinctive outgoing history: every transfer it ever made went to the
same labelled exchange wallet, because the only thing that ever happens to
money there is the sweep. A personal wallet that deposits to an exchange does
not look like that -- it sends to its *own* deposit address, which is
unlabelled, and it does other things with its money.

The rule, stated plainly. An address is inferred to be a deposit address of
exchange E when all of the following hold:

  1. It is not the reported address and carries no label of its own.
  2. It made at least `min_sweeps` outgoing transfers.
  3. Every one of them went to a single address H that the label file records
     as an E hot wallet (or exchange/contract/cold wallet) -- never to a
     labelled *deposit* wallet, because deposits sweep to hot wallets, and
     never anywhere else.
  4. Where the provider can answer it cheaply, the address's current native
     balance is recorded as evidence: a swept deposit address holds close to
     nothing. This is reported, not required, because a deposit that has
     landed and not yet been swept is still a deposit address.

Everything the rule looked at is attached to the finding so it can be checked
by hand on a block explorer, and the finding says what would confirm it: a
lawful request to E asking whether the address is one of theirs.

What it cannot see. Only outgoing transfers are used, so the timing between a
deposit and its sweep is not measured, and the gas-funding transfer an
exchange sends before an ERC-20 sweep is not visible in a token transfer
list. The rule therefore stays strict on what it can see -- one destination,
every time -- rather than loose on what it cannot.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import networkx as nx

from .exchange_matcher import INFERRED_DEPOSIT, ExchangeMatch, ExchangeMatcher

logger = logging.getLogger(__name__)

# Label types a sweep may land on. A labelled deposit wallet is excluded: a
# wallet whose outflows go to *another* deposit address is a customer, not a
# deposit address.
SWEEP_DESTINATION_TYPES = frozenset(
    {"hot_wallet", "exchange_wallet", "contract_wallet", "cold_wallet"}
)


@dataclass(frozen=True)
class DepositInferenceConfig:
    """Every threshold the inference uses, in one place."""

    # One transfer to an exchange is what any customer does. Two or more, all
    # to the same hot wallet and nothing else, is the sweep pattern.
    min_sweeps: int = 2
    # Below this the address moved dust, and the pattern is not evidence.
    min_total_native: float = 0.001


def _sweep_destination(
    matcher: ExchangeMatcher, counterparty: str
) -> dict[str, str] | None:
    meta = matcher.lookup(counterparty)
    if meta is None:
        return None
    if meta.get("type") not in SWEEP_DESTINATION_TYPES:
        return None
    if "deposit" in (meta.get("label") or "").lower():
        return None
    return meta


def infer_deposit_addresses(
    graph: nx.DiGraph,
    matcher: ExchangeMatcher,
    cfg: DepositInferenceConfig | None = None,
    balance_of: Callable[[str], float] | None = None,
    native_symbol: str = "ETH",
) -> list[ExchangeMatch]:
    """Return one inferred match per address that satisfies the rule.

    Reads `outflows_by_counterparty`, which the graph builder records on every
    expanded address from its complete fetched outgoing history (including
    transfers the time rule later left out of the graph): the question here is
    what the address does with money in general, not what it did with the
    traced funds.
    """
    cfg = cfg or DepositInferenceConfig()
    inferred: list[ExchangeMatch] = []

    for node, data in graph.nodes(data=True):
        if data.get("is_seed") or data.get("is_exchange") or matcher.lookup(node):
            continue
        outflows: dict[str, dict[str, Any]] = data.get("outflows_by_counterparty") or {}
        if len(outflows) != 1:
            continue
        (destination, stats), = outflows.items()
        if stats.get("count", 0) < cfg.min_sweeps:
            continue
        if stats.get("total", 0.0) < cfg.min_total_native:
            continue
        meta = _sweep_destination(matcher, destination)
        if meta is None:
            continue

        evidence: dict[str, Any] = {
            "sweep_count": stats["count"],
            "sweep_destination": destination,
            "sweep_destination_label": meta["label"],
            "share_of_outflow_to_destination": 1.0,
            "other_outgoing_destinations": 0,
            "total_swept_native": round(stats["total"], 6),
            "first_sweep": stats.get("first"),
            "last_sweep": stats.get("last"),
            "thresholds_applied": {
                "min_sweeps": cfg.min_sweeps,
                "min_total_native": cfg.min_total_native,
                "required_share_to_one_destination": 1.0,
            },
        }
        if balance_of is not None:
            try:
                evidence["current_balance_native"] = round(balance_of(node), 6)
            except Exception as exc:  # noqa: BLE001 -- evidence, not a requirement
                logger.warning("Balance lookup failed for %s: %s", node, exc)
                evidence["current_balance_native"] = None
        evidence["confirmation"] = (
            f"A lawful request to {meta['exchange']} asking whether {node} is a "
            f"deposit address it issued, and to which customer, would confirm or "
            f"refute this inference."
        )

        data["inferred_exchange"] = meta["exchange"]
        data["inferred_evidence"] = evidence
        data["is_exchange"] = True  # the pattern rules exempt exchanges
        inferred.append(
            ExchangeMatch(
                address=node,
                exchange=meta["exchange"],
                label=f"probable {meta['exchange']} deposit address (inferred)",
                wallet_type=INFERRED_DEPOSIT,
                depth=data.get("depth", 0),
                value_received_native=sum(
                    edge.get("value_native", 0.0) for _, _, edge in graph.in_edges(node, data=True)
                ),
                evidence=evidence,
            )
        )

    inferred.sort(key=lambda m: (m.depth, -m.value_received_native))
    return inferred


def describe(match: ExchangeMatch, native_symbol: str = "ETH") -> str:
    """One paragraph an investigator can paste into a report."""
    e = match.evidence or {}
    balance = e.get("current_balance_native")
    balance_text = (
        f" Its current balance is {balance:.4f} {native_symbol}." if balance is not None else ""
    )
    return (
        f"{match.address} is inferred to be a {match.exchange} deposit address. "
        f"Every one of its {e.get('sweep_count')} outgoing transfers went to "
        f"{e.get('sweep_destination')} ({e.get('sweep_destination_label')}), a "
        f"labelled {match.exchange} wallet, and to nowhere else -- the shape an "
        f"exchange produces when it sweeps a customer's deposits into its hot "
        f"wallet.{balance_text} This is an inference, not a label-file match, "
        f"and it scores lower for that reason. {e.get('confirmation', '')}"
    )
