"""Tests for the confidence score.

The score is the number an investigator will quote, so the property that
matters most is that it stays a simple, reproducible function of its three
documented inputs -- no hidden adjustment from patterns or truncation.
"""
from __future__ import annotations

import pytest

from app.exchange_matcher import ExchangeMatch
from app.pattern_detection import PatternFinding
from app.scoring import (
    WEIGHT_AMOUNT_CORRELATION,
    WEIGHT_HOP_PROXIMITY,
    WEIGHT_MATCH_DIRECTNESS,
    _amount_correlation,
    _band,
    _hop_proximity,
    _match_directness,
    score_case,
)

from conftest import addr, make_graph

SEED = addr("5eed")
EXCHANGE = addr("e11")


def a_match(depth: int = 1, wallet_type: str = "hot_wallet", value: float = 10.0):
    return ExchangeMatch(
        address=EXCHANGE,
        exchange="Binance",
        label="Binance 14",
        wallet_type=wallet_type,
        depth=depth,
        value_received_native=value,
    )


def test_weights_sum_to_one():
    """If they ever drift the score silently stops being a 0-1 quantity."""
    total = WEIGHT_HOP_PROXIMITY + WEIGHT_AMOUNT_CORRELATION + WEIGHT_MATCH_DIRECTNESS
    assert total == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------
def test_hop_proximity_is_full_for_a_direct_deposit():
    assert _hop_proximity(1, 4).raw_value == 1.0


def test_hop_proximity_decays_linearly_and_never_goes_negative():
    assert _hop_proximity(2, 4).raw_value == pytest.approx(0.75)
    assert _hop_proximity(3, 4).raw_value == pytest.approx(0.50)
    assert _hop_proximity(9, 4).raw_value == 0.0


def test_amount_correlation_is_full_when_the_money_survives_intact():
    graph = make_graph([(SEED, EXCHANGE, 10.0)], seed=SEED)
    assert _amount_correlation(graph, SEED, EXCHANGE).raw_value == pytest.approx(1.0)


def test_amount_correlation_compares_first_hop_with_last():
    """Half the value arriving scores half, whatever happened in between."""
    graph = make_graph(
        [(SEED, addr("a1"), 10.0), (addr("a1"), EXCHANGE, 5.0)], seed=SEED
    )
    assert _amount_correlation(graph, SEED, EXCHANGE).raw_value == pytest.approx(0.5)


def test_amount_correlation_is_neutral_when_no_path_exists():
    """Defensive: score neutrally rather than inventing a number."""
    graph = make_graph([(SEED, addr("a1"), 10.0), (addr("b2"), EXCHANGE, 5.0)], seed=SEED)
    component = _amount_correlation(graph, SEED, EXCHANGE)
    assert component.raw_value == 0.5
    assert "could not be measured" in component.explanation


def test_amount_correlation_handles_the_seed_being_the_exchange():
    graph = make_graph([(SEED, addr("a1"), 1.0)], seed=SEED)
    assert _amount_correlation(graph, SEED, SEED).raw_value == 1.0


def test_match_directness_scores_a_recorded_wallet_role_higher():
    """The component exists so weaker future attributions score lower."""
    assert _match_directness(a_match(wallet_type="hot_wallet")).raw_value == 1.0
    assert _match_directness(a_match(wallet_type="unknown")).raw_value == 0.8


# ---------------------------------------------------------------------------
# Bands
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "score,expected",
    [(1.0, "high"), (0.75, "high"), (0.74, "moderate"), (0.5, "moderate"),
     (0.49, "low"), (0.25, "low"), (0.24, "very low"), (0.0, "very low")],
)
def test_band_boundaries(score, expected):
    assert _band(score) == expected


# ---------------------------------------------------------------------------
# score_case
# ---------------------------------------------------------------------------
def test_a_direct_deposit_to_a_labelled_hot_wallet_scores_one():
    graph = make_graph([(SEED, EXCHANGE, 10.0)], seed=SEED)
    result = score_case(graph, SEED, a_match(depth=1), max_depth=4)

    assert result.score == 1.0
    assert result.band == "high"
    assert len(result.components) == 3


def test_score_is_the_weighted_sum_of_its_components():
    """No hidden adjustment: the number must be re-derivable by hand."""
    graph = make_graph(
        [(SEED, addr("a1"), 10.0), (addr("a1"), EXCHANGE, 5.0)], seed=SEED
    )
    result = score_case(graph, SEED, a_match(depth=2), max_depth=4)

    expected = sum(c.raw_value * c.weight for c in result.components)
    assert result.score == pytest.approx(round(expected, 4))
    assert result.score == pytest.approx(0.75 * 0.40 + 0.5 * 0.35 + 1.0 * 0.25)


def test_no_match_yields_no_score_rather_than_a_zero():
    """Zero would read as 'we are confident it did not happen'."""
    graph = make_graph([(SEED, addr("a1"), 10.0)], seed=SEED)
    result = score_case(graph, SEED, None)

    assert result.score is None
    assert result.band == "no attribution"
    assert result.components == []
    assert "absent from the label database" in result.summary


def test_findings_and_truncation_add_caveats_but_never_move_the_score():
    graph = make_graph([(SEED, EXCHANGE, 10.0)], seed=SEED)
    finding = PatternFinding(
        pattern="peel_chain", addresses=[SEED], description="", strength=0.9
    )

    plain = score_case(graph, SEED, a_match(), max_depth=4)
    flagged = score_case(
        graph, SEED, a_match(), findings=[finding], max_depth=4, truncated=True
    )

    assert flagged.score == plain.score
    assert len(flagged.caveats) > len(plain.caveats)
    assert any("peel chain" in c for c in flagged.caveats)
    assert any("sample" in c for c in flagged.caveats)


def test_a_matched_case_always_carries_the_identity_caveat():
    """An exchange match is not an identification of a person."""
    graph = make_graph([(SEED, EXCHANGE, 10.0)], seed=SEED)
    result = score_case(graph, SEED, a_match(), max_depth=4)
    assert any("who controls" in c for c in result.caveats)


def test_native_symbol_reaches_the_explanation():
    graph = make_graph([(SEED, EXCHANGE, 10.0)], seed=SEED)
    result = score_case(graph, SEED, a_match(), max_depth=4, native_symbol="USDT")
    correlation = next(c for c in result.components if c.name == "amount_correlation")
    assert "USDT" in correlation.explanation
