"""Tests for re-checking held Tether freezes against the USDT contract (--recheck-lifts).

A freeze Tether has lifted must not go on reading "Frozen by Tether". The failure
that matters on the other side is a bad answer read as a lift: an error page, a
rate limit or one endpoint's word alone must never remove a freeze.

The answers are real ones, recorded from the public endpoints on 2026-11-15
(fixtures/tether_lifts/recorded.json); nothing here reads the network.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app import config
from scripts import import_all_lists as lists
from scripts import import_tether_freezes as freezes
from scripts.import_all_lists import Family, run_family

from conftest import addr

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "tether_lifts" / "recorded.json").read_text())
STILL_FROZEN_TRON, LIFTED_TRON = RECORDED["tron_eth_call"]["addresses"]
RELEASE_TX = "094d2b9b4dd37bf621941524d2843557ea4b35a2dd6bca162bcf76cfe13b767c"
SHIPPED = config.DATA_DIR  # the lists in the repository, before a test points DATA_DIR elsewhere
ETH_FROZEN = "0x" + RECORDED["ethereum_eth_call"]["request"][0]["params"][0]["data"][-40:]


def _answers(name: str) -> dict[str, str]:
    """calldata -> result, from one recorded batch."""
    entry = RECORDED[name]
    results = {r["id"]: r["result"] for r in entry["response"]}
    return {call["params"][0]["data"]: results[call["id"]] for call in entry["request"]}


def endpoints(fail: tuple[str, ...] = (), once: tuple[str, ...] = ()):
    """An httpx client that answers like the recorded endpoints. URLs in `fail` answer 500;
    URLs in `once` answer 429 the first time."""
    eth_calls = {freezes.ETH_RPC: _answers("ethereum_eth_call"), freezes.ETH_RPC_2: _answers("ethereum_eth_call"),
                 freezes.TRON_RPC: _answers("tron_eth_call")}
    seen: set[str] = set()

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        if url in fail:
            return httpx.Response(500, text="server error")
        if url in once and url not in seen:
            seen.add(url)
            return httpx.Response(429, json={"error": {"code": -32005, "message": "rate limit exceeded"}})
        if url in eth_calls:
            body = json.loads(request.content)
            return httpx.Response(200, json=[{"jsonrpc": "2.0", "id": c["id"], "result": eth_calls[url][c["params"][0]["data"]]}
                                             for c in body])
        for name in ("trongrid_triggerconstantcontract", "trongrid_removed_events"):
            if url == RECORDED[name]["url"]:
                return httpx.Response(200, json=RECORDED[name]["response"])
        raise AssertionError(f"unexpected request to {url}")

    return httpx.Client(transport=httpx.MockTransport(handle))


def _entry(address: str, chain: str) -> dict:
    """The entry the list held for this address before the re-check."""
    if address in RECORDED["held_entries"]["labels"]:
        return RECORDED["held_entries"]["labels"][address]
    path = SHIPPED / ("frozen_labels_tron.json" if chain == "tron" else "frozen_labels.json")
    return json.loads(path.read_text())["labels"][address]


@pytest.fixture
def held(tmp_path, monkeypatch):
    """frozen_labels*.json in a temporary data dir, holding the given real entries."""
    def make(chain: str, *addresses: str) -> Path:
        name = "frozen_labels_tron.json" if chain == "tron" else "frozen_labels.json"
        entries = {a: _entry(a, chain) for a in addresses}
        path = tmp_path / name
        path.write_text(json.dumps({"_meta": {"last_reviewed": "2026-09-23", "counts": {"frozen": len(entries)},
                                              "excluded": {}}, "labels": entries}, indent=1) + "\n")
        return path
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(freezes.time, "sleep", lambda _seconds: None)
    return make


def test_a_lifted_freeze_moves_to_excluded_with_its_release_tx(held):
    path = held("tron", STILL_FROZEN_TRON, LIFTED_TRON)
    label = _entry(LIFTED_TRON, "tron")["label"]
    assert freezes.recheck_lifts(dry_run=False, chains=("tron",), http=endpoints()) == 0
    written = json.loads(path.read_text())
    assert set(written["labels"]) == {STILL_FROZEN_TRON}
    assert written["_meta"]["excluded"][LIFTED_TRON] == {"why": f"lifted on 2026-11-12, tx {RELEASE_TX}", "label": label}
    assert written["_meta"]["counts"] == {"frozen": 1, "excluded": 1}
    assert written["_meta"]["last_reviewed"] == "2026-09-23"  # a re-check is not a new read of Tether's events


def test_nothing_lifted_leaves_the_file_exactly_as_it_was(held):
    path = held("ethereum", ETH_FROZEN)
    before = path.read_bytes()
    assert freezes.recheck_lifts(dry_run=False, chains=("ethereum",), http=endpoints()) == 0
    assert path.read_bytes() == before


def test_a_dry_run_writes_nothing(held):
    path = held("tron", STILL_FROZEN_TRON, LIFTED_TRON)
    before = path.read_bytes()
    assert freezes.recheck_lifts(dry_run=True, chains=("tron",), http=endpoints()) == 0
    assert path.read_bytes() == before


def test_a_lift_the_second_endpoint_cannot_confirm_is_kept(held):
    path = held("tron", STILL_FROZEN_TRON, LIFTED_TRON)
    trongrid = RECORDED["trongrid_triggerconstantcontract"]["url"]
    assert freezes.recheck_lifts(dry_run=False, chains=("tron",), http=endpoints(fail=(trongrid,))) == 0
    assert set(json.loads(path.read_text())["labels"]) == {STILL_FROZEN_TRON, LIFTED_TRON}


def test_a_rate_limited_batch_is_asked_again():
    state = freezes.still_frozen(endpoints(once=(freezes.ETH_RPC,)), "ethereum", [ETH_FROZEN])
    assert state == {ETH_FROZEN: True}


def test_many_unreadable_answers_stop_the_run_and_write_nothing(held):
    addresses = sorted(json.loads((SHIPPED / "frozen_labels_tron.json").read_text())["labels"])[:8]
    path = held("tron", *addresses)
    before = path.read_bytes()
    down = endpoints(fail=(freezes.TRON_RPC, RECORDED["trongrid_triggerconstantcontract"]["url"]))
    assert freezes.recheck_lifts(dry_run=False, chains=("tron",), http=down) == 1
    assert path.read_bytes() == before


@pytest.mark.parametrize("body", [
    {"result": {"code": "CONTRACT_VALIDATE_ERROR"}},
    {"result": {"result": True}},
    {"result": {"result": True}, "constant_result": [""]},
    ["not", "a", "dict"],
])
def test_a_trongrid_answer_that_is_not_a_plain_result_is_not_a_lift(body):
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=body)))
    assert freezes._tron_answer(client, LIFTED_TRON) is None


def test_no_release_tx_found_still_says_why():
    why = freezes.lifted_why(None, "2026-11-15")
    assert why.startswith("lifted") and "2026-11-15" in why and "not found" in why


# -- the nightly refresh runs it when the key is missing ----------------------------
def test_the_tether_family_falls_back_to_the_lift_recheck():
    tether = next(f for f in lists.families() if f.module == "import_tether_freezes")
    assert tether.keyless_args == ("--recheck-lifts",)


def _frozen_list(path: Path, reviewed: str, *addresses: str) -> Path:
    path.write_text(json.dumps({"_meta": {"last_reviewed": reviewed},
                                "labels": {a: {"category": "frozen", "entity": "Tether (USDT freeze)"} for a in addresses}}))
    return path


def test_without_the_key_only_the_keyless_pass_runs_and_its_removal_opens_a_pr(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", None)
    path = _frozen_list(tmp_path / "frozen_labels_tron.json", "2026-09-23", *[addr(f"a{i}") for i in range(12)])
    family = Family("Tether USDT freezes", "import_tether_freezes", (path,), needs=("ETHERSCAN_API_KEY",),
                    keyless_args=("--recheck-lifts",))
    ran = []

    def run(f: Family) -> int:
        ran.append(f.args)
        _frozen_list(path, "2026-09-23", *[addr(f"a{i}") for i in range(11)])
        return 0

    outcome = run_family(family, run)
    assert ran == [("--recheck-lifts",)]
    assert outcome.status == "ok" and "ETHERSCAN_API_KEY" in outcome.keyless
    assert outcome.changes[path].removed == [addr("a11")]
    assert lists.reason_to_open([outcome], lists.date(2026, 11, 15)) == lists.CHANGED
    assert "re-checked only" in lists.render_summary([outcome], lists.CHANGED)
    assert lists.has_problem([outcome], strict=True)  # the full import still did not run


def test_a_keyless_pass_with_no_change_does_not_renew_an_old_date(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", None)
    path = _frozen_list(tmp_path / "frozen_labels_tron.json", "2026-09-23", addr("a"))
    family = Family("Tether USDT freezes", "import_tether_freezes", (path,), needs=("ETHERSCAN_API_KEY",),
                    keyless_args=("--recheck-lifts",))
    outcome = run_family(family, lambda _f: 0)
    assert lists.reason_to_open([outcome], lists.date(2026, 11, 15)) is None
