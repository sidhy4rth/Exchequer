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


# -- JSON-RPC errors are failures, not answers (r1-scripts-6) -----------------------
RATE_LIMITED = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "rate limited"}}


def nodes(*bodies_per_node):
    """An httpx client whose Ethereum nodes answer in turn: node i gives bodies_per_node[i](method)."""
    def handle(request: httpx.Request) -> httpx.Response:
        index = vc.ETHEREUM_NODES.index(str(request.url).rstrip("/"))
        method = json.loads(request.content)["method"]
        return httpx.Response(200, json=bodies_per_node[index](method))
    return httpx.Client(transport=httpx.MockTransport(handle))


def live(http: httpx.Client):
    return lambda chain, digest, token: vc.read_live(http, chain, digest, token)


def recorded_eth(digest: str) -> dict:
    return answers("demo_1_ethereum.json")[digest]


def test_nodes_that_only_rate_limit_leave_the_transfer_unchecked_not_mismatched():
    report = _demo_report(1)
    report["appendix"]["transactions"] = report["appendix"]["transactions"][:1]
    checks = verify(report, live(nodes(lambda _m: RATE_LIMITED, lambda _m: RATE_LIMITED)))
    assert [c.outcome for c in checks] == [UNCHECKED]
    assert exit_code(checks) == 2


def test_one_node_without_history_and_one_rate_limited_is_unchecked():
    report = _demo_report(1)
    report["appendix"]["transactions"] = report["appendix"]["transactions"][:1]
    checks = verify(report, live(nodes(lambda _m: {"jsonrpc": "2.0", "id": 1, "result": None},
                                       lambda _m: RATE_LIMITED)))
    assert [c.outcome for c in checks] == [UNCHECKED]


def test_both_nodes_saying_null_is_still_a_mismatch():
    report = _demo_report(1)
    report["appendix"]["transactions"] = report["appendix"]["transactions"][:1]
    null = {"jsonrpc": "2.0", "id": 1, "result": None}
    checks = verify(report, live(nodes(lambda _m: null, lambda _m: null)))
    assert [c.outcome for c in checks] == [MISMATCH]


def test_a_native_transfer_whose_receipt_was_rate_limited_is_never_confirmed():
    report = _demo_report(1)
    first = report["appendix"]["transactions"][0]
    report["appendix"]["transactions"] = [first]
    saved = recorded_eth(first["hash"])

    def node(method):
        if method == "eth_getTransactionByHash":
            return {"jsonrpc": "2.0", "id": 1, "result": saved["transaction"]}
        return RATE_LIMITED

    checks = verify(report, live(nodes(node, node)))
    assert [c.outcome for c in checks] == [UNCHECKED]


def test_a_native_transfer_with_no_receipt_is_unchecked():
    report = _demo_report(1)
    first = report["appendix"]["transactions"][0]["hash"]
    saved = answers("demo_1_ethereum.json")
    saved[first] = {**saved[first], "receipt": None}
    assert outcomes(report, saved)[0] == UNCHECKED


def test_a_receipt_without_a_status_is_unchecked():
    report = _demo_report(1)
    first = report["appendix"]["transactions"][0]["hash"]
    saved = answers("demo_1_ethereum.json")
    saved[first] = {**saved[first], "receipt": {k: v for k, v in saved[first]["receipt"].items() if k != "status"}}
    assert outcomes(report, saved)[0] == UNCHECKED


# -- a provider's error or odd answer is a failure, not an answer (r1-scripts-6) ------
def tronscan(body, status: int = 200) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(status, json=body)))


def first_only(report: dict) -> dict:
    report["appendix"]["transactions"] = report["appendix"]["transactions"][:1]
    return report


def test_a_tronscan_rate_limit_answer_is_unchecked_not_a_mismatch():
    # TronScan's refusal can come as HTTP 200 with an error body and no transaction.
    checks = verify(first_only(_demo_report(12)),
                    live(tronscan({"Error": "request rate exceeded the allowed_rps(5)"})))
    assert [c.outcome for c in checks] == [UNCHECKED]
    assert exit_code(checks) == 2


def test_a_tronscan_answer_that_is_not_an_object_is_unchecked():
    checks = verify(first_only(_demo_report(12)), live(tronscan(["not", "a", "transaction"])))
    assert [c.outcome for c in checks] == [UNCHECKED]


def test_an_empty_tronscan_answer_is_still_a_mismatch():
    # {} is how TronScan says it has no such transaction: a real disagreement.
    checks = verify(first_only(_demo_report(12)), live(tronscan({})))
    assert [c.outcome for c in checks] == [MISMATCH]


def test_an_ethereum_result_that_is_not_an_object_is_unchecked():
    weird = {"jsonrpc": "2.0", "id": 1, "result": "0xdeadbeef"}
    checks = verify(first_only(_demo_report(1)), live(nodes(lambda _m: weird, lambda _m: weird)))
    assert [c.outcome for c in checks] == [UNCHECKED]


def test_a_log_of_the_wrong_shape_is_unchecked_not_a_crash():
    # A node's receipt whose logs are not objects is an odd answer, not a disagreement.
    report = _demo_report(3, follow_on=True)
    first = report["appendix"]["transactions"][0]["hash"]
    saved = answers("demo_3_follow_on_usdt.json")
    saved[first] = {**saved[first], "receipt": {**saved[first]["receipt"], "logs": ["not a log", 7]}}
    checks = verify(report, replay(saved))
    assert [c.outcome for c in checks] == [UNCHECKED]


def test_a_tronscan_transfer_list_of_the_wrong_shape_is_unchecked_not_a_crash():
    report, saved = first_only(_demo_report(12)), answers("demo_12_tron.json")
    first = report["appendix"]["transactions"][0]["hash"]
    saved[first] = {**saved[first], "trc20TransferInfo": ["not a transfer"]}
    assert [c.outcome for c in verify(report, replay(saved))] == [UNCHECKED]


def test_a_transfer_missing_from_a_recording_is_unchecked_not_a_mismatch(monkeypatch, capsys, tmp_path):
    # A read that failed while recording is not saved; replayed, it is still a failed read.
    saved = answers("demo_12_tron.json")
    missing = _demo_report(12)["appendix"]["transactions"][0]["hash"]
    del saved[missing]
    recording = tmp_path / "recording.json"
    recording.write_text(json.dumps(saved), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["verify_case", "--demo", "12", "--recorded", str(recording)])
    assert vc.main() == 2
    out = capsys.readouterr().out
    assert "5 transfers: 4 confirmed, 0 mismatch, 1 unchecked" in out and "not in the recording" in out


def test_the_script_rereads_through_the_apps_own_module():
    # POST /trace/{id}/recheck and this script are one implementation (app/second_provider.py).
    from app import second_provider

    assert vc.read_live is second_provider.read_live and vc.Check is second_provider.Check
