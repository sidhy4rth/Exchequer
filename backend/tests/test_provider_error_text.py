"""What is shown when a provider read fails, and which NodeReal errors count as
a rate limit (review of #321, issue #330).

#321 made a client out of retries raise its provider's ProviderUnavailableError
subclass. The officer's watch list showed the class name, so the shown text
changed with it; it now shows public_reason's sentence. The warm-up's
operator-only status keeps a class name, the one shown before #321.

NodeReal sends a rate limit as a JSON-RPC error (test_provider_pacing's
{"code": -32005, "message": "too many requests"}). Only rate-limit messages are
retried and called a refusal; another error that mentions a "limit" is not.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import httpx
import pytest
from sqlalchemy import create_engine

from app import models, ownership, warmup, watchlist
from app.etherscan_client import EtherscanError, ProviderResponseError, ProviderUnavailableError
from app.nodereal_client import NoderealClient, NoderealError, NoderealResponseError, NoderealUnavailableError
from app.provider_errors import error_name, failure_kind
from app.tron_client import TronError, TronUnavailableError

KEY = "SECRETKEYQWERTYUIOPASDFGHJKLZXCVBN"
ALICE = "a" * 32
WALLET = "0x" + "7" * 40


# --- the class name the warm-up shows -------------------------------------------

def test_a_client_out_of_retries_is_named_as_before():
    assert error_name(ProviderUnavailableError("x")) == "EtherscanError"
    assert error_name(NoderealUnavailableError("x", rate_limited=True)) == "NoderealError"
    assert error_name(TronUnavailableError("x")) == "TronError"


@pytest.mark.parametrize("exc", [EtherscanError("x"), NoderealError("x"), TronError("x"),
                                 NoderealResponseError("x"), ProviderResponseError("x"), RuntimeError("x")])
def test_every_other_error_keeps_its_own_name(exc):
    assert error_name(exc) == type(exc).__name__


class _StopLoop(Exception):
    pass


def test_the_warm_up_status_names_a_provider_out_of_retries_as_before(monkeypatch):
    def broken():
        raise NoderealUnavailableError("NodeReal request failed after 5 attempts: rate limit", rate_limited=True)
    monkeypatch.setattr(warmup, "warm_once", broken)

    def stop(_seconds):
        raise _StopLoop
    monkeypatch.setattr(warmup, "_wait", stop, raising=False)
    monkeypatch.setattr(warmup, "_state", {**warmup._state, "runs_completed": 0, "last_error": None})
    with pytest.raises(_StopLoop):
        warmup._loop(1)
    assert warmup.status()["last_error"] == "NoderealError: NodeReal request failed after 5 attempts: rate limit"


# --- the sentence a watch shows ----------------------------------------------------

@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'w.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    monkeypatch.setattr(watchlist, "chain_head", lambda *a, **k: None)  # never a real provider


def _failing_source(exc):
    def source(chain, asset):
        @contextmanager
        def client():
            class C:
                def get_outgoing_transactions(self, address, limit=None):
                    raise exc
            yield C()
        return client()
    return source


@pytest.mark.parametrize("exc, reason", [
    (ProviderUnavailableError("Etherscan request failed after 5 attempts: HTTP 429", rate_limited=True),
     "the provider reported an error"),
    (EtherscanError("Etherscan returned HTTP 400"), "the provider reported an error"),
    (ProviderResponseError("bad shape"), "the provider sent a response Exchequer could not read"),
    (RuntimeError("provider down"), "an unexpected error"),
])
def test_a_watch_that_could_not_be_read_says_why_in_plain_words(store, exc, reason):
    w = watchlist.create_watch(ownership.owner_hash(ALICE), WALLET, "ethereum", "ETH")
    assert watchlist.check_watch(w.id, source=_failing_source(exc)) == []
    shown = watchlist.list_watches(ownership.owner_hash(ALICE))[0]["last_error"]
    assert shown == f"Could not read the address this round ({reason})."
    assert "Error" not in shown and "HTTP" not in shown  # no class name, no provider detail


def test_an_old_and_a_new_provider_failure_show_the_same_text(store):
    texts = []
    for wallet, exc in ((WALLET, EtherscanError("Etherscan request failed after 5 attempts: HTTP 503")),
                        ("0x" + "8" * 40, ProviderUnavailableError("Etherscan request failed after 5 attempts: HTTP 503"))):
        w = watchlist.create_watch(ownership.owner_hash(ALICE), wallet, "ethereum", "ETH")
        watchlist.check_watch(w.id, source=_failing_source(exc))
        texts.append(next(x["last_error"] for x in watchlist.list_watches(ownership.owner_hash(ALICE))
                          if x["watch_id"] == w.id))
    assert texts[0] == texts[1]


# --- which NodeReal errors are a rate limit --------------------------------------------

def _nodereal(error, monkeypatch, max_retries=2):
    monkeypatch.setattr("app.nodereal_client.time.sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["method"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": error})
    client = NoderealClient(api_key=KEY, min_interval=0.0, max_retries=max_retries,
                            client=httpx.Client(transport=httpx.MockTransport(handler)))
    return client, calls


@pytest.mark.parametrize("message", ["too many requests", "Too Many Requests", "max rate limit reached"])
def test_a_nodereal_rate_limit_is_retried_and_called_a_refusal(monkeypatch, message):
    client, calls = _nodereal({"code": -32005, "message": message}, monkeypatch)
    with pytest.raises(NoderealUnavailableError) as raised:
        client._rpc("eth_blockNumber", [])
    assert len(calls) == 3  # every attempt
    assert raised.value.rate_limited is True and failure_kind(raised.value) == "rate_limit"


@pytest.mark.parametrize("message", ["exceed maximum block range limit", "limit must be at most 1000",
                                     "too many results"])
def test_another_error_that_mentions_a_limit_is_not_a_rate_limit(monkeypatch, message):
    client, calls = _nodereal({"code": -32000, "message": message}, monkeypatch)
    with pytest.raises(NoderealError) as raised:
        client._rpc("eth_blockNumber", [])
    assert len(calls) == 1  # not read again: it would fail the same way
    assert not isinstance(raised.value, ProviderUnavailableError)
    assert failure_kind(raised.value) == "provider_error"


def test_a_spent_nodereal_quota_is_still_a_quota(monkeypatch):
    client, calls = _nodereal({"code": -32005, "message": "monthly CU limit exceeded"}, monkeypatch)
    with pytest.raises(NoderealError) as raised:
        client._rpc("eth_blockNumber", [])
    assert len(calls) == 1 and failure_kind(raised.value) == "quota"
