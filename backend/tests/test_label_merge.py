"""Importers that share a label file replace only their own entries, and a failed
check keeps what was held.

The explorer-tag run of import_threat_labels rebuilt the threat files from its
own source and deleted the ~8,100 entries --scam-lists had merged in;
seed_bsc_labels did the same to the 146 accounts port_evm_labels added; both
exited 0, and each file's regenerate_with named exactly that command (audit
r1-scripts-1). A rate limit or an expired key was read as "not used" or "no
bytecode", so entries were dropped and the router file could be written empty
(audit r1-scripts-2). No network: every client and source is a stand-in.
"""
from __future__ import annotations

import io
import json
import sys

import pytest

from app import config
from app.nodereal_client import NoderealError
from scripts import import_threat_labels as threat
from scripts import seed_bsc_labels as seed_bsc
from scripts import seed_router_labels as routers
from scripts._label_files import ShrinkRefused, chain_regenerate, merge_owned

from conftest import addr

DAWS = "Etherscan address tag, via dawsbot/eth-labels @ 14247ba8cf"


def test_merge_owned_keeps_other_importers_entries_and_unknown_ones():
    held = {"a": {"o": 1}, "b": {"o": 1}, "c": {"o": 1}, "x": {"o": 0}}
    labels, counts = merge_owned(held, {"a": {"o": 1, "new": True}}, owned=lambda _a, e: e["o"] == 1, unknown={"b"})
    assert set(labels) == {"a", "b", "x"} and labels["a"]["new"]
    assert counts == {"replaced": 1, "removed": 1, "kept, check failed": 1, "kept from other importers": 1}


def test_an_importer_refuses_to_drop_most_of_its_own_entries():
    held = {str(i): {} for i in range(100)}
    fresh = {str(i): {} for i in range(50)}
    with pytest.raises(ShrinkRefused):
        merge_owned(held, fresh, owned=lambda *_: True)
    assert len(merge_owned(held, fresh, owned=lambda *_: True, allow_shrink=True)[0]) == 50


def test_regenerate_with_appends_never_truncates():
    assert chain_regenerate("a && then b", "a", "c") == "a && then b && then c"
    assert chain_regenerate(None, "a") == "a"


@pytest.mark.parametrize("name, commands", [
    ("threat_labels.json", ("scripts.import_threat_labels", "scripts.import_threat_labels --scam-lists")),
    ("threat_labels_bsc.json", ("scripts.import_threat_labels", "scripts.import_threat_labels --scam-lists")),
    ("exchange_labels_bsc.json", ("scripts.seed_bsc_labels", "scripts.import_eth_labels --chain bsc",
                                  "scripts.port_evm_labels")),
])
def test_shipped_regenerate_with_names_every_contributing_importer(name, commands):
    steps = [s.rsplit("-m ", 1)[-1] for s in
             json.loads((config.DATA_DIR / name).read_text())["_meta"]["regenerate_with"].split(" && then ")]
    assert steps == list(commands)


# -- import_threat_labels, explorer-tag run ----------------------------------------
@pytest.fixture
def threat_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "risk_labels.json").write_text(json.dumps({"labels": {}}))
    held = {addr(f"d{i}"): {"category": "stolen", "entity": f"E{i}", "label": f"E{i} Exploiter", "source": DAWS}
            for i in range(3)}
    held.update({addr(f"5c{i}"): {"category": "scam", "entity": "Phishing wallet", "label": f"Fake_Phishing{i}",
                                  "source": "ScamSniffer address blacklist @ 753310a5c8"} for i in range(2)})
    (tmp_path / "threat_labels.json").write_text(json.dumps({"_meta": {"scam_lists": "2 reported wallets"},
                                                             "labels": held}))
    monkeypatch.setattr(sys, "argv", ["import_threat_labels", "--chain", "ethereum"])
    return tmp_path, held


def _run_base(monkeypatch, found, kept, errors=()):
    monkeypatch.setattr(threat, "candidates_by_chain", lambda: {"ethereum": found, "bsc": {}})
    monkeypatch.setattr(threat, "verify_ethereum", lambda ordered: (kept, [], list(errors)))
    return threat.main()


def test_a_base_threat_import_keeps_scam_list_entries(threat_dir, monkeypatch):
    path, held = threat_dir
    found = {a: m for a, m in held.items() if m["source"] == DAWS}
    kept = {a: found[a] for a in list(found)[:2]}  # the third is no longer used on chain
    assert _run_base(monkeypatch, found, kept) == 0
    written = json.loads((path / "threat_labels.json").read_text())
    assert set(written["labels"]) == set(kept) | {addr("5c0"), addr("5c1")}
    assert written["_meta"]["scam_lists"] == "2 reported wallets"  # the other run's notes stay


def test_threat_verify_keeps_an_errored_address(threat_dir, monkeypatch):
    path, held = threat_dir
    found = {a: m for a, m in held.items() if m["source"] == DAWS}
    errored = addr("d2")
    kept = {a: m for a, m in found.items() if a != errored}
    assert _run_base(monkeypatch, found, kept, errors=[errored]) == 0
    assert errored in json.loads((path / "threat_labels.json").read_text())["labels"]


def test_a_new_candidate_that_could_not_be_checked_stops_the_threat_import(threat_dir, monkeypatch):
    path, held = threat_dir
    found = {a: m for a, m in held.items() if m["source"] == DAWS}
    new = addr("eee")
    found[new] = {"category": "stolen", "entity": "N", "label": "N Hacker", "source": DAWS}
    before = (path / "threat_labels.json").read_text()
    assert _run_base(monkeypatch, found, {}, errors=[new]) == 1
    assert (path / "threat_labels.json").read_text() == before


# -- seed_bsc_labels ---------------------------------------------------------------
class _Native:
    def __init__(self, **_):
        self._client = None

    def head_block(self):
        return 2_000_000

    def close(self):
        pass


def test_seed_bsc_keeps_ported_entries_and_an_errored_address(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "NODEREAL_API_KEY", "stub")
    seeded, quiet, errored, ported = addr("51"), addr("52"), addr("53"), addr("54")
    held = {a: {"exchange": "Binance", "label": f"Binance {i}", "type": "exchange_wallet"}
            for i, a in enumerate((seeded, quiet, errored, ported))}
    (tmp_path / "exchange_labels_bsc.json").write_text(json.dumps({"_meta": {"ported_from_ethereum": "1"},
                                                                    "labels": held}))
    source = {seeded: "Binance 0", quiet: "Binance 1", errored: "Binance 2"}
    monkeypatch.setattr(seed_bsc.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(source).encode()))
    monkeypatch.setattr(seed_bsc, "NoderealClient", _Native)

    def activity(native, token, usdt, head, floor, address):
        if address == errored:
            raise NoderealError("monthly quota exceeded")
        return (5, 1.0) if address == seeded else (0, 0.0)
    monkeypatch.setattr(seed_bsc, "bsc_activity", activity)
    monkeypatch.setattr(sys, "argv", ["seed_bsc_labels"])
    assert seed_bsc.main() == 0
    written = json.loads((tmp_path / "exchange_labels_bsc.json").read_text())
    assert set(written["labels"]) == {seeded, errored, ported}  # only the quiet seed entry goes
    assert written["_meta"]["ported_from_ethereum"] == "1"
    assert "port_evm_labels" in written["_meta"]["regenerate_with"]


# -- seed_router_labels ------------------------------------------------------------
@pytest.fixture
def router_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", "stub")
    monkeypatch.setattr(config, "NODEREAL_API_KEY", "")
    by_hand = addr("0c")
    (tmp_path / "router_labels.json").write_text(json.dumps({"_meta": {}, "labels": {
        by_hand: {"exchange": "OKX DEX", "label": "OKX: DEX Router 2", "type": "router"}}}))
    monkeypatch.setattr(routers, "fetch_category", lambda folder, category: {addr("01"): "Uniswap V2: Router 2"})

    class Client:
        def __init__(self, **_):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
    monkeypatch.setattr(routers, "EtherscanClient", Client)
    monkeypatch.setattr(sys, "argv", ["seed_router_labels"])
    return tmp_path, by_hand


def test_router_seed_writes_nothing_when_a_check_fails(router_dir, monkeypatch):
    path, _ = router_dir
    before = (path / "router_labels.json").read_text()
    monkeypatch.setattr(routers, "has_code_ethereum", lambda client, address: None)  # Invalid API Key
    assert routers.main() == 1
    assert (path / "router_labels.json").read_text() == before


def test_router_seed_keeps_routers_added_by_hand(router_dir, monkeypatch):
    path, by_hand = router_dir
    monkeypatch.setattr(routers, "has_code_ethereum", lambda client, address: True)
    assert routers.main() == 0
    assert set(json.loads((path / "router_labels.json").read_text())["labels"]) == {by_hand, addr("01")}
