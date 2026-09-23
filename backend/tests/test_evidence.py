"""Evidence integrity: every response a trace used is hashed on arrival.

The claim these pin down is narrow and has to hold exactly: the hash in the
manifest is the hash of the bytes the provider sent, a cache hit re-uses the
original hash and time rather than inventing a new retrieval, the manifest
hash does not depend on the order concurrent fetches finished in, and a
report's content hash verifies -- and stops verifying if one byte changes.
"""
from __future__ import annotations

import hashlib

import httpx

from app.etherscan_client import EtherscanClient
from app.evidence import (
    EvidenceLog, EvidenceRecord, build_manifest, manifest_sha256,
    seal_text, sha256_hex, verify_sealed_text,
)

ADDR = "0xAAaa0000000000000000000000000000000000aa"
TX = {"hash": "0xdead", "from": ADDR, "to": "0xBBbb0000000000000000000000000000000000bb",
      "value": "1000000000000000000", "timeStamp": "1700000000", "blockNumber": "18000000", "isError": "0"}
OK = {"status": "1", "message": "OK", "result": [TX]}


def make_client(payload: dict):
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(200, json=payload)
        bodies.append(response.content)
        return response

    client = EtherscanClient(
        api_key="secret-key", chain_id=1, min_interval=0.0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        include_internal=False,
    )
    return client, bodies


def test_response_is_hashed_as_received_and_the_key_is_not_in_the_request():
    client, bodies = make_client(OK)
    client.get_transactions(ADDR)

    [rec] = client.evidence.records
    assert rec.provider == "etherscan"
    assert rec.sha256 == hashlib.sha256(bodies[0]).hexdigest()
    assert rec.bytes == len(bodies[0])
    assert rec.from_cache is False
    assert "secret-key" not in rec.request
    assert "apikey" not in rec.request
    assert f"address={ADDR.lower()}" in rec.request or f"address={ADDR}" in rec.request
    assert rec.retrieved_at.endswith("Z")


def test_cache_hit_reuses_the_original_hash_and_time_and_is_marked_cached():
    client, bodies = make_client(OK)
    client.get_transactions(ADDR)
    client.get_transactions(ADDR)

    first, second = client.evidence.records
    assert len(bodies) == 1, "the second ask must not go to the network"
    assert second.from_cache is True
    assert second.sha256 == first.sha256
    assert second.retrieved_at == first.retrieved_at
    manifest = client.evidence.manifest()
    assert manifest["count"] == 2 and manifest["retrieved"] == 1 and manifest["from_cache"] == 1


def test_an_empty_answer_is_evidence_too():
    client, _ = make_client({"status": "0", "message": "No transactions found", "result": []})
    assert client.get_transactions(ADDR) == []
    assert len(client.evidence.records) == 1


def test_manifest_hash_is_independent_of_arrival_order():
    a = EvidenceRecord("etherscan", "GET q=1", "2026-09-15T10:00:00Z", sha256_hex(b"one"), 3)
    b = EvidenceRecord("etherscan", "GET q=2", "2026-09-15T10:00:01Z", sha256_hex(b"two"), 3)
    assert manifest_sha256([a, b]) == manifest_sha256([b, a])
    assert build_manifest([b, a])["records"][0]["request"] == "GET q=1"


def test_manifest_hash_changes_if_any_response_changes():
    a = EvidenceRecord("etherscan", "GET q=1", "2026-09-15T10:00:00Z", sha256_hex(b"one"), 3)
    a2 = EvidenceRecord("etherscan", "GET q=1", "2026-09-15T10:00:00Z", sha256_hex(b"one!"), 4)
    assert manifest_sha256([a]) != manifest_sha256([a2])


def test_sealed_report_verifies_and_a_changed_byte_does_not():
    sealed = seal_text("line one\nline two")
    assert verify_sealed_text(sealed)
    assert not verify_sealed_text(sealed.replace("line two", "line tw0"))
    assert not verify_sealed_text("no seal here")


def test_log_is_safe_to_append_from_threads():
    from concurrent.futures import ThreadPoolExecutor
    log = EvidenceLog()
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i: log.record("etherscan", f"GET q={i}", str(i).encode()), range(200)))
    assert len(log.records) == 200
    assert len({r.sha256 for r in log.records}) == 200
