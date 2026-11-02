"""verify_case re-reads a report's transfers from a provider the trace did not use.

The fixtures are real responses recorded from those providers by the script itself,
so these tests touch no network. What must never happen: a changed report passing,
or a transfer the run could not read being counted as confirmed.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import httpx
import pytest

from scripts import verify_case as vc
from scripts.verify_case import CONFIRMED, MISMATCH, UNCHECKED, _demo_report, exit_code, verify

FIXTURES = Path(__file__).parent / "fixtures" / "verify_case"
RECORDED = [(12, False, "demo_12_tron.json", 5),
            (1, False, "demo_1_ethereum.json", 16),
            (3, True, "demo_3_follow_on_usdt.json", 1)]


def answers(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def replay(saved: dict):
    return lambda _chain, digest, _token: saved.get(digest) or {}


def outcomes(report: dict, saved: dict) -> list[str]:
    return [check.outcome for check in verify(report, replay(saved))]


@pytest.mark.parametrize("demo, follow_on, fixture, count", RECORDED)
def test_a_real_demo_passes(demo, follow_on, fixture, count):
    checks = verify(_demo_report(demo, follow_on), replay(answers(fixture)))
    assert [c.outcome for c in checks] == [CONFIRMED] * count
    assert exit_code(checks) == 0


@pytest.mark.parametrize("demo, follow_on, fixture, count", RECORDED)
@pytest.mark.parametrize("field, tampered", [
    ("value_native", lambda v: v + 1),
    ("value_native", lambda v: v * 1.001),
    ("to", lambda _v: "0x" + "9" * 40),
    ("from", lambda _v: "0x" + "9" * 40),
])
def test_a_tampered_report_fails(demo, follow_on, fixture, count, field, tampered):
    report = copy.deepcopy(_demo_report(demo, follow_on))
    transfer = report["appendix"]["transactions"][0]
    transfer[field] = tampered(transfer[field])
    checks = verify(report, replay(answers(fixture)))
    assert checks[0].outcome == MISMATCH
    assert [c.outcome for c in checks[1:]] == [CONFIRMED] * (count - 1)
    assert exit_code(checks) == 1


@pytest.mark.parametrize("demo, follow_on, fixture", [r[:3] for r in RECORDED])
def test_a_transaction_the_provider_does_not_have_is_a_mismatch(demo, follow_on, fixture):
    report = _demo_report(demo, follow_on)
    assert outcomes(report, {})[0] == MISMATCH


def test_a_failed_tron_transaction_is_a_mismatch():
    report, saved = _demo_report(12), answers("demo_12_tron.json")
    first = report["appendix"]["transactions"][0]["hash"]
    saved[first] = {**saved[first], "contractRet": "REVERT"}
    assert outcomes(report, saved)[0] == MISMATCH


def test_a_failed_ethereum_transaction_is_a_mismatch():
    report, saved = _demo_report(1), answers("demo_1_ethereum.json")
    first = report["appendix"]["transactions"][0]["hash"]
    saved[first] = {**saved[first], "receipt": {"status": "0x0"}}
    assert outcomes(report, saved)[0] == MISMATCH


@pytest.mark.parametrize("demo, fixture", [(1, "demo_1_ethereum.json"), (12, "demo_12_tron.json")])
def test_a_transfer_moved_by_a_contract_is_unchecked_never_confirmed(demo, fixture):
    report = copy.deepcopy(_demo_report(demo))
    report["appendix"]["transactions"][0]["internal"] = True
    checks = verify(report, replay(answers(fixture)))
    assert checks[0].outcome == UNCHECKED and "contract call" in checks[0].detail
    assert exit_code(checks) == 2


def test_a_provider_failure_is_unchecked_never_confirmed():
    def down(_chain, _digest, _token):
        raise httpx.ConnectError("no route")

    checks = verify(_demo_report(12), down)
    assert {c.outcome for c in checks} == {UNCHECKED}
    assert exit_code(checks) == 2


def test_a_chain_this_script_does_not_cover_is_unchecked():
    report = {"case": {"chain": "Polygon PoS", "asset": "POL"},
              "appendix": {"transactions": [{"hash": "0xabc", "from": "0x1", "to": "0x2", "value_native": 1}]}}
    checks = verify(report, lambda *_: pytest.fail("must not read a chain it cannot check"))
    assert [c.outcome for c in checks] == [UNCHECKED] and "Polygon" in checks[0].detail


def test_a_report_with_no_transfers_proves_nothing():
    assert exit_code(verify({"case": {"chain": "Tron", "asset": "USDT"}, "appendix": {"transactions": []}}, None)) == 2


def test_a_mismatch_outranks_anything_unchecked():
    assert exit_code([vc.Check("a", UNCHECKED), vc.Check("b", MISMATCH), vc.Check("c", CONFIRMED)]) == 1


def test_the_command_line_replays_a_recording_with_no_network(monkeypatch, capsys):
    def no_network(*_args, **_kwargs):
        raise AssertionError("--recorded must not read the network")

    monkeypatch.setattr(vc, "read_live", no_network)
    monkeypatch.setattr(sys, "argv", ["verify_case", "--demo", "12", "--recorded",
                                      str(FIXTURES / "demo_12_tron.json")])
    assert vc.main() == 0
    assert "5 transfers: 5 confirmed, 0 mismatch, 0 unchecked" in capsys.readouterr().out
