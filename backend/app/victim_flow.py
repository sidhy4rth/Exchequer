"""Where the victim's share went, on every branch the trace followed.

Pro-rata (app/prorata.py) follows one route: the reported wallet to the
exchange the case names. The flow applies the same rule to every branch, so
a picture of the case can be sized by the victim's money instead of by
everything that moved.

How it works, in order:

  * The start is the case's denominator (`materiality.denominator`): what the
    reported wallet sent as the trace saw it, or the reported payments when
    the victim gave them. It is split across the wallet's transfers out in
    proportion to their value; what it sent to counterparties the trace did
    not follow is "not followed". An older case does not list that money: a
    wallet its fan-out limit cut keeps nothing, and what it did not send on
    the followed links is "not followed" too.
  * Each wallet's window runs from the first victim money in to its last
    transfer out (on the lead route, its last transfer along the route, as
    pro-rata reads it). Money that arrives later stays in the wallet. Its
    share is the victim money in the window over all the money in it: on the
    lead route that is pro-rata's own chain read
    (`received_in_window`); elsewhere only the transfers the trace followed
    are known, so the denominator is the larger of what came in and what went
    out (`traced_only`), and the share is an upper bound. Each transfer out
    carries its value times the share, never more than came in. What the
    wallet did not send on stays "left", or "held" at a wallet that is
    frozen, sanctioned or seized.
  * The money ends at an exchange (including an inferred deposit address),
    a mixer ("risk"), a wallet the trace did not expand ("beyond the limit"),
    or "other": a swap, or money that came back to a wallet earlier on the
    route, which is counted once. Every bucket together is the start.

On the lead route the next link keeps pro-rata's own figure and the
wallet's other transfers share what is left, so the money that took that
route is exactly pro-rata's estimate. That holds at the reported wallet
too: when the start is less than it sent (money came back to it, or the
victim reported paying less), its link on the route keeps its value, as
pro-rata's start does. Only a cap below that link's value (the reported
payments or a swap's output; pro-rata's `seed_cap.applied`) scales its
whole split, the route's link with the rest.

Its limits: money a wallet held before the victim's arrived is not seen; off
the lead route the shares are upper bounds; where the case does not list a
link's transfers, the window uses the link's first and last times
(`edge_bounds`). It is a display. Letters and the score keep
`estimates.conservative`, and nothing here changes them.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable, Mapping

from .prorata import DILUTED

# Which build() made a flow. Bump it whenever build() changes what it gives:
# a stored flow of an older version (or none) is rebuilt on read, from the
# stored case, whose transfers may be trimmed (with_flow, contracts.upgrade).
VERSION = 1

KINDS = ("exchange", "held", "left", "risk", "beyond_limit", "not_followed", "other")
ACTIONS = {"exchange": "draft_letter", "held": "ask_issuer", "left": "watch", "beyond_limit": "trace_deeper"}
HOLDS = frozenset({"frozen", "sanctioned", "seized"})
UPPER = frozenset({"traced_only", "edge_bounds"})
CUT = re.compile(r"(?:fan-out limit|safety cap) of \d+ counterparties per address applied at (\S+?)\.\.\.")

# A transfer, or a whole link when its transfers are not listed:
# (block or None, earliest time, latest time, value).
Piece = tuple[Any, int, int, float]


def build(result: Any, received_in_window: Mapping[str, float] | None = None) -> dict[str, Any]:
    """The victim's share on every branch of a stored or fresh case. Never raises.

    `received_in_window` adds chain reads of wallets' inflow in their windows
    ({address: amount}); pro-rata's own hops are read from the case. Every
    flow carries the `version` of the build that made it.
    """
    return {"version": VERSION, **_build(result, received_in_window)}


def is_current(flow: Any) -> bool:
    """Whether a flow a case carries came from this build (or a later one)."""
    version = flow.get("version") if isinstance(flow, dict) else None
    return isinstance(version, int) and version >= VERSION


def _build(result: Any, received_in_window: Mapping[str, float] | None) -> dict[str, Any]:
    try:
        direction = result.get("direction", "outgoing")
        if direction == "incoming":
            return {"status": "not_applicable"}
        if direction != "outgoing":
            return _unavailable("the case does not say which way the money moved")
        return _Flow(result, dict(received_in_window or {})).run()
    except Exception:  # noqa: BLE001 -- a display is never worth a failed case
        return _unavailable("the case's graph could not be read")


def with_flow(result: dict[str, Any]) -> dict[str, Any]:
    """`result` with its `victim_flow`, and each follow-on's, as upgrade()
    gives them: a current one the case carries wins, else one built now.

    The input is never changed: new top levels, never a deep copy. A route
    passes the copy its reader may see (case_privacy.for_reader), so the flow
    is built only from what that reader is shown."""
    out = result if is_current(result.get("victim_flow")) else {**result, "victim_flow": build(result)}
    ons = out.get("follow_ons")
    if not isinstance(ons, list):
        return out
    return {**out, "follow_ons": [{**f, "result": with_flow(f["result"])}
                                  if isinstance(f, dict) and isinstance(f.get("result"), dict) else f
                                  for f in ons]}


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason}


def _after(p: Piece, start: tuple[Any, int] | None) -> bool:
    return start is None or (p[0] >= start[0] if p[0] and start[0] else p[2] >= start[1])


def _before(p: Piece, end: tuple[Any, int] | None) -> bool:
    return end is None or (p[0] <= end[0] if p[0] and end[0] else p[1] <= end[1])


def _bound(pieces: list[Piece], low: bool) -> tuple[Any, int] | None:
    if not pieces:
        return None
    pick = min if low else max
    blocks = [p[0] for p in pieces]
    return (pick(blocks) if all(blocks) else None, pick(p[1] if low else p[2] for p in pieces))


class _Flow:
    def __init__(self, result: dict[str, Any], reads: dict[str, float]) -> None:
        self.r, self.reads, self.seed = result, reads, result["address"]
        self.nodes = {n["address"]: n for n in result["graph"]["nodes"]}
        self.edges = {(e["source"], e["target"]): e for e in result["graph"]["edges"]}
        self.out: dict[str, list[str]] = defaultdict(list)
        self.inn: dict[str, list[str]] = defaultdict(list)
        for s, t in self.edges:
            self.out[s].append(t)
            self.inn[t].append(s)
        self.untraced: dict[str, float] = defaultdict(float)
        for u in result.get("untraced") or []:
            self.untraced[u["address"]] += float(u.get("value_native") or 0)
        # Wallets whose outflow the fan-out limit cut, in a case too old to
        # say how much: their reasons name them by prefix.
        self.cut = set() if "untraced" in result else {
            m.group(1) for x in result.get("truncation_reasons") or [] for m in [CUT.search(str(x))] if m}
        rows: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for t in result.get("transfers") or []:
            rows[(t.get("from"), t.get("to"))].append(t)
        trimmed = bool(result.get("transfers_omitted"))
        self.pieces: dict[tuple[str, str], list[Piece]] = {}
        self.bounded: set[tuple[str, str]] = set()
        for key, e in self.edges.items():
            listed = rows.get(key, [])
            if listed and (not trimmed or len(listed) >= int(e.get("tx_count") or 0)):
                self.pieces[key] = [(t.get("block") or None, t.get("timestamp") or 0, t.get("timestamp") or 0,
                                     float(t.get("value_native") or 0)) for t in listed]
            else:
                self.bounded.add(key)
                self.pieces[key] = [(None, e.get("first_seen") or 0, e.get("last_seen") or 0, self._value(key))]
        self.inferred = {m.get("address") for m in result.get("inferred_deposits") or []}
        self.inferred |= {a for a, n in self.nodes.items() if n.get("inferred_exchange") and not n.get("exchange")}
        self.exchanges = self.inferred | {m.get("address") for m in result.get("matches") or []}
        self.exchanges |= {a for a, n in self.nodes.items() if n.get("exchange")}

    def _value(self, key: tuple[str, str]) -> float:
        return float(self.edges[key].get("value_native") or 0)

    def _part(self, key: tuple[str, str], keep: Callable[[Piece], bool]) -> float:
        """The link's value that `keep` accepts, as part of the link's value."""
        ps = self.pieces[key]
        total = sum(p[3] for p in ps)
        return self._value(key) * (sum(p[3] for p in ps if keep(p)) / total if total > 0 else 1.0)

    def _expanded(self, a: str) -> bool:
        n, r = self.nodes[a], self.r
        if "expanded" in n:
            return bool(n["expanded"])
        if self.out[a] or a in self.untraced:
            return True
        if r.get("max_depth") is not None and int(n.get("depth") or 0) >= int(r["max_depth"]):
            return False
        reasons = [str(x) for x in r.get("truncation_reasons") or []]
        if any(a[:10] in x for x in reasons):
            return False
        return not (r.get("stopped_by") or r.get("addresses_unexpanded_by_time")
                    or r.get("addresses_unexpanded_by_budget") or any(x.startswith("node limit") for x in reasons))

    def _kind(self, a: str) -> str | None:
        """The bucket for money that reaches `a`, or None for a wallet it passes through."""
        n = self.nodes[a]
        if a in self.exchanges:
            return "exchange"
        if n.get("risk_category") == "mixer":
            return "risk"
        if n.get("is_router"):
            return "other"
        if n.get("is_service_contract"):
            return "not_followed"
        return None if self._expanded(a) else "beyond_limit"

    def _order(self, kinds: dict[str, str | None], lead_next: dict[str, str]) -> tuple[list[str], set]:
        """Depth-first from the reported wallet, lead route first: the links
        that point back up the walk, and the wallets in topological order."""
        def succ(u: str) -> list[str]:
            if u != self.seed and kinds[u]:
                return []
            return sorted(self.out[u], key=lambda t: (t != lead_next.get(u), -self._value((u, t)), t))
        state, order, back = {self.seed: 1}, [], set()
        stack = [(self.seed, iter(succ(self.seed)))]
        while stack:
            u, it = stack[-1]
            v = next(it, None)
            if v is None:
                stack.pop()
                state[u] = 2
                order.append(u)
            elif state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                state[v] = 1
                stack.append((v, iter(succ(v))))
        return order[::-1], back

    def run(self) -> dict[str, Any]:
        r, seed = self.r, self.seed
        if seed not in self.nodes:
            return _unavailable("the reported address is not in the case's graph")
        mat = r.get("materiality") or {}
        start = float(mat.get("denominator") or 0)
        basis = (mat.get("basis") if start > 0 else None) or "seed_outflow"
        if start <= 0:
            out = [self._value((seed, t)) for t in self.out[seed]]
            back_in = sum(self._value((s, seed)) for s in self.inn[seed])
            start = max(max(out), sum(out) + self.untraced[seed] - back_in) if out else self.untraced[seed]
        if start <= 0:  # an outgoing trace, so it says why: not a reverse one
            return {"status": "not_applicable", "reason": "the reported wallet sent nothing the trace saw"}
        prorata = r.get("prorata") or {}
        chain = {h["address"]: float(h["received_in_window"]) for h in prorata.get("hops") or []
                 if h.get("received_in_window")}
        path = [s.get("address") for s in r.get("trace_path") or []]
        lead_next = dict(zip(path, path[1:], strict=False)) if path[:1] == [seed] else {}
        kinds = {a: (None if a == seed else self._kind(a)) for a in self.nodes}
        order, back = self._order(kinds, lead_next)

        vin: dict[str, float] = defaultdict(float)
        vin[seed] = start
        victim: dict[tuple[str, str], float] = {}
        kept: dict[tuple[str, str], float] = {}  # the part of an in-link inside its target's window
        inside: dict[str, float] = {}
        info: dict[str, dict[str, Any]] = {}
        amounts = {k: defaultdict(float) for k in KINDS}
        for w in order:
            if kinds[w]:
                amounts[kinds[w]][w] += vin[w]
                info[w] = {"role": kinds[w], "share": None, "basis": None, "left": 0.0}
                continue
            feeds = [s for s in self.inn[w] if (s, w) in victim and (s, w) not in back]
            begin = None if w == seed else _bound(
                [p for s in feeds if victim.get((s, w), 0) > 0 for p in self.pieces[(s, w)]], low=True)
            nxt = lead_next.get(w)
            last = [p for t in ([nxt] if nxt in self.out[w] else self.out[w])
                    for p in self.pieces[(w, t)] if _after(p, begin)]
            end = None if w == seed or not last else _bound(last, low=False)

            def within(p: Piece, begin: Any = begin, end: Any = end) -> bool:
                return _after(p, begin) and _before(p, end)
            for s in feeds:
                kept[(s, w)] = self._part((s, w), within) / (self._value((s, w)) or 1.0)
            inside[w] = vin[w] if w == seed else sum(victim[(s, w)] * kept[(s, w)] for s in feeds)
            gross = {t: self._part((w, t), lambda p, b=begin: _after(p, b)) for t in self.out[w]}
            sent = sum(gross.values()) + self.untraced[w]
            loose = any(k in self.bounded for k in [*((s, w) for s in feeds), *((w, t) for t in gross)])
            if w == seed:
                den, how = sent, basis
            elif self.reads.get(w):
                den, how = self.reads[w], "read"
            elif chain.get(w):
                den, how = chain[w], "prorata"
            else:
                came = sum(self._part((s, w), within) for s in self.inn[w] if (s, w) not in back)
                den, how = max(came, sent), "edge_bounds" if loose else "traced_only"
            share = min(1.0, inside[w] / den) if den > 0 else 0.0
            # On the lead route the next link keeps pro-rata's own figure (at
            # the reported wallet its whole value, unless a cap below it
            # scales the split); the rest share what is left, never more
            # than came in.
            lead = nxt in gross and (w != seed or basis == "seed_outflow" or start >= gross[nxt])
            first = min(inside[w], gross[nxt] * (1.0 if w == seed else share)) if lead else 0.0
            rest = (sent - gross[nxt] if lead else sent) * share
            scale = (inside[w] - first) / rest if rest > inside[w] - first else 1.0
            for t, g in gross.items():
                victim[(w, t)] = v = first if lead and t == nxt else g * share * scale
                if (w, t) in back or self.edges[(w, t)].get("swap"):
                    amounts["other"][t] += v
                else:
                    vin[t] += v
            amounts["not_followed"][w] += self.untraced[w] * share * scale
            left = max(0.0, vin[w] - first - rest * scale)
            where = ("not_followed" if any(w.startswith(c) for c in self.cut)
                     else "held" if self.nodes[w].get("risk_category") in HOLDS else "left")
            amounts[where][w] += left
            info[w] = {"role": "seed" if w == seed else "wallet", "share": share, "basis": how,
                       "left": 0.0 if where == "not_followed" else left, "lead": lead,
                       # Each stored amount is rounded to 6 places on its own,
                       # so the start can miss what was sent by a few 1e-7.
                       "short": w == seed and sent - start > 1e-6 * (2 + len(gross) + len(self.inn[w]))}

        reached = None
        if len(path) > 1 and all((a, b) in victim for a, b in zip(path, path[1:], strict=False)):
            reached = victim[(path[0], path[1])]
            for prev, w, nxt in zip(path, path[1:], path[2:], strict=False):
                reached *= kept.get((prev, w), 0.0) * victim[(w, nxt)] / inside[w] if inside[w] > 0 else 0.0
        return self._shape(start, basis, order, info, vin, victim, back, amounts, path, reached)

    def _shape(self, start, basis, order, info, vin, victim, back, amounts, path, reached) -> dict[str, Any]:
        def style(s: str, t: str) -> str:
            if info[s]["basis"] in UPPER or t in self.inferred:
                return "dashed"
            return "faded" if info[s]["share"] < DILUTED else "solid"
        buckets = []
        for kind in KINDS:
            amount = sum(amounts[kind].values(), 0.0)
            buckets.append({"kind": kind, "amount": _r(amount), "share": round(amount / start, 6),
                            "addresses": [a for a, v in sorted(amounts[kind].items(), key=lambda kv: (-kv[1], kv[0]))
                                          if v > 1e-9],
                            "action": ACTIONS.get(kind)})
        bases = {i["basis"] for i in info.values()}
        notes = ["A display of where the victim's share may have gone. Letters state the conservative "
                 "estimate, not these figures."]
        if bases & UPPER:
            notes.append("Off the lead route a wallet's share counts only the money the trace followed into "
                         "it, so those figures are upper bounds and drawn dashed.")
        if "edge_bounds" in bases:
            notes.append("Some transfers are not listed in the case, so those wallets' windows use each "
                         "link's first and last transfer times.")
        if any(victim[k] > 0 for k in back):
            notes.append("Some money came back to a wallet earlier on the route. It is counted once, "
                         "under other.")
        seed = info[self.seed]
        if not seed["share"]:
            notes.append("The trace saw no transfer out of the reported wallet, so the money is shown "
                         "still there.")
        elif seed["short"] and seed["lead"]:
            why = ("Money came back to the reported wallet, so the starting figure is less than it sent"
                   if basis == "seed_outflow" and any(self._value((s, self.seed)) > 0 for s in self.inn[self.seed])
                   else "The reported wallet sent more than the starting figure")
            notes.append(f"{why}. Its transfer on the route to the exchange keeps its value, as pro-rata's "
                         "does, and its other transfers share the rest.")
        elif seed["short"]:
            notes.append("The reported wallet sent more than the starting figure, so each of its transfers "
                         "carries only that part of it.")
        return {
            "status": "estimated",
            "method": "prorata",
            "nodes": [{"address": a, "role": info[a]["role"], "victim_in": _r(vin[a]),
                       "share": None if info[a]["share"] is None else round(info[a]["share"], 6),
                       "basis": info[a]["basis"], "left": _r(info[a]["left"])} for a in order],
            "links": [{"source": s, "target": t, "gross": _r(self._value((s, t))), "victim": _r(v),
                       "style": style(s, t)} for (s, t), v in victim.items()],
            "buckets": buckets,
            "totals": {"denominator": _r(start), "basis": basis, "accounted": _r(sum(b["amount"] for b in buckets))},
            "lead": {"path": path, "reached": None if reached is None else _r(reached)},
            "passed_through": [{"address": a, "category": self.nodes[a].get("risk_category"),
                                "victim_in": _r(vin[a])}
                               for a in order if info[a]["role"] == "wallet" and self.nodes[a].get("risk_category")
                               and vin[a] > 0],
            "notes": notes,
        }


def _r(x: float) -> float:
    return round(x, 9)
