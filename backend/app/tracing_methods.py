"""How much of the victim's money reached the exchange, by three methods (R4).

When a wallet on the path also holds other people's money, nothing on the chain
says which coins were whose. Courts and tracing practice answer with a rule,
and different rules give different answers. Pro-rata (app/prorata.py) is one.
This module adds the two others in common use, so a report can show the range
and a letter can state the smallest figure instead of picking a rule that
happens to suit it.

FIFO, first in, first out
    Money leaves a wallet in the order it arrived. Every transfer out takes
    from the oldest money still in the wallet. The victim's part of a transfer
    out is the victim's part of the money it took.

LIBR, lowest intermediate balance rule
    The victim's money stays in the wallet as long as the wallet holds enough
    to cover it. It leaves only when the balance falls below it, and once gone
    it does not come back when other money arrives later. The victim's part of
    a transfer out is how much the victim's money in the wallet fell because
    of it.

A worked example, for checking by hand. A wallet receives 40 of the victim's,
then 60 from someone else, then sends 50 to the exchange:

    FIFO   the 50 takes the oldest money: all 40 of the victim's, then 10 of
           the other.                                victim part 40
    LIBR   balance 100 falls to 50, which still covers the victim's 40, so
           none of it has to have left.              victim part 0
    pro-rata the victim is 40% of what came in.      victim part 20

All three read the same window as pro-rata: every transfer into and out of the
wallet from the moment the traced money first arrived to the moment the wallet
last sent it on along the path.

What none of them can see, and the result says so: money the wallet held
before the window. A transfer out that is larger than everything that came in
during the window is paid partly from that unseen money, and is reported as
`unseen_outflow`. Both rules here treat the unseen money as nobody's victim
funds. Transfers in the same block (or the same second, on Tron) have no
order in the providers' lists. They are taken incoming first, so money can
arrive and leave in one block.

A wallet whose window could not be read in full gives "unknown" for both
methods, never a number from part of the picture. Nothing here raises: an
estimate is never worth a failed trace.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Callable, Iterable

import networkx as nx

from .provider_errors import public_reason

FIFO = "fifo"
LIBR = "libr"
METHODS = (FIFO, LIBR)

# Floating-point dust below this is treated as zero.
EPSILON = 1e-12

# (address, start_block, end_block, start_ts, end_ts) ->
#     (transfers in, transfers out, whether the read was complete)
FlowsBetween = Callable[[str, int, int, int, int], tuple[list[Any], list[Any], bool]]


def compare(
    graph: nx.DiGraph, path: list[str], flows_between: FlowsBetween | None,
    prorata: dict[str, Any] | None = None, seed_cap: float | None = None,
) -> dict[str, Any]:
    """FIFO and LIBR along `path`, beside the pro-rata result already computed.

    `path` runs seed -> ... -> exchange in the direction the money moved.
    Returns one result per method, plus the range across every method that
    produced a figure and the smallest of them (`conservative`). `seed_cap`
    limits the victim's part of the first hop as in prorata.estimate (the
    reported payments, or a swap's output), so no method states more.
    """
    reader = read_once(flows_between) if flows_between else None
    results = {method: _trace(graph, path, reader, method, seed_cap) for method in METHODS}
    figures = {m: r["estimated"] for m, r in results.items() if r["status"] == "estimated"}
    if prorata and prorata.get("status") == "estimated":
        figures["prorata"] = float(prorata["estimated"])
    out: dict[str, Any] = {**results, "figures": figures}
    if figures:
        low = min(figures.values())
        out["range"] = {"low": round(low, 6), "high": round(max(figures.values()), 6)}
        out["conservative"] = round(low, 6)
        out["conservative_method"] = min(figures, key=figures.get)
    else:
        out["range"] = None
        out["conservative"] = None
        out["conservative_method"] = None
    return out


def read_once(flows_between: FlowsBetween) -> FlowsBetween:
    """Pro-rata and both methods read the same wallets over the same windows:
    one API call each, shared (pipeline.run_trace passes one reader to all)."""
    seen: dict[tuple, Any] = {}

    def read(*window: Any) -> tuple[list[Any], list[Any], bool]:
        if window not in seen:
            try:
                seen[window] = flows_between(*window)
            except Exception as exc:  # noqa: BLE001 -- replayed to the second method too
                seen[window] = exc
        if isinstance(seen[window], Exception):
            raise seen[window]
        return seen[window]
    return read


def _trace(graph: nx.DiGraph, path: list[str], flows_between: FlowsBetween | None, method: str,
           seed_cap: float | None = None) -> dict[str, Any]:
    if len(path) < 2:
        return {"status": "not_applicable"}
    first = _edge_txs(graph, path[0], path[1])
    sent = sum(t["value_native"] for t in first)
    if sent <= 0:
        return {"status": "not_applicable"}
    if len(path) > 2 and flows_between is None:
        return {"status": "not_applicable"}

    # The victim's part of each transfer on the edge being followed. Everything
    # the reported wallet sent along the path counts as the victim's, as in
    # pro-rata -- scaled down to the cap when one is given.
    start = min(sent, seed_cap) if seed_cap is not None else sent
    victim = {transfer_key(t): t["value_native"] * (start / sent) for t in first}
    hops: list[dict[str, Any]] = []
    for i in range(1, len(path) - 1):
        wallet = path[i]
        arriving = _edge_txs(graph, path[i - 1], wallet)
        leaving = _edge_txs(graph, wallet, path[i + 1])
        window = _window(arriving, leaving)
        if window is None:
            return _unknown(sent, hops, f"{wallet} sent on before the traced funds arrived, "
                                         "or its transfers carry neither blocks nor times")
        start_block, end_block, start_ts, end_ts = window
        try:
            incoming, outgoing, complete = flows_between(wallet, start_block, end_block, start_ts, end_ts)
        except Exception as exc:  # noqa: BLE001 -- an estimate is never worth a failed trace
            return _unknown(sent, hops, f"{wallet}'s transfers could not be read ({public_reason(exc)})")
        if not complete:
            return _unknown(sent, hops, f"{wallet} moved too many transfers in the window to read in full")

        events = _events(incoming, outgoing, arriving, leaving, window, victim, path[i - 1], path[i + 1])
        apply = _fifo if method == FIFO else _libr
        victim_out, unseen = apply(events, {transfer_key(t) for t in leaving})
        victim_in = sum(victim.get(transfer_key(t), 0.0) for t in arriving)
        victim = victim_out
        hops.append({
            "address": wallet,
            "victim_in": round(victim_in, 6),
            "received_in_window": round(sum(e["value"] for e in events if e["in"]), 6),
            "sent_in_window": round(sum(e["value"] for e in events if not e["in"]), 6),
            "sent_on": round(sum(t["value_native"] for t in leaving), 6),
            "victim_on": round(sum(victim_out.values()), 6),
            "unseen_outflow": round(unseen, 6),
        })

    last = _edge_txs(graph, path[-2], path[-1])
    estimated = sum(victim.get(transfer_key(t), 0.0) for t in last)
    return {
        "status": "estimated",
        "method": method,
        "sent": round(sent, 6),
        "estimated": round(estimated, 6),
        "ratio": round(min(1.0, estimated / start), 4) if start > 0 else 0.0,
        "unseen_outflow": any(h["unseen_outflow"] > 0 for h in hops),
        "hops": hops,
    }


def _returned(e: dict[str, Any], owed: dict[str, float]) -> float:
    """The victim's part of a transfer in: its own, plus what the wallet had
    paid of the victim's to this same counterparty earlier in the window and
    is now getting back (W -> X -> W carries the coins' history with it)."""
    back = min(e["value"] - e["victim"], owed.get(e["party"], 0.0)) if e["party"] else 0.0
    if back > 0:
        owed[e["party"]] -= back
    return e["victim"] + max(0.0, back)


def _fifo(events: list[dict[str, Any]], path_out: set[tuple]) -> tuple[dict[tuple, float], float]:
    """Each transfer out takes the oldest money first. Returns the victim's
    part of each transfer out along the path, and the unseen outflow."""
    queue: deque[list[float]] = deque()  # [amount left, victim part of it]
    victim_out: dict[tuple, float] = {}
    owed: dict[str, float] = {}
    unseen = 0.0
    for e in events:
        if e["in"]:
            queue.append([e["value"], _returned(e, owed)])
            continue
        need, taken = e["value"], 0.0
        while need > EPSILON and queue:
            lot = queue[0]
            take = min(need, lot[0])
            share = lot[1] * (take / lot[0]) if lot[0] > EPSILON else 0.0
            lot[0] -= take
            lot[1] -= share
            taken += share
            need -= take
            if lot[0] <= EPSILON:
                queue.popleft()
        unseen += max(0.0, need)
        if e["party"]:
            owed[e["party"]] = owed.get(e["party"], 0.0) + taken
        if e["key"] in path_out:
            victim_out[e["key"]] = taken
    return victim_out, unseen


def _libr(events: list[dict[str, Any]], path_out: set[tuple]) -> tuple[dict[tuple, float], float]:
    """The victim's money leaves only when the balance drops below it."""
    balance = victim_left = unseen = 0.0
    victim_out: dict[tuple, float] = {}
    owed: dict[str, float] = {}
    for e in events:
        if e["in"]:
            balance += e["value"]
            victim_left += _returned(e, owed)
            continue
        before = victim_left
        if e["value"] > balance:
            unseen += e["value"] - balance
        balance = max(0.0, balance - e["value"])
        victim_left = min(victim_left, balance)
        if e["party"]:
            owed[e["party"]] = owed.get(e["party"], 0.0) + before - victim_left
        if e["key"] in path_out:
            victim_out[e["key"]] = before - victim_left
    return victim_out, unseen


# ---------------------------------------------------------------------------
# The window and its events
# ---------------------------------------------------------------------------
def _edge_txs(graph: nx.DiGraph, a: str, b: str) -> list[dict[str, Any]]:
    edge = graph.edges[a, b]
    txs = [t for t in edge.get("transactions") or [] if float(t.get("value_native") or 0) > 0]
    if txs:
        return [{**t, "value_native": float(t["value_native"])} for t in txs]
    # An edge without its transfers listed: one transfer of the edge's value.
    value = float(edge.get("value_native") or 0)
    return [{"hash": f"{a}->{b}", "value_native": value,
             "block_number": None, "timestamp": edge.get("first_seen")}] if value > 0 else []


def transfer_key(tx: Any) -> tuple:
    """A transfer's identity: one hash can carry several token transfers."""
    value = _get(tx, "value_native")
    return (str(_get(tx, "hash") or "").lower(), round(float(value or 0), 9))


def _get(tx: Any, name: str) -> Any:
    return tx.get(name) if isinstance(tx, dict) else getattr(tx, name, None)


def _position(tx: Any, by_block: bool) -> int:
    return int((_get(tx, "block_number") if by_block else _get(tx, "timestamp")) or 0)


def _window(arriving: list[dict[str, Any]], leaving: list[dict[str, Any]]) -> tuple[int, int, int, int] | None:
    """(start_block, end_block, start_ts, end_ts), as pro-rata bounds it."""
    blocks_in = [t["block_number"] for t in arriving if t.get("block_number")]
    blocks_out = [t["block_number"] for t in leaving if t.get("block_number")]
    times_in = [t["timestamp"] for t in arriving if t.get("timestamp")]
    times_out = [t["timestamp"] for t in leaving if t.get("timestamp")]
    if not (blocks_in and blocks_out) and not (times_in and times_out):
        return None
    start_block, end_block = (min(blocks_in), max(blocks_out)) if blocks_in and blocks_out else (0, 0)
    start_ts, end_ts = (min(times_in) if times_in else 0), (max(times_out) if times_out else 0)
    if (blocks_in and blocks_out and end_block < start_block) or (not blocks_in and end_ts < start_ts):
        return None
    return start_block, end_block, start_ts, end_ts


def _events(
    incoming: Iterable[Any], outgoing: Iterable[Any],
    arriving: list[dict[str, Any]], leaving: list[dict[str, Any]],
    window: tuple[int, int, int, int], victim: dict[tuple, float],
    came_from: str | None = None, goes_to: str | None = None,
) -> list[dict[str, Any]]:
    """Every transfer in and out of the wallet in the window, in order.

    The path's own transfers are added if the provider's list missed them (an
    internal transfer, for one), so the method always sees the money it follows.
    A transfer from the wallet to itself is not an event: it moves nothing,
    and as a lot it pushed the victim's coins out first (FIFO went to 0). Each
    event keeps its counterparty (`party`) so coins paid out and returned
    keep their history.
    """
    start_block, end_block, start_ts, end_ts = window
    by_block = end_block > 0

    def inside(tx: Any) -> bool:
        pos = _position(tx, by_block)
        return (start_block <= pos <= end_block) if by_block else (start_ts <= pos <= end_ts)

    events: dict[tuple, dict[str, Any]] = {}
    for is_in, read, own, own_party in ((True, incoming, arriving, came_from), (False, outgoing, leaving, goes_to)):
        for tx, party in [*((t, _get(t, "from_address" if is_in else "to_address")) for t in read),
                          *((t, own_party) for t in own)]:
            key = (is_in, *transfer_key(tx))
            if key in events or not inside(tx):
                continue
            if _get(tx, "from_address") and _get(tx, "from_address") == _get(tx, "to_address"):
                continue
            value = float(_get(tx, "value_native") or 0)
            if value <= 0:
                continue
            events[key] = {"in": is_in, "key": transfer_key(tx), "value": value, "pos": _position(tx, by_block),
                           "party": party,
                           "victim": min(value, victim.get(transfer_key(tx), 0.0)) if is_in else 0.0}
    # Incoming first within one block or second: the lists give no order there.
    return sorted(events.values(), key=lambda e: (e["pos"], 0 if e["in"] else 1))


def _unknown(sent: float, hops: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    return {"status": "unknown", "sent": round(sent, 6), "hops": hops, "reason": reason}
