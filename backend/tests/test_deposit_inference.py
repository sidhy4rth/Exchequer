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


def test_the_balance_is_stated_in_the_chains_coin_on_a_token_trace():
    # On a USDT trace the lookup reads the ETH left for gas; calling it USDT
    # would misstate the evidence.
    found = infer_deposit_addresses(sweep_graph(), matcher(), balance_of=lambda a: 0.0123,
                                    native_symbol="ETH")
    assert found[0].evidence["current_balance_symbol"] == "ETH"
    text = describe(found[0], "ETH")
    assert "0.0123 ETH" in text and "USDT" not in text


# ---------------------------------------------------------------------------
# Dust is dust in every asset, and a flagged wallet is not unlabelled
# (audit r2-g2-documented-claims-vs-code-7-6)
# ---------------------------------------------------------------------------
def test_usdt_dust_sweeps_are_not_evidence():
    # 0.0012 USDT is a fraction of a cent: a poisoning lookalike's dust sends
    # to a hot wallet, not a deposit address's sweeps.
    graph = sweep_graph()
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = outflows(**{HOT: (2, 0.0012)})
    assert infer_deposit_addresses(graph, matcher(), asset="USDT") == []
    assert infer_deposit_addresses(graph, matcher(), asset="TRX") == []


def test_real_usdt_sweeps_still_are():
    graph = sweep_graph()
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = outflows(**{HOT: (2, 2400.0)})
    (found,) = infer_deposit_addresses(graph, matcher(), asset="USDT")
    assert found.evidence["thresholds_applied"]["min_total_native"] == 1.0


def test_the_floor_is_the_assets_own():
    from app.deposit_inference import dust_floor
    assert dust_floor("ETH") == 0.001 and dust_floor("USDT") == 1.0 and dust_floor("TRX") == 10.0


def test_a_risk_flagged_wallet_is_never_inferred():
    # A wallet the screening lists flag (here, an address-poisoning lookalike)
    # has a label of its own: the rule is for unlabelled wallets.
    graph = sweep_graph()
    found = infer_deposit_addresses(graph, matcher(), asset="ETH", is_flagged=lambda a: a == DEPOSIT)
    assert found == []
    assert not graph.nodes[DEPOSIT].get("inferred_exchange")


def test_a_usdt_trace_does_not_name_a_dust_sweeping_lookalike(monkeypatch):
    """The finding's case as a whole trace: 5,000 USDT to lookalike L, whose
    only USDT outflows are two 0.0006 dust sends to Binance 14."""
    from contextlib import contextmanager

    from app import pipeline
    from app.etherscan_client import Transaction
    from app.pipeline import TraceRequest

    lookalike = addr("100ca1")

    def tx(n, src, dst, value):
        return Transaction(hash=f"0x{n:064x}", from_address=src, to_address=dst, value_native=value,
                           value_wei=int(value * 1e6), timestamp=1_700_000_000 + n, block_number=100 + n,
                           is_error=False, asset="USDT")

    history = [tx(1, SEED, lookalike, 5000.0), tx(2, lookalike, HOT, 0.0006), tx(3, lookalike, HOT, 0.0006)]

    class Client:
        def get_outgoing_transactions(self, address, limit=None):
            return [t for t in history if t.from_address == address]

    @contextmanager
    def open_source(_chain, _asset):
        yield Client()

    monkeypatch.setattr(pipeline, "open_source", open_source)
    monkeypatch.setattr(pipeline, "get_matcher", lambda key: matcher())
    monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
    result = pipeline.run_trace(TraceRequest(address=SEED, chain="ethereum", asset="USDT", max_depth=3))
    assert result["inferred_deposits"] == []
    assert result["exchange_address"] != lookalike


# ---------------------------------------------------------------------------
# 8 Nov check: the floor is per sweep, and a deposit address sends on what it
# received (r2-g2-documented-claims-vs-code-7-6)
# ---------------------------------------------------------------------------
def test_the_dust_floor_applies_to_each_sweep_not_their_total():
    graph = sweep_graph()
    # Two 0.6 USDT sends total 1.2, over a 1 USDT floor; neither is a sweep.
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = {
        HOT: {"count": 2, "total": 1.2, "min": 0.6, "first": 1, "last": 2}}
    assert infer_deposit_addresses(graph, matcher(), asset="USDT") == []
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = {
        HOT: {"count": 2, "total": 1.001, "min": 0.001, "first": 1, "last": 2}}
    assert infer_deposit_addresses(graph, matcher(), asset="USDT") == []


def test_a_wallet_that_kept_what_it_received_is_not_a_deposit_address():
    # It received the victim's 5,000 and sent on 6: an exchange sweeps a
    # deposit address, it does not leave 99.9% of the money in it.
    graph = make_graph([(SEED, DEPOSIT, 5000.0), (DEPOSIT, HOT, 6.0)], seed=SEED, exchanges={HOT: "Binance"})
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = {
        HOT: {"count": 2, "total": 6.0, "min": 3.0, "first": 1, "last": 2}}
    assert infer_deposit_addresses(graph, matcher(), asset="USDT") == []


def test_a_deposit_address_that_swept_what_it_received_still_is():
    graph = make_graph([(SEED, DEPOSIT, 5000.0), (DEPOSIT, HOT, 4999.0)], seed=SEED, exchanges={HOT: "Binance"})
    graph.nodes[DEPOSIT]["outflows_by_counterparty"] = {
        HOT: {"count": 2, "total": 4999.0, "min": 2000.0, "first": 1, "last": 2}}
    (found,) = infer_deposit_addresses(graph, matcher(), asset="USDT")
    assert found.evidence["swept_after_arrival_native"] == 4999.0
    assert found.evidence["received_on_trace_native"] == 5000.0
    assert found.evidence["thresholds_applied"]["min_sweep_native"] == 1.0


def test_the_graph_builder_records_each_counterpartys_smallest_outflow():
    from app.etherscan_client import Transaction
    from app.graph_builder import TraceConfig, build_trace_graph

    def tx(n, src, dst, value):
        return Transaction(hash=f"0x{n:064x}", from_address=src, to_address=dst, value_native=value,
                           value_wei=int(value * 1e18), timestamp=1_700_000_000 + n, block_number=100 + n,
                           is_error=False, asset="ETH")
    history = [tx(1, SEED, DEPOSIT, 5.0), tx(2, DEPOSIT, HOT, 2.0), tx(3, DEPOSIT, HOT, 0.5)]

    class Client:
        def get_outgoing_transactions(self, address, limit=None):
            return [t for t in history if t.from_address == address]

    graph = build_trace_graph(SEED, Client(), cfg=TraceConfig(max_depth=2), is_terminal=lambda a: a == HOT).graph
    assert graph.nodes[DEPOSIT]["outflows_by_counterparty"][HOT]["min"] == 0.5


@pytest.mark.parametrize("sends", [[0.6, 0.6], [1.0, 0.001], [3.0, 3.0]],
                         ids=["2 x 0.6 USDT", "1.0 + 0.001 USDT", "2 x 3 USDT"])
def test_a_usdt_trace_does_not_name_a_lookalike_that_kept_the_money(monkeypatch, sends):
    """The checker's bypasses (8 Nov): lookalike L receives the victim's
    5,000 USDT and sends a few dollars to Binance 14 in two transfers."""
    from contextlib import contextmanager

    from app import pipeline
    from app.etherscan_client import Transaction
    from app.pipeline import TraceRequest

    lookalike = addr("100ca1")

    def tx(n, src, dst, value):
        return Transaction(hash=f"0x{n:064x}", from_address=src, to_address=dst, value_native=value,
                           value_wei=int(value * 1e6), timestamp=1_700_000_000 + n, block_number=100 + n,
                           is_error=False, asset="USDT")

    history = [tx(1, SEED, lookalike, 5000.0)] + [tx(2 + i, lookalike, HOT, v) for i, v in enumerate(sends)]

    class Client:
        def get_outgoing_transactions(self, address, limit=None):
            return [t for t in history if t.from_address == address]

    @contextmanager
    def open_source(_chain, _asset):
        yield Client()

    monkeypatch.setattr(pipeline, "open_source", open_source)
    monkeypatch.setattr(pipeline, "get_matcher", lambda key: matcher())
    monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
    result = pipeline.run_trace(TraceRequest(address=SEED, chain="ethereum", asset="USDT", max_depth=3))
    assert result["inferred_deposits"] == []
    assert result["exchange_address"] != lookalike
