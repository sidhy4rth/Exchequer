"""Provider error text never reaches a case, the screen or a signed report.

A failed read deeper in a trace, or in the pro-rata and FIFO estimates, was
recorded as f"... ({exc})", and the exception text can quote the provider's
response body -- an HTML error page, quota or key state. It was stored, shown
and signed. Now the case carries a fixed sentence per kind of failure; the
detail goes only to the (redacted) log.
"""
from __future__ import annotations

from contextlib import contextmanager

from app import pipeline
from app.api_budget import DeadlineReached
from app.etherscan_client import EtherscanError, EtherscanRateLimitError, ProviderQuotaError, Transaction
from app.pipeline import TraceRequest, run_trace
from app.prorata import estimate as estimate_prorata
from app.provider_errors import public_reason
from conftest import addr

SECRET = "<html>secret-token-state</html>"


def test_each_kind_of_failure_has_a_fixed_sentence():
    assert public_reason(DeadlineReached()) == "time limit"
    assert public_reason(ProviderQuotaError(SECRET)) == "the provider's quota is used up"
    assert public_reason(EtherscanRateLimitError(SECRET)) == "the provider kept refusing requests"
    assert public_reason(EtherscanError(SECRET)) == "the provider reported an error"
    assert public_reason(ValueError(SECRET)) == "an unexpected error"


def test_a_failed_read_deeper_in_the_trace_leaves_no_provider_text(monkeypatch):
    seed, mid = addr("5eed"), addr("a1")
    hop = Transaction(hash="0x" + "1" * 64, from_address=seed, to_address=mid, value_native=1.0, value_wei=10**18,
                      timestamp=1_700_000_000, block_number=1, is_error=False, asset="ETH")

    class Fake:
        def get_outgoing_transactions(self, address, limit=None):
            if address == mid:
                raise EtherscanError(f"Etherscan returned HTTP 418: {SECRET}")
            return [hop]

    @contextmanager
    def open_source(chain, asset):
        yield Fake()
    monkeypatch.setattr(pipeline, "open_source", open_source)
    monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
    r = run_trace(TraceRequest(address=seed, chain="ethereum", max_depth=3, follow_swaps=False))
    assert r["warnings"] and "secret" not in str(r).lower()
    assert any("the provider reported an error" in w for w in r["warnings"])


def test_a_failed_prorata_read_gives_a_reason_without_the_exception_text():
    import networkx as nx
    a, b, x = addr("a"), addr("b"), addr("c")
    g = nx.DiGraph()
    g.add_edge(a, b, value_native=1.0, transactions=[{"block_number": 1, "timestamp": 1, "value_native": 1.0}])
    g.add_edge(b, x, value_native=1.0, transactions=[{"block_number": 2, "timestamp": 2, "value_native": 1.0}])

    def broken(*args):
        raise EtherscanError(SECRET)
    out = estimate_prorata(g, [a, b, x], broken)
    assert "secret" not in str(out).lower()
