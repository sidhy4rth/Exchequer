"""Tests for deposit-address inference.

The inference names a company in a report on the strength of a wallet's
behaviour rather than a label file, so the tests that matter most are the
ones where it must stay silent: a customer wallet that simply deposits to an
exchange looks, on a careless reading, exactly like a deposit address.
"""
from __future__ import annotations

import pytest

from app.deposit_inference import DepositInferenceConfig, describe, infer_deposit_addresses
from app.exchange_matcher import INFERRED_DEPOSIT, ExchangeMatcher
from app.scoring import _match_directness, score_case

from conftest import addr, make_graph

SEED = addr("5eed")
DEPOSIT = addr("de90")
HOT = addr("b1a")
OTHER = addr("c1")


def matcher(**extra):
    labels = {HOT: {"exchange": "Binance", "label": "Binance 14", "type": "hot_wallet"}}
    labels.update(extra)
    return ExchangeMatcher(labels, chain="ethereum")


def outflows(**by_destination):
    """address -> (count, total) in the shape the graph builder records."""
    return {
        dst: {"count": count, "total": total, "first": 1_700_000_000, "last": 1_700_100_000}
        for dst, (count, total) in by_destination.items()
    }


def sweep_graph(sweeps: int = 3):
    graph = make_graph([(SEED, DEPOSIT, 10.0), (DEPOSIT, HOT, 10.0)], seed=SEED,
                       exchanges={HOT: "Binance"})
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = outflows(**{HOT: (sweeps, 30.0)})
    return graph


# ---------------------------------------------------------------------------
# Fires on the sweep shape
# ---------------------------------------------------------------------------
def test_an_address_that_only_ever_sweeps_to_one_hot_wallet_is_inferred():
    graph = sweep_graph(sweeps=3)
    found = infer_deposit_addresses(graph, matcher())

    assert [m.address for m in found] == [DEPOSIT]
    match = found[0]
    assert match.exchange == "Binance"
    assert match.wallet_type == INFERRED_DEPOSIT
    assert match.inferred is True
    assert match.depth == 1
    assert match.evidence["sweep_count"] == 3
    assert match.evidence["sweep_destination"] == HOT
    assert match.evidence["share_of_outflow_to_destination"] == 1.0
    assert "lawful request to Binance" in match.evidence["confirmation"]
    assert graph.nodes[DEPOSIT]["inferred_exchange"] == "Binance"


def test_the_balance_is_recorded_as_evidence_when_a_lookup_is_available():
    graph = sweep_graph()
    found = infer_deposit_addresses(graph, matcher(), balance_of=lambda a: 0.0003)
    assert found[0].evidence["current_balance_native"] == pytest.approx(0.0003)


def test_a_failed_balance_lookup_does_not_block_the_inference():
    def boom(_address):
        raise RuntimeError("provider down")

    found = infer_deposit_addresses(sweep_graph(), matcher(), balance_of=boom)
    assert len(found) == 1
    assert found[0].evidence["current_balance_native"] is None


def test_the_description_names_the_evidence_and_the_confirmation():
    found = infer_deposit_addresses(sweep_graph(), matcher())
    text = describe(found[0], "ETH")
    assert "3 outgoing transfers" in text
    assert HOT in text
    assert "inference, not a label-file match" in text
    assert "lawful request" in text


# ---------------------------------------------------------------------------
# Stays silent where it must
# ---------------------------------------------------------------------------
def test_a_single_transfer_to_an_exchange_is_not_enough():
    """One deposit is what any customer does."""
    assert infer_deposit_addresses(sweep_graph(sweeps=1), matcher()) == []


def test_a_wallet_that_also_sends_elsewhere_is_a_customer_not_a_deposit_address():
    graph = sweep_graph(sweeps=5)
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = outflows(
        **{HOT: (5, 50.0), OTHER: (1, 0.5)}
    )
    assert infer_deposit_addresses(graph, matcher()) == []


def test_sweeps_to_an_unlabelled_address_prove_nothing():
    graph = sweep_graph()
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = outflows(**{OTHER: (4, 40.0)})
    assert infer_deposit_addresses(graph, matcher()) == []


def test_sending_to_a_labelled_deposit_wallet_marks_a_customer_not_a_deposit_address():
    """Etherscan labels some deposit addresses. A wallet whose outflows go to
    one of those is the customer who owns it -- deposits sweep to hot wallets,
    never to other deposit addresses."""
    graph = sweep_graph()
    labelled_deposit = matcher(**{HOT: {"exchange": "Binance", "label": "Binance: Deposit 7",
                                        "type": "deposit_wallet"}})
    assert infer_deposit_addresses(graph, labelled_deposit) == []


def test_the_seed_and_labelled_wallets_are_never_inferred():
    graph = sweep_graph()
    graph.nodes[SEED]["outflows_by_counterparty"] = outflows(**{HOT: (3, 30.0)})
    found = infer_deposit_addresses(graph, matcher())
    assert SEED not in [m.address for m in found]
    assert HOT not in [m.address for m in found]


def test_dust_sweeps_are_not_evidence():
    graph = sweep_graph()
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = outflows(**{HOT: (3, 0.0001)})
    assert infer_deposit_addresses(graph, matcher(), DepositInferenceConfig()) == []


def test_an_unexpanded_address_has_no_history_to_read():
    """At the depth limit the outgoing history was never fetched, so nothing
    can be inferred -- the rule reads evidence, it does not guess."""
    graph = sweep_graph()
    del graph.nodes[DEPOSIT]["outflows_by_counterparty"]
    assert infer_deposit_addresses(graph, matcher()) == []


# ---------------------------------------------------------------------------
# It scores as the weaker attribution it is
# ---------------------------------------------------------------------------
def test_an_inferred_match_scores_half_directness_and_says_why():
    found = infer_deposit_addresses(sweep_graph(), matcher())
    component = _match_directness(found[0])
    assert component.raw_value == 0.5
    assert "Inferred, not labelled" in component.explanation
    assert "Only Binance can confirm" in component.explanation


def test_an_inferred_match_scores_below_a_labelled_wallet_at_the_same_distance():
    graph = sweep_graph()
    inferred = infer_deposit_addresses(graph, matcher())[0]
    exact = ExchangeMatcher.primary_match(matcher().annotate(graph))
    same_depth_exact = type(exact)(**{**exact.__dict__, "depth": inferred.depth,
                                      "address": inferred.address})
    weaker = score_case(graph, SEED, inferred, max_depth=4).score
    stronger = score_case(graph, SEED, same_depth_exact, max_depth=4).score
    assert weaker < stronger


def test_a_label_file_match_wins_a_tie_on_distance():
    graph = sweep_graph()
    inferred = infer_deposit_addresses(graph, matcher())
    exact = matcher().annotate(graph)
    tied = [type(inferred[0])(**{**inferred[0].__dict__, "depth": exact[0].depth})]
    assert ExchangeMatcher.primary_match(exact + tied).inferred is False


# ---------------------------------------------------------------------------
# Second adversarial pass
# ---------------------------------------------------------------------------
def test_paying_into_an_exchange_contract_wallet_marks_a_customer():
    """The label audit typed deposit forwarders as contract wallets; a wallet
    that pays one twice is the customer who owns the forwarder, not a deposit
    address of the exchange."""
    graph = sweep_graph()
    forwarder = matcher(**{HOT: {"exchange": "Binance", "label": "Binance: Deposit Forwarder",
                                  "type": "contract_wallet"}})
    assert infer_deposit_addresses(graph, forwarder) == []


def test_a_capped_history_is_said_to_be_most_recent_not_every():
    graph = sweep_graph(sweeps=200)
    graph.nodes[DEPOSIT]["outgoing_history_capped"] = True
    found = infer_deposit_addresses(graph, matcher())
    assert found[0].evidence["outgoing_history_capped"] is True
    text = describe(found[0], "ETH")
    assert "most recent outgoing transfers (older history exists" in text
    assert "Every one of its 200 outgoing transfers went" not in text
