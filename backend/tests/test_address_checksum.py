"""A mixed-case EVM address must carry a correct EIP-55 checksum.

Any 0x + 40 hex was accepted and lowercased, so an address copied from a
screenshot with one character wrong was traced as some other wallet, whose
attribution could end up in a letter. EIP-55 mixed case exists to catch that
typo; all-lowercase and all-uppercase forms carry no checksum and still pass
(r1-trace-engine-13).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import config
from app.batches import BatchError, validate_rows
from app.etherscan_client import evm_checksum_ok, is_evm_address
from app.keccak import keccak256
from app.pipeline import TraceRequest, check_request

GOOD = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
FLIPPED = "0x5AAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"  # one letter's case changed


def test_keccak256_known_vectors():
    assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert keccak256(b"abc").hex() == "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"


@pytest.mark.parametrize("address", [
    GOOD,
    "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
    "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
    "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
    "0xdAC17F958D2ee523a2206206994597C13D831ec7",  # USDT, as Etherscan shows it
])
def test_eip55_spec_vectors_pass(address):
    assert evm_checksum_ok(address)
    assert config.CHAINS["ethereum"].validate_address(address)


def test_one_flipped_letter_fails():
    assert not evm_checksum_ok(FLIPPED)
    assert not config.CHAINS["ethereum"].validate_address(FLIPPED)
    assert not evm_checksum_ok("0xDaC17F958D2ee523a2206206994597C13D831ec7")


def test_all_lower_and_all_upper_pass():
    assert evm_checksum_ok(GOOD.lower())
    assert evm_checksum_ok("0x" + GOOD[2:].upper())
    assert config.CHAINS["polygon"].validate_address(GOOD.lower())


def test_trace_rejects_a_bad_checksum_with_a_typo_hint():
    with pytest.raises(HTTPException) as exc:
        check_request(TraceRequest(address=FLIPPED, chain="ethereum"))
    assert exc.value.status_code == 400
    assert "checksum" in exc.value.detail and "mistyped" in exc.value.detail


def test_batch_row_and_watch_reject_a_bad_checksum():
    from app.watchlist import WatchError, create_watch

    with pytest.raises(BatchError) as exc:
        validate_rows([{"address": FLIPPED, "chain": "ethereum"}])
    assert "checksum" in exc.value.row_errors[0]["error"]
    with pytest.raises(WatchError) as werr:
        create_watch("owner", FLIPPED, "ethereum", None)
    assert "checksum" in str(werr.value)


def test_provider_data_is_not_checksum_gated():
    # Provider records and test fixtures use mixed case freely; only what a
    # person submits is held to the checksum.
    assert is_evm_address("0xAAaa0000000000000000000000000000000000aa")
