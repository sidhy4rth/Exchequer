"""How much of the reported funds likely reached the exchange: pro-rata tracing.

A trace shows *that* a path runs from the reported address to an exchange. It
does not show how much of what arrived there was the victim's. A wallet in the
middle may be receiving other people's money at the same time -- 40 USDT of
the victim's can join 961 USDT from elsewhere and leave as 1,001.50 -- and
comparing the first hop with the last (1,001.50 "out of" 40) says nothing
about whose money that is.

Pro-rata (or "haircut") tracing is the standard answer for mixed funds, and
it is simple enough to check by hand. At each wallet on the path:

    victim share  = victim funds that came in / ALL funds that came in
    victim onward = what the wallet sent on along the path x victim share

where "came in" means every transfer into the wallet from the moment the
traced funds began arriving to the moment it last sent them on -- read from
the chain, not just the transfers the trace happened to follow. The victim
amount can only shrink along the path, never grow. What survives the last
wallet is the estimate of the victim's funds reaching the exchange.

What it does not see, and says so: money a wallet already held before the
traced funds arrived. Counting it would lower the victim's share, so the
estimate is an upper bound for a wallet with an old balance. And where a
wallet's incoming history in the window could not be read in full, there is
no estimate at all -- "unknown" is reported rather than a number built from
part of the picture.
"""
from __future__ import annotations

from typing import Any, Callable

import networkx as nx

# A share below this at any wallet is called out: the victim's funds were a
# small part of what that wallet was moving.
DILUTED = 0.25

IncomingBetween = Callable[[str, int, int, int, int], tuple[list[Any], bool]]


def _in_window(txs: list[dict[str, Any]], end_block: int, end_ts: int) -> float:
    """Value of `txs` at or before the window's end -- by block where the
    chain gives one, by time where it does not (Tron)."""
    return sum(t.get("value_native", 0.0) for t in txs
               if (t["block_number"] <= end_block if t.get("block_number") else (t.get("timestamp") or 0) <= end_ts))


def estimate(graph: nx.DiGraph, path: list[str], incoming_between: IncomingBetween | None) -> dict[str, Any]:
    """Pro-rata estimate of the reported funds reaching the end of `path`.

    `path` runs seed -> ... -> exchange in the direction the money moved.
    `incoming_between(address, start_block, end_block, start_ts, end_ts)`
    returns (transfers into address in that range, whether the read was
    complete). Never raises: a failed read is an "unknown", not a failed trace.
    """
    if len(path) < 2 or (len(path) > 2 and incoming_between is None):
        return {"status": "not_applicable"}
    first = graph.edges[path[0], path[1]]
    sent = float(first.get("value_native", 0.0))
    if sent <= 0:
        return {"status": "not_applicable"}

    carried = sent
    hops: list[dict[str, Any]] = []
    for i in range(1, len(path) - 1):
        wallet = path[i]
        edge_in = graph.edges[path[i - 1], wallet]
        edge_out = graph.edges[wallet, path[i + 1]]
        txs_in, txs_out = edge_in.get("transactions") or [], edge_out.get("transactions") or []
        blocks_in = [t["block_number"] for t in txs_in if t.get("block_number")]
        blocks_out = [t["block_number"] for t in txs_out if t.get("block_number")]
        times_in = [t["timestamp"] for t in txs_in if t.get("timestamp")]
        times_out = [t["timestamp"] for t in txs_out if t.get("timestamp")]
        if not (blocks_in and blocks_out) and not (times_in and times_out):
            return {"status": "unknown", "sent": sent, "hops": hops,
                    "reason": f"the transfers through {wallet} carry neither blocks nor times to bound the window"}
        start_block, end_block = (min(blocks_in), max(blocks_out)) if blocks_in and blocks_out else (0, 0)
        start_ts = min(times_in) if times_in else 0
        end_ts = max(times_out) if times_out else 0
        if (end_block < start_block) or (not blocks_in and end_ts < start_ts):
            return {"status": "unknown", "sent": sent, "hops": hops,
                    "reason": f"{wallet} sent on before the traced funds arrived"}

        try:
            received, complete = incoming_between(wallet, start_block, end_block, start_ts, end_ts)
        except Exception as exc:  # noqa: BLE001 -- an estimate is never worth a failed trace
            return {"status": "unknown", "sent": sent, "hops": hops,
                    "reason": f"{wallet}'s incoming transfers could not be read ({exc})"}
        if not complete:
            return {"status": "unknown", "sent": sent, "hops": hops,
                    "reason": f"{wallet} received too many transfers in the window to read in full"}

        # The traced funds that reached this wallet before it last sent on.
        edge_total = float(edge_in.get("value_native", 0.0)) or 1.0
        in_window = _in_window(txs_in, end_block, end_ts)
        carried_in = carried * (in_window / edge_total)
        total_in = max(sum(t.value_native for t in received), in_window)
        share = min(1.0, carried_in / total_in) if total_in > 0 else 0.0
        onward = float(edge_out.get("value_native", 0.0))
        carried = min(carried_in, onward * share)
        hops.append({
            "address": wallet,
            "received_in_window": round(total_in, 6),
            "victim_in": round(carried_in, 6),
            "victim_share": round(share, 4),
            "sent_on": round(onward, 6),
            "victim_on": round(carried, 6),
        })

    arrived = float(graph.edges[path[-2], path[-1]].get("value_native", 0.0))
    lowest = min((h["victim_share"] for h in hops), default=1.0)
    return {
        "status": "estimated",
        "sent": round(sent, 6),
        "estimated": round(carried, 6),
        "ratio": round(min(1.0, carried / sent), 4),
        "arrived_total": round(arrived, 6),
        "lowest_share": lowest,
        "diluted": lowest < DILUTED,
        "hops": hops,
    }
