"""FIFO and LIBR beside pro-rata (R4): worked examples that can be checked by hand.

Every example is a victim wallet V paying a middle wallet M, which also deals
with other wallets, and M paying the exchange X. Blocks are small integers so
the order of events is visible at a glance.
"""
from __future__ import annotations

from types import SimpleNamespace

import networkx as nx
import pytest

from app.prorata import estimate as estimate_prorata
from app.tracing_methods import FIFO, LIBR, compare


def tx(hash_, value, block, ts=None, frm=None, to=None):
    return SimpleNamespace(hash=hash_, value_native=value, block_number=block, timestamp=ts or block,
                           from_address=frm, to_address=to)


def edge(graph, a, b, *txs):
    graph.add_edge(a, b, value_native=sum(t.value_native for t in txs), transactions=[
        {"hash": t.hash, "value_native": t.value_native, "block_number": t.block_number,
         "timestamp": t.timestamp} for t in txs])


def reader(incoming, outgoing, complete=True):
    """flows_between for one middle wallet: what came in and went out."""
    return lambda *window: (incoming, outgoing, complete)


def one_hop(victim_pays, onward, others_in=(), others_out=()):
    """V -> M -> X, with M's other transfers in and out."""
    g = nx.DiGraph()
    edge(g, "V", "M", *victim_pays)
    edge(g, "M", "X", *onward)
    return g, reader([*victim_pays, *others_in], [*onward, *others_out])


def figures(graph, flows, prorata=None):
    result = compare(graph, ["V", "M", "X"], flows, prorata)
    return result[FIFO]["estimated"], result[LIBR]["estimated"], result


# ---------------------------------------------------------------------------
# The module docstring's example
# ---------------------------------------------------------------------------
def test_the_docstring_example_gives_40_by_fifo_0_by_libr_and_20_by_pro_rata():
    # Block 1: 40 of the victim's arrive. Block 2: 60 from someone else.
    # Block 3: 50 go to the exchange.
    victim = tx("v1", 40.0, 1)
    g, flows = one_hop([victim], [tx("x1", 50.0, 3)], others_in=[tx("o1", 60.0, 2)])
    prorata = estimate_prorata(g, ["V", "M", "X"], lambda *w: ([victim, tx("o1", 60.0, 2)], True))
    fifo, libr, result = figures(g, flows, prorata)
    assert (fifo, libr, prorata["estimated"]) == (40.0, 0.0, 20.0)
    assert result["range"] == {"low": 0.0, "high": 40.0}
    assert result["conservative"] == 0.0 and result["conservative_method"] == LIBR


# ---------------------------------------------------------------------------
# Agreement: when nothing else is in the wallet, every rule says all of it
# ---------------------------------------------------------------------------
def test_with_no_other_money_every_method_says_all_of_it():
    g, flows = one_hop([tx("v1", 40.0, 1)], [tx("x1", 40.0, 2)])
    fifo, libr, result = figures(g, flows)
    assert fifo == libr == 40.0
    assert result[FIFO]["ratio"] == 1.0 and result[FIFO]["unseen_outflow"] is False


def test_a_direct_deposit_needs_no_reads_and_is_all_of_it():
    g = nx.DiGraph()
    edge(g, "V", "X", tx("v1", 12.5, 1))
    result = compare(g, ["V", "X"], None)
    assert result[FIFO]["estimated"] == result[LIBR]["estimated"] == 12.5


# ---------------------------------------------------------------------------
# FIFO, by hand
# ---------------------------------------------------------------------------
def test_fifo_older_money_leaves_first():
    # Block 1: 30 from someone else. Block 2: 40 of the victim's.
    # Block 3: 50 to the exchange takes the 30 first, then 20 of the victim's.
    g, flows = one_hop([tx("v1", 40.0, 2)], [tx("x1", 50.0, 3)], others_in=[tx("o1", 30.0, 1)])
    # The other money arrived before the window opened (block 2), so it is not
    # seen: the window starts when the victim's money arrives.
    fifo, _, result = figures(g, flows)
    assert fifo == 40.0
    assert result[FIFO]["hops"][0]["unseen_outflow"] == 10.0


def test_fifo_an_earlier_payment_out_takes_the_victims_money_first():
    # Block 1: 40 of the victim's. Block 2: 25 of it leaves to someone else.
    # Block 3: 60 more arrive. Block 4: 50 to the exchange takes the victim's
    # remaining 15, then 35 of the other money.
    g, flows = one_hop([tx("v1", 40.0, 1)], [tx("x1", 50.0, 4)],
                       others_in=[tx("o1", 60.0, 3)], others_out=[tx("y1", 25.0, 2)])
    fifo, _, _ = figures(g, flows)
    assert fifo == 15.0


def test_fifo_splits_one_transfer_out_across_several_lots():
    # 10 victim, 10 other, 10 victim, then 25 out: takes 10 v + 10 o + 5 v.
    g, flows = one_hop([tx("v1", 10.0, 1), tx("v2", 10.0, 3)], [tx("x1", 25.0, 4)],
                       others_in=[tx("o1", 10.0, 2)])
    fifo, _, _ = figures(g, flows)
    assert fifo == 15.0


# ---------------------------------------------------------------------------
# LIBR, by hand
# ---------------------------------------------------------------------------
def test_libr_victim_money_leaves_only_when_the_balance_drops_below_it():
    # Block 1: 40 victim (balance 40). Block 2: 60 other (100).
    # Block 3: 70 to the exchange: balance 30, below the victim's 40, so 10 of
    # the victim's left in that transfer.
    g, flows = one_hop([tx("v1", 40.0, 1)], [tx("x1", 70.0, 3)], others_in=[tx("o1", 60.0, 2)])
    _, libr, _ = figures(g, flows)
    assert libr == 10.0


def test_libr_money_that_left_does_not_come_back_with_new_deposits():
    # Block 1: 40 victim. Block 2: 30 out elsewhere (balance 10, victim 10).
    # Block 3: 90 other arrive (balance 100, victim still 10).
    # Block 4: 100 to the exchange: the victim's 10 left with it.
    g, flows = one_hop([tx("v1", 40.0, 1)], [tx("x1", 100.0, 4)],
                       others_in=[tx("o1", 90.0, 3)], others_out=[tx("y1", 30.0, 2)])
    fifo, libr, _ = figures(g, flows)
    assert libr == 10.0
    assert fifo == 10.0  # FIFO: the 30 out took victim money first, the rest leaves at block 4


# ---------------------------------------------------------------------------
# Two middle wallets: what one hop carries is what the next one starts with
# ---------------------------------------------------------------------------
def test_two_hops_carry_the_victims_part_forward():
    # V -40-> A (block 1). A also gets 60 other (block 2) and sends 100 to B (3).
    # B also gets 100 other (block 4) and sends 50 to X (5).
    g = nx.DiGraph()
    edge(g, "V", "A", tx("v1", 40.0, 1))
    edge(g, "A", "B", tx("ab", 100.0, 3))
    edge(g, "B", "X", tx("bx", 50.0, 5))
    flows = {
        "A": ([tx("v1", 40.0, 1), tx("o1", 60.0, 2)], [tx("ab", 100.0, 3)]),
        "B": ([tx("ab", 100.0, 3), tx("o2", 100.0, 4)], [tx("bx", 50.0, 5)]),
    }
    result = compare(g, ["V", "A", "B", "X"], lambda addr, *w: (*flows[addr], True))
    # FIFO: A passes all 40 on to B. At B those 40 are in the oldest lot
    # (100 with 40 victim), and the 50 out takes half of it: 20.
    assert result[FIFO]["estimated"] == 20.0
    # LIBR: A sends everything, so all 40 leave for B. At B the balance after
    # the 50 out is 150, which covers the 40: none of it has to have left.
    assert result[LIBR]["estimated"] == 0.0
    assert [h["victim_on"] for h in result[FIFO]["hops"]] == [40.0, 20.0]


# ---------------------------------------------------------------------------
# Honesty: no number from part of the picture
# ---------------------------------------------------------------------------
def test_an_incomplete_read_is_unknown_for_both_methods():
    g, _ = one_hop([tx("v1", 40.0, 1)], [tx("x1", 40.0, 2)])
    result = compare(g, ["V", "M", "X"], reader([], [], complete=False))
    assert result[FIFO]["status"] == result[LIBR]["status"] == "unknown"
    assert "in full" in result[FIFO]["reason"]
    assert result["conservative"] is None and result["range"] is None


def test_a_failed_read_is_unknown_and_never_raises():
    def boom(*window):
        raise RuntimeError("provider down")
    g, _ = one_hop([tx("v1", 40.0, 1)], [tx("x1", 40.0, 2)])
    result = compare(g, ["V", "M", "X"], boom)
    assert result[LIBR]["status"] == "unknown" and "could not be read" in result[LIBR]["reason"]
    # A fixed sentence: exception text can quote a provider's response body.
    assert "provider down" not in result[LIBR]["reason"]


def test_sending_on_before_the_money_arrived_is_unknown():
    g, flows = one_hop([tx("v1", 40.0, 5)], [tx("x1", 40.0, 2)])
    assert compare(g, ["V", "M", "X"], flows)[FIFO]["status"] == "unknown"


def test_the_path_transfers_count_even_if_the_provider_list_missed_them():
    # An internal transfer can be missing from a plain transaction list.
    g, _ = one_hop([tx("v1", 40.0, 1)], [tx("x1", 40.0, 2)])
    fifo, libr, _ = figures(g, reader([], []))
    assert fifo == libr == 40.0


def test_transfers_outside_the_window_are_ignored():
    # The 500 arriving at block 9 is after M sent on (block 2).
    g, flows = one_hop([tx("v1", 40.0, 1)], [tx("x1", 40.0, 2)], others_in=[tx("late", 500.0, 9)])
    fifo, libr, _ = figures(g, flows)
    assert fifo == libr == 40.0


def test_money_in_and_out_in_the_same_block_can_pass_straight_through():
    g, flows = one_hop([tx("v1", 40.0, 7)], [tx("x1", 40.0, 7)])
    fifo, libr, _ = figures(g, flows)
    assert fifo == libr == 40.0


def test_tron_transfers_are_ordered_by_time_when_there_are_no_blocks():
    g, flows = one_hop([tx("v1", 40.0, None, ts=1000)], [tx("x1", 50.0, None, ts=1003)],
                       others_in=[tx("o1", 60.0, None, ts=1001)])
    fifo, libr, _ = figures(g, flows)
    assert (fifo, libr) == (40.0, 0.0)


@pytest.mark.parametrize("method", [FIFO, LIBR])
def test_a_method_never_finds_more_than_was_sent(method):
    g, flows = one_hop([tx("v1", 40.0, 1)], [tx("x1", 1000.0, 3)], others_in=[tx("o1", 960.0, 2)])
    result = compare(g, ["V", "M", "X"], flows)[method]
    assert result["estimated"] <= result["sent"] and result["ratio"] <= 1.0



# ---------------------------------------------------------------------------
# Recycled coins are not new money (audit r1-attribution-integrity-5)
# ---------------------------------------------------------------------------
def _round_trips(n=9):
    """V pays M 10,000; M bounces it through H n times; M pays X 10,000."""
    victim = tx("v1", 10_000.0, 1, frm="V", to="M")
    onward = tx("x1", 10_000.0, 100, frm="M", to="X")
    out = [tx(f"o{i}", 10_000.0, 2 + 2 * i, frm="M", to="H") for i in range(n)]
    back = [tx(f"b{i}", 10_000.0, 3 + 2 * i, frm="H", to="M") for i in range(n)]
    g = nx.DiGraph()
    edge(g, "V", "M", victim)
    edge(g, "M", "X", onward)
    return g, reader([victim, *back], [*out, onward])


def test_fifo_carries_the_victims_coins_through_a_round_trip():
    g, flows = _round_trips()
    fifo, libr, _ = figures(g, flows)
    assert fifo == 10_000.0 and libr == 10_000.0


def test_self_sends_are_not_lots():
    victim = tx("v1", 10_000.0, 1, frm="V", to="M")
    onward = tx("x1", 10_000.0, 100, frm="M", to="X")
    selfs = [tx(f"s{i}", 10_000.0, 2 + i, frm="M", to="M") for i in range(9)]
    g = nx.DiGraph()
    edge(g, "V", "M", victim)
    edge(g, "M", "X", onward)
    fifo, libr, result = figures(g, reader([victim, *selfs], [*selfs, onward]))
    assert fifo == libr == 10_000.0
    assert result[FIFO]["hops"][0]["received_in_window"] == 10_000.0


def test_conservative_is_not_zeroed_by_recycling():
    g, flows = _round_trips()
    prorata = estimate_prorata(g, ["V", "M", "X"], None, flows_between=flows)
    result = compare(g, ["V", "M", "X"], flows, prorata)
    assert result["conservative"] == 10_000.0


# ---------------------------------------------------------------------------
# Longer loops: coins out through one helper, back through another
# (audit r1-attribution-integrity-5, round 2)
# ---------------------------------------------------------------------------
def three_wallet_loop(n=9, link=10_000.0, link_block=None, h2_is_linked=True):
    """V pays M 10,000; n times M pays H1 10,000, H1 pays H2 `link`, H2 pays
    M 10,000; M pays X 10,000. The trace followed M -> H1 -> H2, so those
    edges are in the graph. The verifier's probe, with the link in the graph."""
    victim = tx("v1", 10_000.0, 1, frm="V", to="M")
    onward = tx("x1", 10_000.0, 100, frm="M", to="X")
    out = [tx(f"o{i}", 10_000.0, 2 + 3 * i, frm="M", to="H1") for i in range(n)]
    hop = [tx(f"h{i}", link, link_block or 3 + 3 * i, frm="H1", to="H2") for i in range(n)]
    back = [tx(f"b{i}", 10_000.0, 4 + 3 * i, frm="H2", to="M") for i in range(n)]
    g = nx.DiGraph()
    edge(g, "V", "M", victim)
    edge(g, "M", "X", onward)
    edge(g, "M", "H1", *out)
    if h2_is_linked:
        edge(g, "H1", "H2", *hop)
    return g, reader([victim, *back], [*out, onward])


def test_a_loop_through_two_helpers_keeps_the_victims_coins():
    g, flows = three_wallet_loop()
    prorata = estimate_prorata(g, ["V", "M", "X"], None, flows_between=flows)
    fifo, libr, result = figures(g, flows, prorata)
    assert (fifo, libr, prorata["estimated"]) == (10_000.0, 10_000.0, 10_000.0)
    assert result["conservative"] == 10_000.0
    assert prorata["hops"][0]["recycled_in_window"] == 90_000.0 and not prorata["diluted"]


def test_a_longer_loop_is_netted_too():
    # M -> H1 -> H2 -> H3 -> M, once.
    victim = tx("v1", 10_000.0, 1, frm="V", to="M")
    onward = tx("x1", 10_000.0, 100, frm="M", to="X")
    out, back = tx("o", 10_000.0, 2, frm="M", to="H1"), tx("b", 10_000.0, 5, frm="H3", to="M")
    g = nx.DiGraph()
    edge(g, "V", "M", victim)
    edge(g, "M", "X", onward)
    edge(g, "M", "H1", out)
    edge(g, "H1", "H2", tx("h12", 10_000.0, 3))
    edge(g, "H2", "H3", tx("h23", 10_000.0, 4))
    flows = reader([victim, back], [out, onward])
    prorata = estimate_prorata(g, ["V", "M", "X"], None, flows_between=flows)
    fifo, libr, _ = figures(g, flows, prorata)
    assert (fifo, libr, prorata["estimated"]) == (10_000.0, 10_000.0, 10_000.0)


def test_a_loop_is_netted_by_time_where_the_chain_gives_no_blocks():
    # Tron: transfers carry times only.
    def t(hash_, value, when, frm, to):
        return tx(hash_, value, None, ts=1_000 + when, frm=frm, to=to)
    victim, onward = t("v1", 10_000.0, 1, "V", "M"), t("x1", 10_000.0, 100, "M", "X")
    out = [t(f"o{i}", 10_000.0, 2 + 3 * i, "M", "H1") for i in range(9)]
    hop = [t(f"h{i}", 10_000.0, 3 + 3 * i, "H1", "H2") for i in range(9)]
    back = [t(f"b{i}", 10_000.0, 4 + 3 * i, "H2", "M") for i in range(9)]
    g = nx.DiGraph()
    edge(g, "V", "M", victim)
    edge(g, "M", "X", onward)
    edge(g, "M", "H1", *out)
    edge(g, "H1", "H2", *hop)
    flows = reader([victim, *back], [*out, onward])
    prorata = estimate_prorata(g, ["V", "M", "X"], None, flows_between=flows)
    fifo, libr, _ = figures(g, flows, prorata)
    assert (fifo, libr, prorata["estimated"]) == (10_000.0, 10_000.0, 10_000.0)


def test_a_loop_is_said_in_the_caveats():
    from app.scoring import _prorata_caveats
    g, flows = three_wallet_loop()
    text = " ".join(_prorata_caveats(estimate_prorata(g, ["V", "M", "X"], None, flows_between=flows), "USDT"))
    assert "M got 90,000.0000 USDT back" in text and "from H2" in text and "netted out" in text


def test_money_from_a_wallet_the_trace_never_linked_to_ms_payees_is_new_money():
    # H2 is not reached from H1 in the traced graph: its 10,000s are someone else's.
    g, flows = three_wallet_loop(n=1, h2_is_linked=False)
    prorata = estimate_prorata(g, ["V", "M", "X"], None, flows_between=flows)
    fifo, libr, _ = figures(g, flows, prorata)
    assert prorata["estimated"] == 5_000.0 and prorata["hops"][0]["recycled_in_window"] == 0.0
    # M paid the victim's coins to H1 and took H2's in: nothing netted, as before.
    assert (fifo, libr) == (0.0, 0.0)


def test_a_thin_link_nets_no_more_than_flowed_along_it():
    # H1 passed only 5 to H2 each time: at most 45 of H2's 90,000 can be M's own coins.
    g, flows = three_wallet_loop(link=5.0)
    prorata = estimate_prorata(g, ["V", "M", "X"], None, flows_between=flows)
    assert prorata["hops"][0]["recycled_in_window"] == 45.0
    assert prorata["diluted"]


def test_a_link_outside_the_window_is_not_a_loop():
    # H1 paid H2 long before the victim's money arrived: not these coins.
    g, flows = three_wallet_loop(n=1, link_block=-50)
    prorata = estimate_prorata(g, ["V", "M", "X"], None, flows_between=flows)
    assert prorata["hops"][0]["recycled_in_window"] == 0.0


def test_money_back_before_m_paid_out_is_not_netted_even_with_a_link():
    # H2 paid M first; M only paid H1 afterwards. H2's money did join M.
    victim = tx("v1", 10_000.0, 1, frm="V", to="M")
    onward = tx("x1", 10_000.0, 100, frm="M", to="X")
    came, went = tx("b", 10_000.0, 2, frm="H2", to="M"), tx("o", 10_000.0, 3, frm="M", to="H1")
    g = nx.DiGraph()
    edge(g, "V", "M", victim)
    edge(g, "M", "X", onward)
    edge(g, "M", "H1", went)
    edge(g, "H1", "H2", tx("h", 10_000.0, 4))
    prorata = estimate_prorata(g, ["V", "M", "X"], None, flows_between=reader([victim, came], [went, onward]))
    assert prorata["hops"][0]["recycled_in_window"] == 0.0 and prorata["estimated"] == 5_000.0


def test_the_methods_never_exceed_the_seed_cap():
    # The reported wallet sent 50 on; the victim's part of it was at most 10.
    g, flows = one_hop([tx("v1", 50.0, 1)], [tx("x1", 50.0, 2)])
    result = compare(g, ["V", "M", "X"], flows, seed_cap=10.0)
    assert result[FIFO]["estimated"] == result[LIBR]["estimated"] == 10.0
    assert result["conservative"] == 10.0
