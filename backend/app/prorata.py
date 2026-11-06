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

"Came in" is new money only. The route's own transfer is counted once, even
when the provider's list missed it (an internal transfer). A wallet paying
itself, or getting back coins it had just paid out (W -> X -> W), adds
nothing anyone else owned, so both are netted out and the hop says how much
-- otherwise each bounce, for the price of gas, shrank the estimate.

What it does not see, and says so: money a wallet already held before the
traced funds arrived. Counting it would lower the victim's share. And where a
wallet's history in the window could not be read in full, there is no
estimate at all -- "unknown" is reported rather than a number built from part
of the picture.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable

import networkx as nx

from .provider_errors import public_reason
from .tracing_methods import FlowsBetween, transfer_key

# A share below this at any wallet is called out: the victim's funds were a
# small part of what that wallet was moving.
DILUTED = 0.25

IncomingBetween = Callable[[str, int, int, int, int], tuple[list[Any], bool]]


def _field(tx: Any, name: str) -> Any:
    return tx.get(name) if isinstance(tx, dict) else getattr(tx, name, None)


def _within(txs: list[dict[str, Any]], end_block: int, end_ts: int) -> list[dict[str, Any]]:
    """`txs` at or before the window's end -- by block where the chain gives
    one, by time where it does not (Tron)."""
    return [t for t in txs
            if (t["block_number"] <= end_block if t.get("block_number") else (t.get("timestamp") or 0) <= end_ts)]


def _missed(received: list[Any], own: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The route's own transfers the provider's list does not hold, so the
    denominator is the union of the two, each transfer once. A row without a
    hash stands for the route's transfer of the same value."""
    keys = {transfer_key(t) for t in received}
    hashless = Counter(transfer_key(t)[1] for t in received if not transfer_key(t)[0])
    out = []
    for t in own:
        key = transfer_key(t)
        if key in keys:
            continue
        if hashless[key[1]]:
            hashless[key[1]] -= 1
            continue
        out.append(t)
    return out


def _recycled(received: list[tuple[Any, str | None]], paid: list[Any], by_block: bool,
              ) -> tuple[float, dict[str, float]]:
    """Value that came back from wallets this one had paid earlier in the
    window (W -> X -> W): the wallet's own coins, not anyone else's. One pass
    in order; a payment counts before a return in the same block. A transfer
    from X that arrived before W paid X is new money and is not netted."""
    def pos(tx: Any) -> int:
        return int((_field(tx, "block_number") if by_block else _field(tx, "timestamp")) or 0)

    events = [(pos(t), 0, _field(t, "to_address"), float(_field(t, "value_native") or 0)) for t in paid]
    events += [(pos(t), 1, party, float(_field(t, "value_native") or 0)) for t, party in received]
    owed: dict[str, float] = defaultdict(float)
    via: dict[str, float] = defaultdict(float)
    for _, is_in, party, value in sorted(events, key=lambda e: (e[0], e[1])):
        if not party:
            continue
        if not is_in:
            owed[party] += value
            continue
        back = min(value, owed[party])
        if back > 0:
            owed[party] -= back
            via[party] += back
    return sum(via.values()), dict(via)


def estimate(graph: nx.DiGraph, path: list[str], incoming_between: IncomingBetween | None,
             flows_between: FlowsBetween | None = None) -> dict[str, Any]:
    """Pro-rata estimate of the reported funds reaching the end of `path`.

    `path` runs seed -> ... -> exchange in the direction the money moved.
    `incoming_between(address, start_block, end_block, start_ts, end_ts)`
    returns (transfers into address in that range, whether the read was
    complete). `flows_between`, when given, is read instead and also returns
    what the wallet paid out, so coins it got back from wallets it had paid
    are netted out. Never raises: a failed read is an "unknown", not a failed
    trace.
    """
    if len(path) < 2 or (len(path) > 2 and incoming_between is None and flows_between is None):
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
            return _unknown(sent, hops, f"the transfers through {wallet} carry neither blocks nor times "
                                        "to bound the window")
        start_block, end_block = (min(blocks_in), max(blocks_out)) if blocks_in and blocks_out else (0, 0)
        start_ts = min(times_in) if times_in else 0
        end_ts = max(times_out) if times_out else 0
        if (end_block < start_block) or (not blocks_in and end_ts < start_ts):
            return _unknown(sent, hops, f"{wallet} sent on before the traced funds arrived")

        try:
            if flows_between is not None:
                received, paid, complete = flows_between(wallet, start_block, end_block, start_ts, end_ts)
            else:
                (received, complete), paid = incoming_between(wallet, start_block, end_block, start_ts, end_ts), []
        except Exception as exc:  # noqa: BLE001 -- an estimate is never worth a failed trace
            return _unknown(sent, hops, f"{wallet}'s incoming transfers could not be read ({public_reason(exc)})")
        if not complete:
            return _unknown(sent, hops, f"{wallet} received too many transfers in the window to read in full")

        # A wallet paying itself moves nobody else's money.
        def to_itself(tx: Any) -> bool:
            return bool(_field(tx, "from_address")) and _field(tx, "from_address") == _field(tx, "to_address")
        self_sent = sum(float(_field(t, "value_native") or 0) for t in received if to_itself(t))
        received = [t for t in received if not to_itself(t)]
        paid = [t for t in paid if not to_itself(t)]

        # The traced funds that reached this wallet before it last sent on.
        edge_total = float(edge_in.get("value_native", 0.0)) or 1.0
        own_in = _within(txs_in, end_block, end_ts)
        in_window = sum(t.get("value_native", 0.0) for t in own_in)
        carried_in = carried * (in_window / edge_total)
        came_in = [(t, _field(t, "from_address")) for t in received]
        came_in += [(t, path[i - 1]) for t in _missed(received, own_in)]
        recycled, via = _recycled(came_in, paid, by_block=bool(blocks_in and blocks_out))
        total_in = max(sum(float(_field(t, "value_native") or 0) for t, _ in came_in) - recycled, in_window)
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
            # Netted out of what came in: sent to itself, or got back from
            # wallets it had paid in the window (largest first).
            "self_transfers": round(self_sent, 6),
            "recycled_in_window": round(recycled, 6),
            "recycled_via": [{"address": a, "value": round(v, 6)}
                             for a, v in sorted(via.items(), key=lambda kv: -kv[1])[:3]],
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


def _unknown(sent: float, hops: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    """No estimate. The wallets measured before the read failed are kept, and
    a small share at one of them is still called out."""
    lowest = min((h["victim_share"] for h in hops), default=None)
    return {"status": "unknown", "sent": sent, "hops": hops, "reason": reason,
            "lowest_share": lowest, "diluted": lowest is not None and lowest < DILUTED}
