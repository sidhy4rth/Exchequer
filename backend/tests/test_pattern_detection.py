"""Tests for the laundering heuristics.

These rules are the part of TraceChain that makes an accusation, so what
matters is not only that they fire on the shape they describe but that they
stay silent on ordinary activity. Each rule therefore gets both.
"""
from __future__ import annotations

from app.pattern_detection import (
    AMOUNT_SPLIT,
    PEEL_CHAIN,
    PatternConfig,
    detect_amount_splits,
    detect_patterns,
    detect_peel_chains,
    flag_names,
)

from conftest import addr, make_graph

CFG = PatternConfig()
NOT_AN_EXCHANGE = lambda _a: False  # noqa: E731


# ---------------------------------------------------------------------------
# Peel chain
# ---------------------------------------------------------------------------
def test_peel_chain_fires_on_declining_single_use_run(peel_chain_graph):
    findings = detect_peel_chains(peel_chain_graph, CFG, NOT_AN_EXCHANGE)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.pattern == PEEL_CHAIN
    # The reported path includes the feeder and the exit, not just the run.
    assert finding.evidence["chain_length"] == 2
    assert finding.evidence["path"] == [addr("5eed"), addr("a1"), addr("b2"), addr("e11")]
    assert finding.evidence["hop_amounts_native"] == [10.0, 9.0, 8.0]
    assert finding.evidence["total_peeled_native"] == 2.0
    assert 0.0 < finding.strength <= 1.0


def test_peel_chain_reports_the_thresholds_it_applied(peel_chain_graph):
    """A finding has to be re-checkable by hand, which means saying what it used."""
    finding = detect_peel_chains(peel_chain_graph, CFG, NOT_AN_EXCHANGE)[0]
    applied = finding.evidence["thresholds_applied"]

    assert applied["low_activity_max"] == CFG.low_activity_max
    assert applied["min_chain_intermediates"] == CFG.min_chain_intermediates
    assert applied["min_hop_retention"] == CFG.min_hop_retention
    assert applied["growth_tolerance"] == CFG.growth_tolerance


def test_peel_chain_ignores_a_run_whose_amounts_grow():
    """Money growing along the path is a funding pattern, not a peel."""
    seed = addr("5eed")
    graph = make_graph(
        [
            (seed, addr("a1"), 8.0),
            (addr("a1"), addr("b2"), 9.0),
            (addr("b2"), addr("e11"), 10.0),
        ],
        seed=seed,
    )
    assert detect_peel_chains(graph, CFG, NOT_AN_EXCHANGE) == []


def test_peel_chain_ignores_a_hop_that_keeps_most_of_the_money():
    """Forwarding 20% is a split; the amount-split rule owns that shape."""
    seed = addr("5eed")
    graph = make_graph(
        [
            (seed, addr("a1"), 10.0),
            (addr("a1"), addr("b2"), 2.0),
            (addr("b2"), addr("e11"), 1.8),
        ],
        seed=seed,
    )
    assert detect_peel_chains(graph, CFG, NOT_AN_EXCHANGE) == []


def test_peel_chain_needs_more_than_one_intermediate():
    """A single hop between two wallets is an ordinary payment."""
    seed = addr("5eed")
    graph = make_graph(
        [(seed, addr("a1"), 10.0), (addr("a1"), addr("e11"), 9.0)],
        seed=seed,
    )
    assert detect_peel_chains(graph, CFG, NOT_AN_EXCHANGE) == []


def test_peel_chain_skips_wallets_that_are_known_exchanges(peel_chain_graph):
    """An exchange hot wallet is busy by nature and is never a throwaway."""
    findings = detect_peel_chains(
        peel_chain_graph, CFG, lambda a: a == addr("b2")
    )
    assert findings == []


def test_peel_chain_ignores_a_busy_wallet():
    """Above low_activity_max the wallet is lived in, not single-use."""
    seed = addr("5eed")
    graph = make_graph(
        [
            (seed, addr("a1"), 10.0),
            (addr("a1"), addr("b2"), 9.0),
            (addr("b2"), addr("e11"), 8.0),
        ],
        seed=seed,
        tx_count=4,  # activity_count becomes 8, over the limit of 3
    )
    assert detect_peel_chains(graph, CFG, NOT_AN_EXCHANGE) == []


# ---------------------------------------------------------------------------
# Amount split
# ---------------------------------------------------------------------------
def test_amount_split_fires_on_an_even_fan_out(amount_split_graph):
    findings = detect_amount_splits(amount_split_graph, CFG, NOT_AN_EXCHANGE)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.pattern == AMOUNT_SPLIT
    assert finding.evidence["address"] == addr("5911")
    assert finding.evidence["branch_count"] == 4
    assert finding.evidence["total_in_native"] == 10.0
    assert finding.evidence["total_out_native"] == 9.6
    assert finding.evidence["forwarded_ratio"] == 0.96
    assert finding.evidence["largest_branch_share"] < CFG.max_single_branch_share


def test_amount_split_needs_four_recipients():
    """Paying a few people and keeping change is ordinary; the validation run
    showed three recipients fires on 40% of ordinary high-volume wallets."""
    seed = addr("5eed")
    splitter = addr("5911")
    graph = make_graph(
        [
            (seed, splitter, 10.0),
            (splitter, addr("c1"), 3.2),
            (splitter, addr("c2"), 3.2),
            (splitter, addr("c3"), 3.2),
        ],
        seed=seed,
    )
    assert detect_amount_splits(graph, CFG, NOT_AN_EXCHANGE) == []


def test_amount_split_ignores_a_wallet_that_keeps_some_of_the_money():
    """Forwarding 80% of the inflow is spending, not passing through."""
    seed = addr("5eed")
    splitter = addr("5911")
    graph = make_graph(
        [
            (seed, splitter, 10.0),
            (splitter, addr("c1"), 2.0),
            (splitter, addr("c2"), 2.0),
            (splitter, addr("c3"), 2.0),
            (splitter, addr("c4"), 2.0),
        ],
        seed=seed,
    )
    assert detect_amount_splits(graph, CFG, NOT_AN_EXCHANGE) == []


def test_amount_split_ignores_money_forwarded_mostly_whole():
    """One branch taking ~94% is a pass-through with change, not a division."""
    seed = addr("5eed")
    splitter = addr("5911")
    graph = make_graph(
        [
            (seed, splitter, 10.0),
            (splitter, addr("c1"), 9.4),
            (splitter, addr("c2"), 0.1),
            (splitter, addr("c3"), 0.1),
            (splitter, addr("c4"), 0.1),
        ],
        seed=seed,
    )
    assert detect_amount_splits(graph, CFG, NOT_AN_EXCHANGE) == []


def test_amount_split_skips_exchanges(amount_split_graph):
    """Exchanges fan out to thousands of customers by design."""
    findings = detect_amount_splits(
        amount_split_graph, CFG, lambda a: a == addr("5911")
    )
    assert findings == []


def test_amount_split_skips_the_seed_which_has_no_observed_inflow():
    """The forwarded-ratio test cannot be applied without an inflow to divide."""
    seed = addr("5eed")
    graph = make_graph(
        [
            (seed, addr("c1"), 2.5),
            (seed, addr("c2"), 2.5),
            (seed, addr("c3"), 2.5),
            (seed, addr("c4"), 2.5),
        ],
        seed=seed,
    )
    assert detect_amount_splits(graph, CFG, NOT_AN_EXCHANGE) == []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def test_detect_patterns_tags_the_graph_for_the_frontend(amount_split_graph):
    detect_patterns(amount_split_graph, CFG, NOT_AN_EXCHANGE)

    assert AMOUNT_SPLIT in amount_split_graph.nodes[addr("5911")]["flags"]
    assert AMOUNT_SPLIT in amount_split_graph.edges[addr("5911"), addr("c1")]["flags"]


def test_detect_patterns_returns_strongest_first():
    """A graph carrying both patterns reports them in strength order."""
    seed = addr("5eed")
    splitter = addr("5911")
    graph = make_graph(
        [
            # A peel chain leading into a splitter.
            (seed, addr("a1"), 10.0),
            (addr("a1"), addr("b2"), 9.5),
            (addr("b2"), splitter, 9.0),
            (splitter, addr("c1"), 2.3),
            (splitter, addr("c2"), 2.3),
            (splitter, addr("c3"), 2.3),
            (splitter, addr("c4"), 2.0),
        ],
        seed=seed,
    )
    findings = detect_patterns(graph, CFG, NOT_AN_EXCHANGE)

    assert {f.pattern for f in findings} == {PEEL_CHAIN, AMOUNT_SPLIT}
    strengths = [f.strength for f in findings]
    assert strengths == sorted(strengths, reverse=True)
    assert flag_names(findings) == [AMOUNT_SPLIT, PEEL_CHAIN]


def test_detect_patterns_is_silent_on_an_ordinary_payment():
    """The rules must not manufacture a finding from normal activity."""
    seed = addr("5eed")
    graph = make_graph([(seed, addr("a1"), 1.0)], seed=seed)
    assert detect_patterns(graph, CFG, NOT_AN_EXCHANGE) == []


def test_native_symbol_reaches_the_description(amount_split_graph):
    """A description saying 'ETH' about a BNB transfer misstates the evidence."""
    findings = detect_amount_splits(
        amount_split_graph, PatternConfig(native_symbol="BNB"), NOT_AN_EXCHANGE
    )
    assert "BNB" in findings[0].description
    assert "ETH" not in findings[0].description
