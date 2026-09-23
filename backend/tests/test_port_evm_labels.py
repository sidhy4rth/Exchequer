"""Tests for carrying Ethereum labels to Polygon and Arbitrum.

The failure that matters is a label on something that is not the same account:
a contract at the same address on another chain, or an address never used
there. Both must be refused.
"""
from __future__ import annotations

from app import config
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


def test_polygon_and_arbitrum_are_etherscan_chains_with_their_own_stablecoins():
    polygon, arbitrum = config.CHAINS["polygon"], config.CHAINS["arbitrum"]
    assert (polygon.chain_id, polygon.native_symbol, polygon.provider) == (137, "POL", "etherscan")
    assert (arbitrum.chain_id, arbitrum.native_symbol, arbitrum.provider) == (42161, "ETH", "etherscan")
    assert polygon.find_token("USDT").address != config.CHAINS["ethereum"].find_token("USDT").address
