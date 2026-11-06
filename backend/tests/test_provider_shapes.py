"""A provider answer of an unexpected shape is a provider error, never a crash.

The clients assumed dict bodies and well-formed fields outside their guards:
a JSON list, a JSON-RPC error that is a string, a nonce that is not hex, or
one garbled timeStamp escaped as AttributeError/ValueError. Those are not
provider errors, so the seed's read became a 500 ("failed unexpectedly")
instead of the 502 an upstream failure gets (r1-providers-10).
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi import HTTPException

from app import pipeline
from app.etherscan_client import EtherscanClient, EtherscanError, ProviderResponseError
from app.nodereal_client import NoderealClient, NoderealError
from app.pipeline import TraceRequest, run_trace
from app.provider_errors import public_reason
from app.tron_client import TronClient, TronError

EVM = "0x" + "1" * 40
OTHER = "0x" + "2" * 40
TRON = "TSFFxCbDLh6nP1x4BcyqkbEFJyx3zSGY2r"


def _http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _etherscan(body) -> EtherscanClient:
    return EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, include_internal=False,
                           client=_http(lambda r: httpx.Response(200, json=body)))


def _nodereal(answer) -> NoderealClient:
    def handler(request):
        method = json.loads(request.content)["method"]
        if method == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(40_000_000)})
        return httpx.Response(200, json=answer(method))
    return NoderealClient(api_key="k", min_interval=0, max_retries=0, client=_http(handler))


def _tron(body) -> TronClient:
    return TronClient(api_key="k", min_interval=0, max_retries=0,
                      client=_http(lambda r: httpx.Response(200, json=body)))


def test_an_etherscan_list_body_is_a_provider_error():
    with pytest.raises(ProviderResponseError):
        _etherscan([{"status": "1"}]).get_outgoing_transactions(EVM)


def test_one_garbled_etherscan_timestamp_skips_that_record_only():
    good = {"hash": "0x1", "from": EVM, "to": OTHER, "value": "10", "timeStamp": "1700000000",
            "blockNumber": "5", "isError": "0"}
    bad = {**good, "hash": "0x2", "timeStamp": "n/a"}
    client = _etherscan({"status": "1", "message": "OK", "result": [good, bad, "not a record"]})
    assert [t.hash for t in client.get_outgoing_transactions(EVM)] == ["0x1"]


def test_a_nodereal_error_that_is_a_string_is_a_provider_error():
    client = _nodereal(lambda m: {"jsonrpc": "2.0", "id": 1, "error": "internal failure"})
    with pytest.raises(NoderealError):
        client.get_outgoing_transactions(EVM)


def test_a_nodereal_result_of_the_wrong_shape_is_a_provider_error():
    client = _nodereal(lambda m: {"jsonrpc": "2.0", "id": 1, "result": ["not", "a", "dict"]})
    with pytest.raises(ProviderResponseError):
        client.get_outgoing_transactions(EVM)


def test_a_nodereal_nonce_that_is_not_hex_is_a_provider_error():
    client = _nodereal(lambda m: {"jsonrpc": "2.0", "id": 1, "result": 123})
    with pytest.raises(ProviderResponseError):
        client._nonce(EVM, 10)
    # The deep search treats an unreadable nonce as "not found", as it does any
    # provider error, rather than failing the trace.
    assert client._send_range(EVM, 40_000_000) is None


def test_a_nodereal_head_that_is_not_hex_is_a_provider_error():
    def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})
    client = NoderealClient(api_key="k", min_interval=0, max_retries=0, client=_http(handler))
    with pytest.raises(ProviderResponseError):
        client.head_block()


@pytest.mark.parametrize("body", [[{"data": []}], {"data": "nothing"}, {"data": [], "meta": "x"}])
def test_a_trongrid_body_of_the_wrong_shape_is_a_provider_error(body):
    with pytest.raises(TronError):
        _tron(body).get_outgoing_transactions(TRON)


def test_trongrid_records_of_the_wrong_shape_are_skipped():
    client = TronClient(api_key="k", min_interval=0, contract_address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                        client=_http(lambda r: httpx.Response(200, json={
                            "data": ["junk", {"token_info": "junk", "value": "5"}], "meta": {}})))
    assert client.get_outgoing_transactions(TRON) == []


def test_the_reason_a_case_records_is_fixed():
    assert public_reason(ProviderResponseError("<html>x</html>")) == (
        "the provider sent a response Exchequer could not read")


@pytest.mark.parametrize("make", [
    lambda: _etherscan([1, 2, 3]),
    lambda: _nodereal(lambda m: {"jsonrpc": "2.0", "id": 1, "error": "boom"}),
])
def test_a_misshapen_answer_at_the_seed_is_a_502(monkeypatch, make):
    @contextmanager
    def open_source(chain, asset):
        yield make()
    monkeypatch.setattr(pipeline, "open_source", open_source)
    with pytest.raises(HTTPException) as exc:
        run_trace(TraceRequest(address=EVM, chain="ethereum", follow_swaps=False))
    assert exc.value.status_code == 502
    assert "Could not reach the blockchain data provider" in exc.value.detail


def test_a_misshapen_tron_answer_at_the_seed_is_a_502(monkeypatch):
    @contextmanager
    def open_source(chain, asset):
        yield _tron([])
    monkeypatch.setattr(pipeline, "open_source", open_source)
    with pytest.raises(HTTPException) as exc:
        run_trace(TraceRequest(address=TRON, chain="tron", follow_swaps=False))
    assert exc.value.status_code == 502


def test_provider_errors_are_still_etherscan_errors():
    assert issubclass(ProviderResponseError, EtherscanError)
