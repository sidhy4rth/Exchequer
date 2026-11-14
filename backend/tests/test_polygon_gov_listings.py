"""Government listings that name Polygon or Arbitrum itself (#148).

Government listings used to have per-chain files only on Ethereum, BSC and Tron, so
a U.S. forfeiture order for a wallet on Polygon had nowhere to go (#176 left one out).
Polygon and Arbitrum now have an intl_sanctions file of their own, which the importer
starts; Ethereum's listings still reach them through risk_labels_<chain>.json. Reads the
shipped data files; no network.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from app import config, never_flag, pipeline
from app.etherscan_client import Transaction
from app.pipeline import TraceRequest, run_trace
from app.risk_matcher import SEIZED, get_risk_matcher
from conftest import addr, make_graph

# N.D. Okla. 23-CR-333-SEH, order entered April 24, 2025: "Mnemonic Polygon (POL) WalletAddress
# 0x06884E8FB446352aFba58bce270c9365D5511d51" (USAO notice, Internet Archive copy of 20260328).
POLYGON_WALLET = "0x06884e8fb446352afba58bce270c9365d5511d51"
# An ordinary account: the first test vector in EIP-55, in no label file.
ORDINARY = "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed"
SEED, HOP = addr("5eed"), addr("a1")
T = 1_700_000_000


@pytest.mark.parametrize("chain", ["polygon", "arbitrum"])
def test_each_chain_has_its_own_government_listing_file(chain):
    path = config.get_chain(chain).intl_sanctions_path
    assert path is not None and path.name == f"intl_sanctions_{chain}.json"
    meta = json.loads(path.read_text())["_meta"]
    assert meta["chain"] == chain and meta["last_reviewed"]
    assert meta["counts"]["addresses"] == len(json.loads(path.read_text())["labels"])


def test_the_polygon_forfeiture_order_is_flagged_as_seized_with_its_notice():
    matcher = get_risk_matcher("polygon")
    meta = matcher.lookup(POLYGON_WALLET)
    assert meta is not None and meta["category"] == SEIZED
    assert meta["source"].startswith("U.S. court order of forfeiture, U.S. District Court for the ")
    assert "Northern District of Oklahoma, case 23-CR-333-SEH" in meta["source"]
    assert "web.archive.org/web/20260328205455/" in meta["source"]
    (match,) = matcher.annotate(make_graph([(SEED, POLYGON_WALLET, 5.0)], seed=SEED))
    assert match.category == SEIZED and match.describe("POL").startswith("Government seizure order:")
    assert not matcher.is_terminal(POLYGON_WALLET)  # a seizure order is a flag, not the end of a trace


def test_the_order_is_read_only_on_the_chain_the_notice_names():
    for chain in ("ethereum", "bsc", "arbitrum"):
        assert get_risk_matcher(chain).lookup(POLYGON_WALLET) is None, chain


@pytest.mark.parametrize("chain", ["polygon", "arbitrum"])
def test_an_ordinary_address_is_not_flagged(chain):
    matcher = get_risk_matcher(chain)
    assert matcher.lookup(ORDINARY) is None
    assert matcher.annotate(make_graph([(SEED, ORDINARY, 5.0)], seed=SEED)) == []


def test_the_wallet_is_on_no_never_flag_list():
    assert never_flag.kind("polygon", POLYGON_WALLET) is None
    assert never_flag.reason("polygon", POLYGON_WALLET) is None


def _tx(n, src, dst, value, when):
    return Transaction(hash="0x" + f"{n:064x}", from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 1e18), timestamp=when, block_number=when // 2,
                       is_error=False, asset="POL")


@pytest.fixture
def polygon_trace(monkeypatch):
    def run(history):
        class Fake:
            def get_outgoing_transactions(self, address, limit=None):
                return [t for t in history if t.from_address == address]

        @contextmanager
        def open_source(chain, asset):
            yield Fake()
        monkeypatch.setattr(pipeline, "open_source", open_source)
        monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
        return run_trace(TraceRequest(address=SEED, chain="polygon", asset="POL", max_depth=3, follow_swaps=False))
    return run


def test_a_polygon_trace_through_the_forfeited_wallet_flags_it(polygon_trace):
    result = polygon_trace([_tx(1, SEED, HOP, 100.0, T + 10), _tx(2, HOP, POLYGON_WALLET, 100.0, T + 20)])
    assert SEIZED in result["risk_flags"]
    assert [m["address"] for m in result["risk_matches"] if m["category"] == SEIZED] == [POLYGON_WALLET]


def test_a_polygon_trace_through_ordinary_wallets_flags_nothing(polygon_trace):
    result = polygon_trace([_tx(1, SEED, HOP, 100.0, T + 10), _tx(2, HOP, ORDINARY, 100.0, T + 20)])
    assert result["risk_flags"] == [] and result["risk_matches"] == []
