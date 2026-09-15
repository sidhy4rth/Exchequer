"""Detects that a transfer into a DEX router was a swap, and what came back.

A trace follows one asset. When a wallet sends 10 ETH to a Uniswap router the
trail in ETH ends there -- but the wallet did not lose the money; it got it
back as USDT, in the same transaction, and carried on. Until now the trace
reported that as "the funds went to an address that sent nothing onward",
which is true of the ETH and false of the money.

What is done here is deliberately small. When an outgoing transfer's
recipient is a labelled router (data/router_labels*.json), the transaction
receipt is fetched and its ERC-20 `Transfer` events are read. A Transfer
whose recipient is the sender of the transaction is the swap's output: that
token, in that amount, came back to the same wallet. The edge then carries

    swap = {router, asset_in, amount_in, asset_out, amount_out, tx, ...}

and the trace says, in one sentence, that the funds were swapped and where to
resume. The trace is NOT resumed on the output asset here. Doing so honestly
means deciding what amount correlation should mean across 1 ETH -> 2,400
USDT, and the one-asset-per-trace rule exists precisely because those are
not comparable; a swap that is recorded and re-run on the output asset keeps
every threshold valid, and a swap that is silently crossed does not.

What it cannot see. A swap whose output is the chain's native coin (USDT ->
ETH) leaves no Transfer event to the sender -- the router unwraps WETH and
sends ETH by an internal transaction -- so it is reported as "sent to a
router; no token output found in the receipt" rather than guessed. And on a
token trace the transfer into a swap usually lands on a liquidity *pool*, not
on the router, so it is not recognised; only transactions sent to a labelled
router are.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import networkx as nx

from . import config
from .etherscan_client import normalize_address
from .exchange_matcher import ExchangeMatcher

logger = logging.getLogger(__name__)

# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


@dataclass(frozen=True)
class SwapConfig:
    # Receipts cost one request each; a wallet that swapped forty times is
    # already established as swapping after the first two.
    max_receipts_per_edge: int = 2


def _topic_address(topic: str) -> str:
    """A 32-byte topic holding a left-padded address -> normalized 0x address."""
    return normalize_address("0x" + topic[-40:])


def parse_swap_outputs(receipt: dict[str, Any], sender: str) -> list[dict[str, Any]]:
    """Every ERC-20 Transfer in `receipt` whose recipient is `sender`.

    These are the assets that came back to the wallet that sent the swap.
    Returned raw (contract and integer units); the caller names them.
    """
    sender = normalize_address(sender)
    outputs: list[dict[str, Any]] = []
    for log in receipt.get("logs") or []:
        topics = log.get("topics") or []
        if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC:
            continue
        if _topic_address(topics[2]) != sender:
            continue
        try:
            units = int(log.get("data") or "0x0", 16)
        except ValueError:
            continue
        if units <= 0:
            continue
        outputs.append({
            "contract": normalize_address(log.get("address", "")),
            "from": _topic_address(topics[1]),
            "units": units,
        })
    return outputs


def _name_asset(chain: config.Chain, contract: str, units: int) -> tuple[str, float | None]:
    """Symbol and human amount if the contract is a configured token, else the
    bare contract and no amount -- the decimals are not known and guessing 18
    would misstate the figure."""
    for token in chain.tokens:
        if normalize_address(token.address) == contract:
            return token.symbol, units / (10 ** token.decimals)
    return f"token {contract}", None


def detect_swaps(
    graph: nx.DiGraph,
    routers: ExchangeMatcher,
    receipt_of: Callable[[str], dict[str, Any] | None] | None,
    chain: config.Chain,
    asset_symbol: str,
    cfg: SwapConfig | None = None,
) -> list[dict[str, Any]]:
    """Tag router nodes and, where a receipt can be read, the swap on each edge.

    Returns one record per swap found (or per router edge whose output could
    not be read), for the response and the report.
    """
    cfg = cfg or SwapConfig()
    findings: list[dict[str, Any]] = []

    for source, target, edge in graph.edges(data=True):
        meta = routers.lookup(target)
        if meta is None:
            continue
        node = graph.nodes[target]
        node["is_router"] = True
        node["router"] = meta["exchange"]
        node["label"] = node.get("label") or meta["label"]

        swaps: list[dict[str, Any]] = []
        transactions = edge.get("transactions") or []
        for tx in transactions[: cfg.max_receipts_per_edge]:
            record: dict[str, Any] = {
                "router": meta["exchange"],
                "router_label": meta["label"],
                "router_address": target,
                "sender": source,
                "tx": tx.get("hash"),
                "timestamp": tx.get("timestamp"),
                "asset_in": asset_symbol,
                "amount_in": tx.get("value_native"),
                "asset_out": None,
                "amount_out": None,
                "output_read": False,
            }
            receipt = None
            if receipt_of is not None and tx.get("hash"):
                try:
                    receipt = receipt_of(tx["hash"])
                except Exception as exc:  # noqa: BLE001 -- one receipt must not kill a trace
                    logger.warning("Receipt for %s could not be read: %s", tx.get("hash"), exc)
            if receipt:
                outputs = parse_swap_outputs(receipt, source)
                if outputs:
                    # The largest single output is the swap's result; the rest
                    # are refunds or fee rebates and are listed, not summed.
                    main = max(outputs, key=lambda o: o["units"])
                    symbol, amount = _name_asset(chain, main["contract"], main["units"])
                    record.update(
                        asset_out=symbol,
                        asset_out_contract=main["contract"],
                        amount_out=amount,
                        amount_out_units=str(main["units"]),
                        output_read=True,
                        other_outputs=len(outputs) - 1,
                    )
            swaps.append(record)
            findings.append(record)

        if swaps:
            edge["swaps"] = swaps
            edge["swap"] = swaps[0]

    return findings


def describe(swap: dict[str, Any]) -> str:
    """One sentence for the report."""
    where = f"{swap['router_label']} ({swap['router_address']})"
    if swap.get("output_read"):
        amount = swap.get("amount_out")
        out = (
            f"{amount:,.4f} {swap['asset_out']}" if amount is not None
            else f"{swap['amount_out_units']} units of {swap['asset_out']}"
        )
        return (
            f"{swap['sender']} sent {swap['amount_in']:.4f} {swap['asset_in']} to {where} "
            f"in transaction {swap['tx']} and received {out} back in the same "
            f"transaction: a swap, not a payment. This trace follows "
            f"{swap['asset_in']} and ends here; to follow the money further, "
            f"re-run it on {swap['asset_out']} from {swap['sender']}."
        )
    return (
        f"{swap['sender']} sent {swap['amount_in']:.4f} {swap['asset_in']} to {where}, "
        f"a swap router, in transaction {swap['tx']}. No token was returned to the "
        f"sender in that transaction's receipt, so what came back could not be "
        f"read -- this is what a swap into the chain's native coin looks like, "
        f"and it is reported rather than guessed."
    )
