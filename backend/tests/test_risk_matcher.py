"""Tests for sanctions and mixer screening.

Two things matter here and they fail in opposite directions. Calling a clean
address sanctioned is a false accusation against a real party. Failing to stop
a trace at a mixer produces a confident graph built on a false premise, which
is worse than producing nothing at all -- so the terminal behaviour is tested
as carefully as the matching.
"""
from __future__ import annotations

import json

import pytest

from app.risk_matcher import MIXER, SANCTIONED, RiskMatcher

from conftest import addr, make_graph

SEED = addr("5eed")
MIXER_ADDR = addr("111e4")
SDN_ADDR = addr("5d1")


@pytest.fixture
def risk_file(tmp_path):
    path = tmp_path / "risk.json"
    path.write_text(
        json.dumps(
            {
                "_meta": {"source": "OFAC SDN list, published 01/01/2026"},
                MIXER_ADDR: {
                    "category": "mixer",
                    "entity": "TORNADO CASH",
                    "label": "TORNADO CASH",
                },
                SDN_ADDR: {
                    "category": "sanctioned",
                    "entity": "LAZARUS GROUP",
                    "label": "LAZARUS GROUP",
                    "source": "OFAC SDN list, published 01/01/2026",
                },
            }
        )
    )
    return path


def test_loads_both_categories(risk_file):
    matcher = RiskMatcher.from_file(risk_file)

    assert len(matcher) == 2
    assert matcher.counts_by_category() == {SANCTIONED: 1, MIXER: 1}
    assert matcher.entities == ["LAZARUS GROUP", "TORNADO CASH"]


def test_source_falls_back_to_the_file_metadata(risk_file):
    """Every finding must be able to name the list it came from."""
    matcher = RiskMatcher.from_file(risk_file)
    assert matcher.lookup(MIXER_ADDR)["source"] == "OFAC SDN list, published 01/01/2026"


def test_an_unlisted_address_is_not_flagged(risk_file):
    matcher = RiskMatcher.from_file(risk_file)
    assert matcher.lookup(addr("c1ea4")) is None
    assert matcher.is_flagged(addr("c1ea4")) is False
    assert matcher.is_terminal(addr("c1ea4")) is False


def test_an_unknown_category_is_dropped_rather_than_guessed(tmp_path):
    """A bad category must not silently become a warning of the wrong kind."""
    path = tmp_path / "risk.json"
    path.write_text(
        json.dumps({SDN_ADDR: {"category": "suspicious", "entity": "SOMEONE"}})
    )
    assert len(RiskMatcher.from_file(path)) == 0


def test_an_entry_with_no_entity_is_dropped(tmp_path):
    path = tmp_path / "risk.json"
    path.write_text(json.dumps({SDN_ADDR: {"category": "sanctioned"}}))
    assert len(RiskMatcher.from_file(path)) == 0


def test_a_missing_file_disables_screening_without_breaking_the_trace(tmp_path):
    matcher = RiskMatcher.from_file(tmp_path / "absent.json")
    assert len(matcher) == 0
    assert matcher.is_flagged(SDN_ADDR) is False


def test_a_corrupt_file_disables_screening_without_crashing(tmp_path):
    path = tmp_path / "risk.json"
    path.write_text("{not json")
    assert len(RiskMatcher.from_file(path)) == 0


def test_no_path_configured_disables_screening():
    assert len(RiskMatcher.from_file(None)) == 0


# ---------------------------------------------------------------------------
# Terminal behaviour -- the reason this module is separate from the exchange one
# ---------------------------------------------------------------------------
def test_a_mixer_ends_the_trace(risk_file):
    """Following a tumbler's outputs would manufacture a trail."""
    matcher = RiskMatcher.from_file(risk_file)
    assert matcher.is_terminal(MIXER_ADDR) is True


def test_a_sanctioned_address_does_not_end_the_trace(risk_file):
    """It is an ordinary wallet whose transfers mean what they say."""
    matcher = RiskMatcher.from_file(risk_file)
    assert matcher.is_flagged(SDN_ADDR) is True
    assert matcher.is_terminal(SDN_ADDR) is False


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------
def test_annotate_tags_nodes_and_returns_matches(risk_file):
    matcher = RiskMatcher.from_file(risk_file)
    graph = make_graph(
        [(SEED, addr("a1"), 10.0), (addr("a1"), MIXER_ADDR, 9.0)], seed=SEED
    )

    matches = matcher.annotate(graph)

    assert len(matches) == 1
    assert matches[0].category == MIXER
    assert matches[0].depth == 2
    assert matches[0].value_received_native == pytest.approx(9.0)

    node = graph.nodes[MIXER_ADDR]
    assert node["risk_category"] == MIXER
    assert node["risk_entity"] == "TORNADO CASH"
    assert MIXER in node["flags"]
    assert node["is_terminal"] is True


def test_annotate_does_not_mark_a_sanctioned_node_terminal(risk_file):
    matcher = RiskMatcher.from_file(risk_file)
    graph = make_graph([(SEED, SDN_ADDR, 10.0)], seed=SEED)

    matcher.annotate(graph)

    assert graph.nodes[SDN_ADDR]["risk_category"] == SANCTIONED
    assert graph.nodes[SDN_ADDR].get("is_terminal") is not True


def test_matches_are_ordered_closest_to_the_victim_first(risk_file):
    matcher = RiskMatcher.from_file(risk_file)
    graph = make_graph(
        [
            (SEED, SDN_ADDR, 5.0),                  # depth 1
            (SEED, addr("a1"), 10.0),
            (addr("a1"), MIXER_ADDR, 9.0),          # depth 2
        ],
        seed=SEED,
    )
    matches = matcher.annotate(graph)
    assert [m.depth for m in matches] == [1, 2]


def test_annotate_leaves_a_clean_graph_untouched(risk_file):
    matcher = RiskMatcher.from_file(risk_file)
    graph = make_graph([(SEED, addr("a1"), 10.0)], seed=SEED)

    assert matcher.annotate(graph) == []
    assert "risk_category" not in graph.nodes[addr("a1")]


# ---------------------------------------------------------------------------
# Descriptions -- these get pasted into reports
# ---------------------------------------------------------------------------
def test_a_mixer_description_states_why_the_trace_stopped(risk_file):
    matcher = RiskMatcher.from_file(risk_file)
    graph = make_graph([(SEED, MIXER_ADDR, 9.0)], seed=SEED)
    text = matcher.annotate(graph)[0].describe("ETH")

    assert "TORNADO CASH" in text
    assert "commingled pool" in text
    assert "OFAC SDN list" in text


def test_a_sanctioned_description_names_the_list_and_the_entity(risk_file):
    matcher = RiskMatcher.from_file(risk_file)
    graph = make_graph([(SEED, SDN_ADDR, 5.0)], seed=SEED)
    text = matcher.annotate(graph)[0].describe("USDT")

    assert "LAZARUS GROUP" in text
    assert "OFAC SDN list" in text
    assert "USDT" in text


def test_description_says_when_the_reported_address_is_itself_listed(risk_file):
    """No value figure there: the trace starts at the seed, so the graph holds
    no inbound edge and any number would be a misleading 0.0000."""
    matcher = RiskMatcher.from_file(risk_file)
    graph = make_graph([(SDN_ADDR, addr("a1"), 5.0)], seed=SDN_ADDR)
    text = matcher.annotate(graph)[0].describe("ETH")

    assert "It is the reported address itself" in text
    assert "0.0000" not in text


def test_description_does_not_repeat_a_name_that_is_its_own_label(risk_file):
    """OFAC entries usually label an address with the entity name itself;
    printing "X (X)" reads like a bug in a document meant to be quoted."""
    matcher = RiskMatcher.from_file(risk_file)
    graph = make_graph([(SEED, SDN_ADDR, 5.0)], seed=SEED)
    text = matcher.annotate(graph)[0].describe("ETH")

    assert "LAZARUS GROUP (LAZARUS GROUP)" not in text
    assert "listed as LAZARUS GROUP on" in text
