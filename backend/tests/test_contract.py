"""Case contract v2 (app/contracts): what every trace result promises its readers."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import networkx as nx
import pytest
from pydantic import ValidationError

from app.contracts import CONTRACT_VERSION, read_case, upgrade
from app.pipeline import _all_transfers
from scripts import build_contract_fixtures

DATA = Path(__file__).resolve().parent.parent / "data"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contract"
DEMOS = json.loads((DATA / "recorded_demos.json").read_text())
BY_DEMO = {d["demo"]: d["result"] for d in DEMOS}


@pytest.mark.parametrize("demo", sorted(BY_DEMO))
def test_every_recorded_demo_reads_as_v2(demo):
    case = read_case(BY_DEMO[demo])
    assert case.contract_version == CONTRACT_VERSION
    # An address-only trace has no reported amount: nobody reported one.
    assert case.intake.mode == "address" and case.reported_amount is None
    assert len(case.transfers) == len(BY_DEMO[demo]["transfers"])


@pytest.mark.parametrize("demo,kind,source", [
    (6, "deposit_inferred", "inference"),
    (9, "exchange_wallet", "label_file"),     # Binance-Hot 7: the exchange's own wallet
    (11, "exchange_wallet", "label_file"),
    (12, "exchange_wallet", "live_tag"),      # Flipster, from TronScan at trace time
    (5, "exchange_wallet", "label_file"),     # Binance 17, on a reverse trace
])
def test_attribution_kind_and_source(demo, kind, source):
    attr = read_case(BY_DEMO[demo]).attribution
    assert (attr.kind, attr.source) == (kind, source)
    assert attr.address == BY_DEMO[demo]["exchange_address"]


@pytest.mark.parametrize("demo", [1, 2, 4, 8])
def test_no_exchange_means_no_attribution(demo):
    assert read_case(BY_DEMO[demo]).attribution is None


def test_a_labelled_deposit_wallet_is_a_deposit_label():
    # No recorded demo ends at a labelled deposit address, so this one is
    # built: the minimum the matcher produces for a deposit_wallet match.
    result = {"exchange": "Bitget", "exchange_address": "0xdep", "exchange_label": "Bitget Dep",
              "attribution_inferred": False, "transfers": [],
              "matches": [{"address": "0xdep", "wallet_type": "deposit_wallet", "label": "Bitget Dep: 0xdep", "depth": 1}]}
    attr = read_case(result).attribution
    assert (attr.kind, attr.source, attr.wallet_type) == ("deposit_label", "label_file", "deposit_wallet")


@pytest.mark.parametrize("demo", sorted(BY_DEMO))
def test_upgrade_adds_fields_and_changes_no_v1_field(demo):
    v1 = BY_DEMO[demo]
    before = copy.deepcopy(v1)
    v2 = upgrade(v1)
    assert v1 == before, "upgrade must not modify its input"

    # Rows may gain fields (a transfer's block, a freeze's frozen_on and
    # event_tx, a graph node's expanded); every field a row had is kept.
    def kept(rows, new_rows):
        for old, new in zip(rows, new_rows, strict=True):
            assert {k: new[k] for k in old} == old
    for key, value in v1.items():
        if key in ("transfers", "risk_matches"):
            kept(value, v2[key])
        elif key == "graph":
            assert {**v2[key], "nodes": value["nodes"]} == value
            kept(value["nodes"], v2[key]["nodes"])
        elif key != "follow_ons":
            assert v2[key] == value, key
    assert upgrade(v2) == v2, "upgrade must be idempotent"


def test_follow_on_traces_are_upgraded_too():
    v2 = upgrade(BY_DEMO[3])
    assert v2["follow_ons"], "demo 3 has a follow-on after a swap"
    for follow in v2["follow_ons"]:
        assert read_case(follow["result"]).contract_version == CONTRACT_VERSION


def test_estimates_carry_prorata_and_conservative_is_the_smallest():
    case = read_case(BY_DEMO[6])
    assert case.estimates.prorata == BY_DEMO[6]["prorata"]["estimated"]
    assert case.estimates.conservative == case.estimates.prorata
    assert case.estimates.fifo is None and case.estimates.libr is None


def test_v2_parts_reject_unknown_keys():
    v2 = upgrade(BY_DEMO[9])
    v2["attribution"]["kind_guess"] = "hot"
    with pytest.raises(ValidationError):
        read_case(v2)


def test_unknown_attribution_kind_is_rejected():
    v2 = upgrade(BY_DEMO[9])
    v2["attribution"]["kind"] = "hot_wallet"
    with pytest.raises(ValidationError):
        read_case(v2)


def test_pipeline_transfers_carry_the_block():
    graph = nx.DiGraph()
    graph.add_edge("A", "B", transactions=[
        {"hash": "0x1", "value_native": 1.0, "timestamp": 100, "block_number": 7, "internal": False}])
    (row,) = _all_transfers(graph)
    assert row["block"] == 7
    assert read_case({"transfers": [row]}).transfers[0].block == 7


def test_fixtures_match_what_the_script_would_write():
    expected = build_contract_fixtures.build(DEMOS)
    on_disk = {p.name for p in FIXTURES.glob("*.json")}
    assert on_disk == set(expected), "run: python -m scripts.build_contract_fixtures"
    for name, content in expected.items():
        assert (FIXTURES / name).read_text() == build_contract_fixtures.dumps(content), (
            f"{name} is stale: run python -m scripts.build_contract_fixtures")


def test_every_fixture_is_a_valid_v2_case():
    index = json.loads((FIXTURES / "index.json").read_text())
    for name in index["fixtures"]:
        read_case(json.loads((FIXTURES / name).read_text()))
    assert index["kinds_without_a_recorded_example"] == ["deposit_label"]


def test_an_exchange_funder_typed_deposit_is_an_exchange_wallet():
    """The contract's kind agrees with the report's (r1-labels-data-5)."""
    result = {"exchange": "Binance", "exchange_address": "0xfun", "exchange_label": "Binance: Deposit Funder",
              "attribution_inferred": False, "transfers": [],
              "matches": [{"address": "0xfun", "wallet_type": "deposit_wallet", "label": "Binance: Deposit Funder",
                           "depth": 1}]}
    assert read_case(result).attribution.kind == "exchange_wallet"


# -- the contract's kind and the report's kind agree (r2-g2-documented-claims-vs-code-7-10)
def test_a_live_tag_saying_deposit_is_not_a_deposit_label():
    """TronScan's word is not a checked label: a tag reading 'Deposit' must not
    become a KYC-grade deposit_label, which case.md says asks for the customer."""
    result = {"exchange": "Binance", "exchange_address": "Tdep", "exchange_label": "Binance Deposit (TronScan tag, read live)",
              "attribution_inferred": False, "transfers": [],
              "matches": [{"address": "Tdep", "wallet_type": "deposit_wallet", "depth": 1}],
              "live_tags": {"enabled": True, "found": [{"address": "Tdep", "label": "Binance Deposit"}]}}
    attr = read_case(result).attribution
    assert (attr.kind, attr.source, attr.wallet_type) == ("exchange_wallet", "live_tag", "deposit_wallet")


# The contract's (kind, source) read as the report's kind: one table, both ways.
REPORT_KIND = {("deposit_inferred", "inference"): "inferred_deposit",
               ("deposit_label", "label_file"): "labelled_deposit",
               ("exchange_wallet", "label_file"): "exchange_wallet",
               ("exchange_wallet", "live_tag"): "explorer_tag"}


def _parity_cases():
    deposit_tag = {"exchange": "Binance", "exchange_address": "Tdep", "attribution_inferred": False,
                   "transfers": [], "matches": [{"address": "Tdep", "wallet_type": "deposit_wallet"}],
                   "live_tags": {"found": [{"address": "Tdep", "label": "Binance Deposit"}]}}
    labelled = {"exchange": "Bitget", "exchange_address": "0xdep", "attribution_inferred": False, "transfers": [],
                "matches": [{"address": "0xdep", "wallet_type": "deposit_wallet"}]}
    fixtures = [json.loads(p.read_text()) for p in sorted(FIXTURES.glob("*.json")) if p.name != "index.json"]
    return [*BY_DEMO.values(), *fixtures, deposit_tag, labelled]


@pytest.mark.parametrize("result", _parity_cases())
def test_the_contract_and_the_report_name_the_same_kind(result):
    from app.report import attribution_kind

    attr = read_case({k: v for k, v in result.items() if k != "attribution"}).attribution
    if attr is None:
        assert not result.get("exchange")
        return
    assert REPORT_KIND[(attr.kind, attr.source)] == attribution_kind(
        {k: v for k, v in result.items() if k != "attribution"})
