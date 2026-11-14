"""Mixer pools on BSC, Polygon and Arbitrum stop a trace, as Ethereum's do.

The curated mixer entries used to be read on Ethereum and BSC only: a Tornado
Cash pool on Polygon or Arbitrum was not flagged at all, so a trace walked
through it as if the payout were the deposit. Polygon and Arbitrum now have a
threat file of their own. Reads the shipped data files; no network.
"""
from __future__ import annotations

import json

import networkx as nx
import pytest

from app import config
from app.risk_matcher import MIXER, get_risk_matcher

# Pools added from the 11 Nov 2026 mixer hunt (#148), one per chain and service.
POOLS = [
    ("bsc", "0x84443cfd09a48af6ef360c6976c5392ac5023a1f", "Tornado Cash: 0.1 BNB pool"),
    ("bsc", "0x66b5e322dc31f8c7a33ffd23975163795f8d16c7", 'Cyclone Protocol: 100 BNB anonymity pool "C3PO"'),
    ("polygon", "0xdf231d99ff8b6c6cbf4e9b9a945cbacef9339178", "Tornado Cash: 1,000 MATIC pool"),
    ("polygon", "0xe6ff16572470f1c441f8fd81db3cc2b4cdcd0a93", "Typhoon Network: 0.1 MATIC pool"),
    ("arbitrum", "0x84443cfd09a48af6ef360c6976c5392ac5023a1f", "Tornado Cash: 0.1 ETH pool"),
    ("ethereum", "0xd619c8da0a58b63be7fa69b4cc648916fe95fa1b", 'Cyclone Protocol: 100 ETH anonymity pool "Latte"'),
]
# An ordinary account: the first test vector in EIP-55, in no label file.
ORDINARY = "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed"


@pytest.mark.parametrize("chain,address,label", POOLS)
def test_a_mixer_pool_is_flagged_and_stops_the_trace(chain, address, label):
    matcher = get_risk_matcher(chain)
    meta = matcher.lookup(address)
    assert meta is not None and meta["category"] == MIXER and meta["label"] == label
    assert matcher.is_terminal(address)

    graph = nx.DiGraph()
    graph.add_node(address, depth=1)
    [match] = matcher.annotate(graph)
    assert match.is_terminal and graph.nodes[address]["is_terminal"]
    assert "The trace stops here" in match.describe()


@pytest.mark.parametrize("chain", ["ethereum", "bsc", "polygon", "arbitrum"])
def test_an_ordinary_address_is_not_flagged(chain):
    matcher = get_risk_matcher(chain)
    assert matcher.lookup(ORDINARY) is None
    assert not matcher.is_terminal(ORDINARY)
    graph = nx.DiGraph()
    graph.add_node(ORDINARY, depth=1)
    assert matcher.annotate(graph) == []


def test_a_pool_is_read_only_on_the_chain_it_is_filed_under():
    # The Cyclone "Latte" pool is an Ethereum contract; the same 0x address on Polygon is not it.
    assert get_risk_matcher("polygon").lookup("0xd619c8da0a58b63be7fa69b4cc648916fe95fa1b") is None


@pytest.mark.parametrize("chain", ["polygon", "arbitrum"])
def test_the_new_threat_files_hold_only_mixers_with_a_source(chain):
    document = json.loads(config.get_chain(chain).threat_labels_path.read_text())
    assert document["_meta"]["chain"] == chain
    labels = document["labels"]
    assert labels and document["_meta"]["counts"] == {"mixer": len(labels)}
    for address, entry in labels.items():
        assert address == address.lower()
        assert entry["category"] == MIXER and entry["source"] and entry["entity"]


def test_no_privacy_protocol_is_labelled_a_mixer():
    # Railgun, Aztec and Hinkal are privacy protocols no enforcement action names a mixer (#148).
    for chain in ("ethereum", "bsc", "polygon", "arbitrum"):
        labels = json.loads(config.get_chain(chain).threat_labels_path.read_text())["labels"]
        named = {e["entity"] for e in labels.values() if e["category"] == MIXER}
        assert not named & {"Railgun", "Aztec", "Hinkal"}, chain
