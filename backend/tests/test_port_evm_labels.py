"""Tests for carrying Ethereum labels to Polygon and Arbitrum.

The failure that matters is a label on something that is not the same account:
a contract at the same address on another chain, or an address never used
there. Both must be refused.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import config
from app.etherscan_client import EtherscanError
from scripts import port_evm_labels as port


class FakeClient:
    def __init__(self, active, code):
        self.active, self.code = active, code

    def _request(self, params):
        if params["action"] == "eth_getCode":
            return self.code.get(params["address"], "0x")
        if params["action"] == "eth_getTransactionCount":
            return "0x5" if params["address"] in self.active else "0x0"
        raise AssertionError(params)


def test_only_an_account_that_has_sent_on_the_chain_is_carried_over():
    """Receiving is not enough -- spam reaches every famous address."""
    live, contract, idle = "0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40
    client = FakeClient(active={live, contract}, code={contract: "0x6080604052"})
    assert port.check(client, live) == "ok"
    assert port.check(client, contract) == "contract"
    assert port.check(client, idle) == "inactive"


def test_deposit_and_contract_wallets_are_never_candidates():
    candidates = port.ethereum_candidates()
    assert candidates and not any(m["type"] in port.SKIP_TYPES for m in candidates.values())


@pytest.fixture
def two_chains(tmp_path, monkeypatch):
    """Polygon and Arbitrum writing to temporary files, with one sanctioned candidate."""
    listed = "0x" + "4" * 40
    monkeypatch.setattr(port, "sanctioned_candidates", lambda: {
        listed: {"category": "sanctioned", "entity": "E", "label": "E", "source": "OFAC SDN list"}})
    chains = {}
    for key in port.TARGETS:
        chains[key] = SimpleNamespace(name=key, chain_id=1, risk_labels_path=tmp_path / f"risk_{key}.json",
                                      labels_path=tmp_path / f"labels_{key}.json")
    monkeypatch.setattr(config, "CHAINS", chains)
    return chains, listed


class ClientContext:
    def __init__(self, *_, **__):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_sanctions_only_writes_the_risk_files_and_leaves_the_exchange_files(two_chains, monkeypatch):
    chains, listed = two_chains
    monkeypatch.setattr(port, "EtherscanClient", ClientContext)
    monkeypatch.setattr(port, "check", lambda _client, _address: "ok")

    assert port.sanctions_only(dry_run=False) == 0
    for chain in chains.values():
        assert listed in json.loads(chain.risk_labels_path.read_text())["labels"]
        assert not chain.labels_path.exists()


def test_sanctions_only_stops_on_a_failed_check_rather_than_dropping_the_address(two_chains, monkeypatch):
    """A rate limit must not read as "not used on this chain" and un-list a designated party."""
    chains, _ = two_chains
    monkeypatch.setattr(port, "EtherscanClient", ClientContext)

    def rate_limited(_client, _address):
        raise EtherscanError("Max rate limit reached")

    monkeypatch.setattr(port, "check", rate_limited)
    assert port.sanctions_only(dry_run=False) == 1
    assert not any(chain.risk_labels_path.exists() for chain in chains.values())


def test_an_address_not_used_on_the_chain_is_still_left_out(two_chains, monkeypatch):
    chains, listed = two_chains
    monkeypatch.setattr(port, "EtherscanClient", ClientContext)
    monkeypatch.setattr(port, "check", lambda _client, _address: "inactive")

    assert port.sanctions_only(dry_run=False) == 0
    assert listed not in json.loads(chains["polygon"].risk_labels_path.read_text())["labels"]


def test_polygon_and_arbitrum_are_etherscan_chains_with_their_own_stablecoins():
    polygon, arbitrum = config.CHAINS["polygon"], config.CHAINS["arbitrum"]
    assert (polygon.chain_id, polygon.native_symbol, polygon.provider) == (137, "POL", "etherscan")
    assert (arbitrum.chain_id, arbitrum.native_symbol, arbitrum.provider) == (42161, "ETH", "etherscan")
    assert polygon.find_token("USDT").address != config.CHAINS["ethereum"].find_token("USDT").address


def test_relabel_re_reads_carried_listings_offline_and_drops_lapsed_ones(two_chains, monkeypatch):
    """An Israeli order now filed as seized is seized on Polygon too; a lapsed one goes (r1-labels-data-12/-3)."""
    chains, listed = two_chains
    lapsed, seized = "0x" + "5" * 40, "0x" + "6" * 40
    for chain in chains.values():
        chain.risk_labels_path.write_text(json.dumps({"_meta": {"last_reviewed": "2026-09-23"}, "labels": {
            a: {"category": "sanctioned", "entity": "E", "label": "E", "source": "old"} for a in (listed, lapsed, seized)}}))
    monkeypatch.setattr(port, "sanctioned_candidates", lambda: {
        listed: {"category": "sanctioned", "entity": "E", "label": "E", "source": "OFAC SDN list"},
        seized: {"category": "seized", "entity": "NBCTF order FO 1/24", "label": "NBCTF order FO 1/24",
                 "source": "Israel NBCTF seizure or forfeiture order FO 1/24 (via OpenSanctions)",
                 "authorities": ["Israel"], "valid_until": "2028-02-16"}})
    monkeypatch.setattr(port, "EtherscanClient", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no chain calls")))
    assert port.relabel(dry_run=False) == 0
    for chain in chains.values():
        written = json.loads(chain.risk_labels_path.read_text())
        assert set(written["labels"]) == {listed, seized}
        assert written["labels"][seized]["category"] == "seized"
        assert written["labels"][seized]["valid_until"] == "2028-02-16"
        assert written["_meta"]["last_reviewed"] == "2026-09-23"
