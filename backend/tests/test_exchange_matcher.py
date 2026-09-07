"""Tests for exchange attribution.

Attribution is the claim that reaches a courtroom, so the rule is deliberately
an exact lookup in a file a human wrote. These tests pin that down: it matches
what is in the file, it matches nothing else, and a missing or broken file
degrades to "no attribution" rather than to a wrong one.
"""
from __future__ import annotations

import json

import pytest

from app.exchange_matcher import ExchangeMatcher

from conftest import addr, make_graph

SEED = addr("5eed")
HOT = addr("e11")
COLD = addr("e22")


@pytest.fixture
def label_file(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps(
            {
                "_source": "metadata keys are ignored",
                HOT: {"exchange": "Binance", "label": "Binance 14", "type": "hot_wallet"},
                COLD: {"exchange": "Kraken", "label": "Kraken 4", "type": "cold_wallet"},
                addr("e33"): "Coinbase",  # the simple shape
            }
        )
    )
    return path


def test_loads_both_the_simple_and_the_rich_label_shapes(label_file):
    matcher = ExchangeMatcher.from_file(label_file)

    assert len(matcher) == 3
    assert matcher.lookup(HOT)["label"] == "Binance 14"
    assert matcher.lookup(addr("e33")) == {
        "exchange": "Coinbase",
        "label": "Coinbase",
        "type": "unknown",
    }


def test_metadata_keys_are_not_treated_as_addresses(label_file):
    matcher = ExchangeMatcher.from_file(label_file)
    assert matcher.exchanges == ["Binance", "Coinbase", "Kraken"]


def test_lookup_is_case_insensitive_for_evm_addresses(label_file):
    """Etherscan returns checksummed addresses in some fields and lowercase in
    others; comparing them raw would silently miss the match."""
    matcher = ExchangeMatcher.from_file(label_file)
    assert matcher.is_exchange(HOT.upper().replace("0X", "0x"))


def test_an_unlabelled_address_is_not_attributed(label_file):
    matcher = ExchangeMatcher.from_file(label_file)
    assert matcher.lookup(addr("dead")) is None
    assert matcher.is_exchange(addr("dead")) is False


def test_a_missing_label_file_degrades_to_no_attribution(tmp_path):
    """A chain with no labels still traces; it just cannot attribute."""
    matcher = ExchangeMatcher.from_file(tmp_path / "absent.json")
    assert len(matcher) == 0
    assert matcher.is_exchange(HOT) is False


def test_a_corrupt_label_file_does_not_crash_the_trace(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json at all")
    assert len(ExchangeMatcher.from_file(path)) == 0


def test_annotate_tags_matched_nodes_and_returns_matches(label_file):
    matcher = ExchangeMatcher.from_file(label_file)
    graph = make_graph([(SEED, addr("a1"), 10.0), (addr("a1"), HOT, 9.0)], seed=SEED)

    matches = matcher.annotate(graph)

    assert len(matches) == 1
    assert matches[0].exchange == "Binance"
    assert matches[0].depth == 2
    assert matches[0].value_received_native == pytest.approx(9.0)
    assert graph.nodes[HOT]["is_exchange"] is True
    # Attributed addresses are terminal: the trace has found its answer.
    assert graph.nodes[HOT]["is_terminal"] is True


def test_primary_match_prefers_the_closest_exchange(label_file):
    """The shortest path is the least diluted by intermediate mixing."""
    matcher = ExchangeMatcher.from_file(label_file)
    graph = make_graph(
        [
            (SEED, COLD, 5.0),                 # Kraken at depth 1
            (SEED, addr("a1"), 10.0),
            (addr("a1"), HOT, 9.0),            # Binance at depth 2
        ],
        seed=SEED,
    )

    primary = ExchangeMatcher.primary_match(matcher.annotate(graph))
    assert primary.exchange == "Kraken"
    assert primary.depth == 1


def test_primary_match_breaks_a_depth_tie_on_value(label_file):
    matcher = ExchangeMatcher.from_file(label_file)
    graph = make_graph([(SEED, COLD, 2.0), (SEED, HOT, 40.0)], seed=SEED)

    primary = ExchangeMatcher.primary_match(matcher.annotate(graph))
    assert primary.exchange == "Binance"


def test_primary_match_of_nothing_is_none():
    assert ExchangeMatcher.primary_match([]) is None
