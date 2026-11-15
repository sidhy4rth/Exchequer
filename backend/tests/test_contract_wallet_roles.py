"""Roles for the older exchange contract wallets, measured on chain (#253).

scripts/measure_contract_wallet_roles.py read, keylessly from Blockscout,
whether each role-less contract_wallet is where the exchange's deposit
addresses sweep. Its answers are in tests/fixtures/contract_wallet_roles.json
(written by its --record, not by hand); these tests read only that file and
the shipped label files, never the network.
"""
from __future__ import annotations

import json

import pytest

from app import config, never_flag
from app.exchange_matcher import CONTRACT_WALLET
from scripts import measure_contract_wallet_roles as mcr

from conftest import addr

EVIDENCE = json.loads(mcr.EVIDENCE.read_text(encoding="utf-8"))
CHAINS = [c for c in EVIDENCE if not c.startswith("_")]


def _labels(chain):
    return json.loads(config.CHAINS[chain].labels_path.read_text(encoding="utf-8"))["labels"]


def _given(chain):
    return {a: e for a, e in EVIDENCE[chain].items() if e["role"]}


# -- the evidence file -------------------------------------------

@pytest.mark.parametrize("chain", CHAINS)
def test_every_measured_row_is_a_contract_wallet_and_every_roleless_one_was_measured(chain):
    labels = _labels(chain)
    for address in EVIDENCE[chain]:
        assert labels[address]["type"] == CONTRACT_WALLET, address
    assert set(mcr.roleless(chain)) <= set(EVIDENCE[chain])


@pytest.mark.parametrize("chain", CHAINS)
def test_a_role_stands_on_enough_sweepers_none_of_them_labelled(chain):
    labels = _labels(chain)
    for address, seen in _given(chain).items():
        assert seen["role"] == mcr.ROLE == "hot_wallet"
        assert seen["sweepers"] == len(seen["sweeper_addresses"]) >= EVIDENCE["_meta"]["min_sweepers"] == mcr.MIN_SWEEPERS
        assert seen["sweepers"] <= seen["sampled"] <= seen["unlabelled_senders"]
        assert not set(seen["sweeper_addresses"]) & set(labels), address
        assert never_flag.kind(chain, address) == never_flag.EXCHANGE


@pytest.mark.parametrize("chain", CHAINS)
def test_every_wallet_left_roleless_says_why(chain):
    for address, seen in EVIDENCE[chain].items():
        if not seen["role"]:
            assert seen["why"] and "role" not in _labels(chain)[address], address


# -- the measurement itself, on made-up flows ----------------------------------------

WALLET, OTHER, PAID = addr("aa11"), addr("0bad"), addr("9a1d")


def _flow(party, contract=False, scam=False):
    return {"party": party, "is_contract": contract, "is_scam": scam, "block": 100}


def _run(monkeypatch, inflow, outflows, code=None, chain="ethereum"):
    def flows(base, address, direction, pages):
        return (inflow, False) if direction == "to" else (outflows.get(address, []), False)
    monkeypatch.setattr(mcr, "_flows", flows)
    row = {"exchange": "Bybit", "label": "Bybit: Reserve Wallet 1", "type": CONTRACT_WALLET}
    labels = {addr("1abe1"): {"exchange": "Bybit"}, addr("2abe1"): {"exchange": "Kraken"}}
    return mcr.measure(chain, WALLET, row, labels, code)


def _senders(n):
    return [addr(f"5e{i:02x}") for i in range(n)]


def test_it_gives_the_role_when_enough_senders_sweep_only_into_the_wallet(monkeypatch):
    senders = _senders(12)
    outflows = {s: [_flow(WALLET), _flow(WALLET), _flow(addr("1abe1"))] for s in senders}  # same exchange: fine
    seen = _run(monkeypatch, [_flow(s) for s in senders], outflows)
    assert seen["role"] == "hot_wallet" and seen["sweepers"] == 12 and seen["sampled"] == 12


def test_it_stays_silent_on_ordinary_senders(monkeypatch):
    senders = _senders(12)
    paying_elsewhere = {s: [_flow(WALLET), _flow(WALLET), _flow(OTHER)] for s in senders}
    assert _run(monkeypatch, [_flow(s) for s in senders], paying_elsewhere)["role"] is None
    to_another_exchange = {s: [_flow(WALLET), _flow(WALLET), _flow(addr("2abe1"))] for s in senders}
    assert _run(monkeypatch, [_flow(s) for s in senders], to_another_exchange)["role"] is None
    once = {s: [_flow(WALLET)] for s in senders}
    assert _run(monkeypatch, [_flow(s) for s in senders], once)["role"] is None


def test_too_few_sweepers_labelled_contract_or_scam_senders_give_no_role(monkeypatch):
    senders = _senders(mcr.MIN_SWEEPERS - 1)
    sweeping = {s: [_flow(WALLET), _flow(WALLET)] for s in _senders(20)}
    assert _run(monkeypatch, [_flow(s) for s in senders], sweeping)["role"] is None
    excluded = ([_flow(s, contract=True) for s in _senders(20)[:10]] + [_flow(s, scam=True) for s in _senders(20)[10:]]
                + [_flow(addr("1abe1"))])
    seen = _run(monkeypatch, excluded, sweeping)
    assert seen["role"] is None and seen["unlabelled_senders"] == 0


def test_a_forwarder_or_an_unread_chain_is_never_measured(monkeypatch):
    senders = _senders(12)
    sweeping = {s: [_flow(WALLET), _flow(WALLET)] for s in senders}
    forwarder = "0x" + "6000" * 3 + "f1"  # CALL, no PUSH4: the forwarder shape check_label_code knows
    assert mcr.clc.classify(forwarder)[0] == mcr.clc.FORWARDER
    assert _run(monkeypatch, [_flow(s) for s in senders], sweeping, code=forwarder)["role"] is None
    assert _run(monkeypatch, [_flow(s) for s in senders], sweeping, chain="bsc")["role"] is None


def test_zero_value_token_transfers_are_left_out(monkeypatch):
    def pages(base, path, params, n):
        if "token-transfers" not in path:
            return [], False
        return [{"from": {"hash": WALLET}, "to": {"hash": OTHER}, "total": {"value": "0"}, "token": {}},
                {"from": {"hash": WALLET}, "to": {"hash": PAID}, "total": {"value": "5"}, "token": {}}], False
    monkeypatch.setattr(mcr, "_pages", pages)
    flows, _ = mcr._flows("https://example.invalid", WALLET, "from", 1)
    assert [f["party"] for f in flows] == [PAID]


def test_a_sender_blockscout_gives_up_on_is_never_a_sweeper(monkeypatch):
    senders = _senders(12)

    def flows(base, address, direction, pages):
        if direction == "to":
            return [_flow(s) for s in senders], False
        raise RuntimeError("no answer")
    monkeypatch.setattr(mcr, "_flows", flows)
    row = {"exchange": "Bybit", "label": "Bybit: Reserve Wallet 1", "type": CONTRACT_WALLET}
    seen = mcr.measure("ethereum", WALLET, row, {}, None)
    assert seen["role"] is None and seen["sweepers"] == 0 and seen["senders_unread"] == 12


def test_the_evidence_file_is_exactly_what_the_script_writes():
    assert mcr.dump(EVIDENCE) == mcr.EVIDENCE.read_text(encoding="utf-8")
    assert EVIDENCE["_meta"]["source"] == "Blockscout public API v2, keyless"


def test_a_held_row_is_measured_but_given_no_role():
    for address in mcr.HELD:
        (chain,) = [c for c in CHAINS if address in EVIDENCE[c]]
        seen = EVIDENCE[chain][address]
        assert seen["role"] is None and "role not set" in seen["why"]
        assert "role" not in _labels(chain)[address]
