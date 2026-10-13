"""Signed reports (app/signing.py, evidence.seal_text) and the verifier."""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import config, signing
from app.evidence import seal_text, verify_sealed_text
from app.main import app

client = TestClient(app)
REPORT = "EXCHEQUER CASE REPORT\nSent 9.5 ETH to Binance 14\n"


def test_a_sealed_report_is_signed_and_verifies():
    sealed = seal_text(REPORT)
    assert "SIGNATURE (Ed25519" in sealed
    assert verify_sealed_text(sealed)  # the old hash check still holds
    result = signing.verify_report(sealed)
    assert result["hash_ok"] and result["signed"] and result["signature_ok"]
    assert result["key_fingerprint"] == signing.get_signer().fingerprint


def test_editing_the_body_and_rehashing_does_not_fool_the_signature():
    sealed = seal_text(REPORT)
    forged_body = REPORT.replace("9.5", "95")
    # The forger recomputes the hash; they cannot recompute the signature.
    from app.evidence import sha256_hex
    head, tail = sealed.split("\nCONTENT HASH", 1)
    tail_lines = tail.split("\n")
    tail_lines[0] = tail_lines[0].rsplit(": ", 1)[0] + ": " + sha256_hex(forged_body)
    forged = forged_body + "\nCONTENT HASH" + "\n".join(tail_lines)
    result = signing.verify_report(forged)
    assert result["hash_ok"] is True
    assert result["signature_ok"] is False


def test_a_report_signed_by_another_key_is_named_as_such():
    other = signing.Signer(Ed25519PrivateKey.generate(), "file")
    mine = signing.get_signer()
    signing.reset_for_tests(other)
    sealed = seal_text(REPORT)
    signing.reset_for_tests(mine)
    result = signing.verify_report(sealed)
    assert result["signature_ok"] is False
    assert "different key" in result["detail"]


def test_old_unsigned_reports_still_check_their_hash():
    old = seal_text(REPORT, sign=False)
    result = signing.verify_report(old)
    assert result["hash_ok"] and not result["signed"]
    assert "Unsigned" in result["detail"]


def test_windows_line_endings_do_not_break_verification():
    assert signing.verify_report(seal_text(REPORT).replace("\n", "\r\n"))["signature_ok"]


def test_verify_and_signing_key_endpoints():
    key = client.get("/signing-key").json()
    assert key["algorithm"] == "Ed25519" and "BEGIN PUBLIC KEY" in key["public_key_pem"]
    ok = client.post("/verify", content=seal_text(REPORT).encode()).json()
    assert ok["signature_ok"] and ok["hash_ok"]
    bad = client.post("/verify", content=b"just some text").json()
    assert bad["sealed"] is False
    assert client.post("/verify", content=b"x" * 2_000_001).status_code == 413


def test_key_is_created_once_with_owner_only_permissions(tmp_path, monkeypatch):
    monkeypatch.delenv("EXCHEQUER_SIGNING_KEY", raising=False)
    monkeypatch.setattr(config, "SIGNING_KEY_PATH", tmp_path / "k.pem")
    first = signing._load()
    second = signing._load()
    assert first.source == second.source == "file"
    assert first.fingerprint == second.fingerprint
    assert oct(os.stat(tmp_path / "k.pem").st_mode & 0o777) == "0o600"


def test_key_from_the_environment(monkeypatch):
    seed = base64.b64encode(b"\x01" * 32).decode()
    monkeypatch.setenv("EXCHEQUER_SIGNING_KEY", seed)
    assert signing._load().source == "environment"


def test_unwritable_key_path_falls_back_to_a_marked_temporary_key(tmp_path, monkeypatch):
    monkeypatch.delenv("EXCHEQUER_SIGNING_KEY", raising=False)
    blocked = tmp_path / "ro"
    blocked.mkdir()
    blocked.chmod(0o500)
    monkeypatch.setattr(config, "SIGNING_KEY_PATH", blocked / "k.pem")
    try:
        signer = signing._load()
    finally:
        blocked.chmod(0o700)
    assert signer.source == "ephemeral" and not signer.persistent
    signing.reset_for_tests(signer)
    try:
        assert "temporary key" in seal_text(REPORT)
    finally:
        signing.reset_for_tests(signing.Signer(Ed25519PrivateKey.generate(), "file"))
