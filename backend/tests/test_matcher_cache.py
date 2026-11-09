"""Each chain's label files are held once, whatever spelling the caller used.

The getters were cached on the raw argument and only normalised it inside, so
/health/detail's `get_matcher()` (no argument) loaded a second copy of every
Ethereum label file beside `get_matcher("ethereum")`'s -- about 40 MB more on
a 512 MB host for the life of the process. Audit r1-labels-data-16.
"""
from __future__ import annotations

import pytest

from app import config, exchange_matcher, risk_matcher


@pytest.fixture(autouse=True)
def _fresh():
    risk_matcher.clear_label_caches()
    yield
    risk_matcher.clear_label_caches()


@pytest.mark.parametrize("getter, cached", [
    (exchange_matcher.get_matcher, exchange_matcher._matcher),
    (exchange_matcher.get_router_matcher, exchange_matcher._router_matcher),
    (risk_matcher.get_risk_matcher, risk_matcher._risk_matcher),
], ids=["exchange", "router", "risk"])
def test_every_spelling_of_a_chain_shares_one_copy(getter, cached):
    first = getter()
    assert getter("ethereum") is first
    assert getter("ETH") is first
    assert getter("mainnet") is first
    assert cached.cache_info().currsize == 1


def test_an_unknown_chain_raises_and_caches_nothing():
    with pytest.raises(config.UnknownChainError):
        risk_matcher.get_risk_matcher("dogecoin")
    with pytest.raises(config.UnknownChainError):
        exchange_matcher.get_matcher("dogecoin")
    assert risk_matcher._risk_matcher.cache_info().currsize == 0
    assert exchange_matcher._matcher.cache_info().currsize == 0
