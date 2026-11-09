"""The victim's share across every branch (app/victim_flow.py).

Demo 11 is the case the design pack drew wrong: worked by hand, pro-rata on
every branch sends 959.58 of the 9,891 to Binance (635 along the lead path,
324.58 through TZ7L), not 635 + 765. The rest are properties every recorded
case must keep, and small graphs for the shapes the demos do not have.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.victim_flow import build

BACKEND = Path(__file__).resolve().parent.parent
DEMOS = json.loads((BACKEND / "data" / "recorded_demos.json").read_text())
BY_DEMO = {d["demo"]: d["result"] for d in DEMOS}
FIXTURES = {p.name: json.loads(p.read_text())
            for p in sorted((BACKEND / "tests" / "fixtures" / "contract").glob("*.json")) if p.name != "index.json"}
CASES = {**{f"demo {n}": r for n, r in BY_DEMO.items()}, **FIXTURES}

TT4Y = "TT4yg2GguWvN5j8Xeb7nUB5Hg2wWd1dFp3"
TZ7L = "TZ7LmC6zBipRx6tDMavbzaF8piBpw89cNz"


def bucket(flow, kind):
    return next(b for b in flow["buckets"] if b["kind"] == kind)


def node(flow, address):
    return next(n for n in flow["nodes"] if n["address"] == address)


def link(flow, source, target):
    return next(lk for lk in flow["links"] if (lk["source"], lk["target"]) == (source, target))


# --- demo 11 -------------------------------------------------------------

def test_demo_11_buckets_match_the_hand_worked_figures():
    flow = build(BY_DEMO[11])
    assert flow["status"] == "estimated" and flow["method"] == "prorata"
    assert flow["totals"]["denominator"] == 9891.0
    assert round(bucket(flow, "exchange")["amount"], 2) == 959.58
    assert round(bucket(flow, "beyond_limit")["amount"], 2) == 8732.34
    assert round(bucket(flow, "not_followed")["amount"], 2) == 196.78
    assert round(bucket(flow, "left")["amount"], 6) == 2.297459
    assert bucket(flow, "left")["addresses"] == [TT4Y]
    assert bucket(flow, "held")["amount"] == 0
    assert round(bucket(flow, "exchange")["share"], 3) == 0.097
    assert bucket(flow, "exchange")["action"] == "draft_letter"


def test_demo_11_tz7l_is_a_marker_not_a_bucket():
    flow = build(BY_DEMO[11])
    marker = next(p for p in flow["passed_through"] if p["address"] == TZ7L)
    assert marker["category"] == "frozen" and marker["victim_in"] == 765.0
    # Its share is an upper bound: only what the trace followed in.
    tz7l = node(flow, TZ7L)
    assert tz7l["basis"] == "traced_only" and round(tz7l["share"], 3) == 0.162
    via = link(flow, TZ7L, "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU")
    assert round(via["victim"], 2) == 324.58 and via["style"] == "dashed"
    assert round(node(flow, TT4Y)["left"], 6) == 2.297459


def test_demo_11_lead_path_is_the_prorata_estimate():
    flow = build(BY_DEMO[11])
    assert flow["lead"]["path"][0] == BY_DEMO[11]["address"]
    assert flow["lead"]["path"][-1] == BY_DEMO[11]["exchange_address"]
    assert flow["lead"]["reached"] == pytest.approx(635.0, abs=1e-6)


# --- properties over every recording and fixture ---------------------------

@pytest.mark.parametrize("name", sorted(CASES))
def test_conservation(name):
    result = CASES[name]
    flow = build(result)
    if result["direction"] != "outgoing":
        assert flow == {"status": "not_applicable"}
        return
    assert flow["status"] == "estimated", flow
    total = flow["totals"]["denominator"]
    assert total > 0
    assert sum(b["amount"] for b in flow["buckets"]) == pytest.approx(total, abs=1e-6)
    for lk in flow["links"]:
        assert 0 <= lk["victim"] <= lk["gross"] + 1e-9, lk
    sent = {}
    for lk in flow["links"]:
        sent[lk["source"]] = sent.get(lk["source"], 0.0) + lk["victim"]
    for n in flow["nodes"]:
        assert sent.get(n["address"], 0.0) + n["left"] <= n["victim_in"] + 1e-6, n


@pytest.mark.parametrize("name", sorted(CASES))
def test_lead_reached_is_the_prorata_estimate(name):
    result = CASES[name]
    prorata = result.get("prorata") or {}
    if (result["direction"] != "outgoing" or prorata.get("status") != "estimated"
            or (prorata.get("seed_cap") or {}).get("applied")):
        pytest.skip("no uncapped pro-rata estimate to agree with")
    # Money that came back to the reported wallet (demos 3 and 6) does not
    # shrink the route: its first link keeps its value, as pro-rata's does.
    assert build(result)["lead"]["reached"] == pytest.approx(prorata["estimated"], abs=1e-6)


def test_a_wallet_cut_by_the_fan_out_limit_did_not_keep_what_it_did_not_send():
    # Demo 2 predates `untraced`: the case only says the limit cut 0xc681's
    # outflow, so what it did not send on the followed links was not followed.
    flow = build(BY_DEMO[2])
    cut = "0xc68191d4d5ea55d3299c71107be135ac8b278f0a"
    assert cut in bucket(flow, "not_followed")["addresses"] and cut not in bucket(flow, "left")["addresses"]
    assert round(bucket(flow, "not_followed")["amount"], 4) == 107.8738
    assert node(flow, cut)["left"] == 0


# --- small graphs ----------------------------------------------------------

def case(edges, *, exchange=None, untraced=(), max_depth=3, prorata=None, materiality=None,
         drop_rows=(), frozen=(), direction="outgoing"):
    """A stored case from `edges`: (source, target, [(time, value), ...])."""
    depth = {"S": 0}
    for _ in edges:
        for s, t, _rows in edges:
            if s in depth and t not in depth:
                depth[t] = depth[s] + 1
    for s, t, _rows in edges:  # a wallet the trace reached some other way
        depth.setdefault(s, 1)
        depth.setdefault(t, 2)
    nodes = [{"address": a, "depth": d, "is_seed": a == "S", "is_terminal": a == exchange,
              "exchange": "Binance" if a == exchange else None,
              "risk_category": "frozen" if a in frozen else None} for a, d in depth.items()]
    graph_edges, transfers = [], []
    for s, t, rows in edges:
        graph_edges.append({"source": s, "target": t, "value_native": sum(v for _, v in rows),
                            "tx_count": len(rows), "first_seen": min(ts for ts, _ in rows),
                            "last_seen": max(ts for ts, _ in rows), "swap": None})
        if (s, t) not in drop_rows:
            transfers += [{"hash": f"{s}{t}{ts}", "from": s, "to": t, "value_native": v,
                           "timestamp": ts, "block": None} for ts, v in rows]
    return {"address": "S", "direction": direction, "max_depth": max_depth,
            "graph": {"nodes": nodes, "edges": graph_edges},
            "untraced": [{"address": a, "value_native": v} for a, v in untraced],
            "transfers": transfers, "transfers_omitted": 1 if drop_rows else 0,
            "trace_path": [{"address": "S"}, {"address": "A"}, {"address": exchange}] if exchange else [],
            "exchange_address": exchange, "prorata": prorata, "materiality": materiality,
            "matches": [{"address": exchange}] if exchange else [], "inferred_deposits": []}


def test_a_merge_adds_both_branches():
    flow = build(case([("S", "A", [(1, 60)]), ("S", "B", [(1, 40)]), ("A", "C", [(2, 60)]),
                       ("B", "C", [(2, 40)]), ("C", "E", [(3, 100)])], exchange="E", max_depth=4))
    assert node(flow, "C")["victim_in"] == 100
    assert bucket(flow, "exchange") == {"kind": "exchange", "amount": 100, "share": 1.0,
                                        "addresses": ["E"], "action": "draft_letter"}


def test_money_back_to_the_reported_wallet_is_counted_once():
    # Sent 150, got 30 back: its outflow is 120. The route's link keeps its
    # 100, as pro-rata's does, and B carries the other 20.
    flow = build(case([("S", "A", [(1, 100)]), ("S", "B", [(1, 50)]), ("A", "S", [(2, 30)]),
                       ("A", "E", [(3, 70)])], exchange="E"))
    assert flow["totals"]["denominator"] == 120
    assert link(flow, "S", "A")["victim"] == 100 and link(flow, "S", "B")["victim"] == pytest.approx(20)
    assert bucket(flow, "other") == {"kind": "other", "amount": 30, "share": 0.25, "addresses": ["S"],
                                     "action": None}
    assert bucket(flow, "exchange")["amount"] == 70
    assert bucket(flow, "left")["addresses"] == ["B"]
    assert any("came back" in n for n in flow["notes"]) and any("keeps its value" in n for n in flow["notes"])
    assert not any("only that part" in n for n in flow["notes"])


def test_the_lead_link_keeps_the_prorata_figure_when_a_wallet_spends_more_than_came_in():
    # A had 50 of its own: it sent 100 on in the window but only 60 came in.
    lead = {"status": "estimated", "estimated": 60.0, "hops": [{"address": "A", "received_in_window": 60.0}]}
    flow = build(case([("S", "A", [(1, 60)]), ("A", "E", [(2, 70)]), ("A", "B", [(3, 30)])], exchange="E",
                      prorata=lead))
    assert link(flow, "A", "E")["victim"] == 60 and link(flow, "A", "B")["victim"] == 0
    assert flow["lead"]["reached"] == 60


# A's window is 1 to 5: the victim's late 40 stays in A, and X's 60 inside the
# window halves A's share. Without the window it would be 100 of 160 (75 / 25).
LATE = [("S", "A", [(1, 60), (10, 40)]), ("X", "A", [(2, 60)]), ("A", "E", [(5, 120)])]


def test_money_arriving_after_the_last_send_stays_in_the_wallet():
    flow = build(case(LATE, exchange="E"))
    assert node(flow, "A")["share"] == 0.5 and node(flow, "A")["basis"] == "traced_only"
    assert bucket(flow, "exchange")["amount"] == 60
    assert bucket(flow, "left") == {"kind": "left", "amount": 40, "share": 0.4, "addresses": ["A"],
                                    "action": "watch"}


def test_money_before_the_victim_arrived_is_not_in_the_window():
    # X's 60 reached A before the victim's money did: it does not dilute it.
    flow = build(case([("S", "A", [(2, 60)]), ("X", "A", [(1, 60)]), ("A", "E", [(5, 60)])], exchange="E"))
    assert node(flow, "A")["share"] == 1 and bucket(flow, "exchange")["amount"] == 60


def test_trimmed_transfers_fall_back_to_the_edge_bounds():
    flow = build(case(LATE, exchange="E", drop_rows={("S", "A")}))
    # Without the rows, the late 40 cannot be told apart: counted as in the window.
    assert node(flow, "A")["basis"] == "edge_bounds"
    assert link(flow, "A", "E")["style"] == "dashed"
    assert bucket(flow, "exchange")["amount"] == 75 and bucket(flow, "left")["amount"] == 25
    assert any("first and last" in n for n in flow["notes"])


def test_the_lead_wallet_reads_its_share_from_the_chain():
    lead = {"status": "estimated", "estimated": 25.0, "hops": [{"address": "A", "received_in_window": 400.0}]}
    flow = build(case([("S", "A", [(1, 100)]), ("A", "E", [(2, 100)])], exchange="E", prorata=lead))
    assert node(flow, "A")["basis"] == "prorata" and node(flow, "A")["share"] == 0.25
    assert flow["lead"] == {"path": ["S", "A", "E"], "reached": 25.0}
    assert bucket(flow, "left")["amount"] == 75 and link(flow, "S", "A")["style"] == "solid"
    # A read of the window handed in wins, and says it was read.
    read = build(case([("S", "A", [(1, 100)]), ("A", "E", [(2, 100)])], exchange="E", prorata=lead),
                 received_in_window={"A": 200.0})
    assert node(read, "A")["basis"] == "read" and read["lead"]["reached"] == 50.0


def test_a_cap_scales_the_split_and_money_kept_at_a_frozen_wallet_is_held():
    capped = {"basis": "reported_amount", "denominator": 50.0}
    flow = build(case([("S", "A", [(1, 100)]), ("A", "E", [(2, 100)])], exchange="E", materiality=capped))
    assert flow["totals"] == {"denominator": 50.0, "basis": "reported_amount", "accounted": 50.0}
    assert link(flow, "S", "A")["victim"] == 50 and bucket(flow, "exchange")["amount"] == 50
    assert any("only that part" in n for n in flow["notes"])
    over = {"basis": "reported_amount", "denominator": 150.0}
    flow = build(case([("S", "A", [(1, 100)]), ("A", "E", [(2, 100)])], exchange="E", materiality=over,
                      frozen={"S"}))
    assert bucket(flow, "held") == {"kind": "held", "amount": 50, "share": 0.333333, "addresses": ["S"],
                                    "action": "ask_issuer"}
    assert bucket(flow, "exchange")["amount"] == 100


def test_reported_payments_that_cover_the_route_do_not_shrink_it():
    # The victim paid 150; S sent 100 on the route and 100 to B. Pro-rata's
    # cap does not apply (150 >= 100), so the route keeps its 100 and B
    # carries the other 50, as when money comes back to S.
    paid = {"basis": "reported_amount", "denominator": 150.0}
    lead = {"status": "estimated", "estimated": 100.0,
            "seed_cap": {"amount": 150.0, "basis": "reported_amount", "applied": False}}
    flow = build(case([("S", "A", [(1, 100)]), ("S", "B", [(1, 100)]), ("A", "E", [(2, 100)])], exchange="E",
                      materiality=paid, prorata=lead))
    assert flow["lead"]["reached"] == lead["estimated"]
    assert link(flow, "S", "A")["victim"] == 100 and link(flow, "S", "B")["victim"] == 50
    assert bucket(flow, "exchange")["amount"] == 100 and bucket(flow, "left")["amount"] == 50
    assert any("sent more" in n and "keeps its value" in n for n in flow["notes"])
    assert not any("came back" in n or "only that part" in n for n in flow["notes"])


@pytest.mark.parametrize("exchange", ["E", None])
def test_a_rounding_gap_at_the_reported_wallet_is_not_a_note(exchange):
    # Each stored amount is rounded on its own: 2.000001 against 2.000002 sent.
    flow = build(case([("S", "A", [(1, 1.000001)]), ("S", "B", [(1, 1.000001)]), ("A", "E", [(2, 1.000001)])],
                      exchange=exchange, materiality={"basis": "seed_outflow", "denominator": 2.000001}))
    assert flow["status"] == "estimated"
    assert not any("came back" in n or "sent more" in n for n in flow["notes"]), flow["notes"]


def test_unfollowed_money_and_the_depth_limit():
    flow = build(case([("S", "A", [(1, 80)]), ("A", "B", [(2, 50)])], untraced=[("S", 20), ("A", 30)],
                      max_depth=2))
    assert bucket(flow, "not_followed")["amount"] == pytest.approx(20 + 80 * 30 / 80)
    assert bucket(flow, "not_followed")["addresses"] == ["A", "S"]
    assert bucket(flow, "beyond_limit") == {"kind": "beyond_limit", "amount": 50, "share": 0.5,
                                            "addresses": ["B"], "action": "trace_deeper"}


def test_an_older_case_cut_by_the_safety_cap_did_not_keep_it_either():
    old = case([("S", "A", [(1, 100)]), ("A", "B", [(2, 40)])])
    del old["untraced"]
    old["truncation_reasons"] = ["safety cap of 50 counterparties per address applied at A..., each "
                                 "carrying at least 1% of what it sent"]
    flow = build(old)
    assert bucket(flow, "not_followed")["amount"] == 60 and bucket(flow, "not_followed")["addresses"] == ["A"]
    assert bucket(flow, "left")["addresses"] == ["B"]
    old["untraced"] = []  # a newer case lists what it left: nothing, so A kept the 60
    assert bucket(build(old), "left")["amount"] == 100


def test_a_reported_wallet_that_has_not_sent_the_money_on_keeps_it():
    flow = build(case([], materiality={"basis": "reported_amount", "denominator": 50.0}))
    assert bucket(flow, "left") == {"kind": "left", "amount": 50, "share": 1.0, "addresses": ["S"],
                                    "action": "watch"}
    assert not any("sent more" in n for n in flow["notes"])
    assert any("no transfer out of the reported wallet" in n for n in flow["notes"])


def test_a_reverse_trace_has_no_victim_flow():
    assert build(case([("A", "S", [(1, 10)])], direction="incoming")) == {"status": "not_applicable"}


@pytest.mark.parametrize("bad", [None, [], {"direction": "outgoing"}, {"direction": "sideways"},
                                 {"direction": "outgoing", "address": "S", "graph": {"nodes": "x", "edges": 3}},
                                 {"direction": "outgoing", "address": "S", "graph": {"nodes": [], "edges": []}}])
def test_malformed_input_is_unavailable_never_an_error(bad):
    flow = build(bad)
    assert flow["status"] == "unavailable" and flow["reason"]
