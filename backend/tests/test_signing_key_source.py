"""The signing key's lifetime is told truthfully (signing.py _load).

Without a usable EXCHEQUER_SIGNING_KEY the server keeps its key in a file
beside the case store. On a host whose disk is wiped on restart (Render's free
plan) that file -- and the key -- is new after every wake, yet the key was
called persistent: reports carried no warning and stopped verifying after the
next restart. Such a key is now called temporary, and the usual spellings of a
32-byte seed (URL-safe or unpadded base64, hex) are accepted instead of being
silently ignored.
"""
from __future__ import annotations

import base64

import pytest

from app import config, signing
from app.evidence import seal_text

SEED = bytes(range(32))


@pytest.fixture
def no_env_key(monkeypatch, tmp_path):
    monkeypatch.delenv("EXCHEQUER_SIGNING_KEY", raising=False)
    monkeypatch.setattr(config, "SIGNING_KEY_PATH", tmp_path / "k.pem")
    yield
    signing.reset_for_tests(None)


def test_a_file_key_on_a_temporary_disk_is_temporary(no_env_key, monkeypatch):
    monkeypatch.setattr(config, "TEMPORARY_DISK", True)
    signer = signing._load()
    assert signer.source == "ephemeral" and not signer.persistent
    signing.reset_for_tests(signer)
    assert "temporary key" in seal_text("REPORT\n")


def test_a_file_key_on_a_lasting_disk_is_still_persistent(no_env_key, monkeypatch):
    monkeypatch.setattr(config, "TEMPORARY_DISK", False)
    assert signing._load().source == "file"


@pytest.mark.parametrize("spelling", [
    base64.b64encode(SEED).decode(),
    base64.urlsafe_b64encode(SEED).decode(),
    base64.b64encode(SEED).decode().rstrip("="),
    SEED.hex(),
])
def test_common_spellings_of_the_seed_are_accepted(monkeypatch, tmp_path, spelling):
    monkeypatch.setattr(config, "SIGNING_KEY_PATH", tmp_path / "k.pem")  # never the real path
    monkeypatch.setenv("EXCHEQUER_SIGNING_KEY", spelling)
    reference = signing.Signer(signing.Ed25519PrivateKey.from_private_bytes(SEED), "environment")
    signer = signing._load()
    assert signer.source == "environment" and signer.fingerprint == reference.fingerprint


def test_a_bad_seed_on_a_temporary_disk_is_still_temporary(no_env_key, monkeypatch):
    monkeypatch.setenv("EXCHEQUER_SIGNING_KEY", "not a key")
    monkeypatch.setattr(config, "TEMPORARY_DISK", True)
    assert signing._load().source == "ephemeral"


def test_the_operator_view_says_whether_the_key_survives_a_restart(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.setattr(config, "HEALTH_TOKEN", "t" * 40)
    temporary = signing.Signer(signing.Ed25519PrivateKey.from_private_bytes(SEED), "ephemeral")
    signing.reset_for_tests(temporary)
    try:
        with TestClient(app) as client:
            detail = client.get("/health/detail", headers={"authorization": "Bearer " + "t" * 40}).json()
    finally:
        signing.reset_for_tests(None)
    assert detail["signing_key"] == {"fingerprint": temporary.fingerprint, "source": "ephemeral", "persistent": False}


@pytest.mark.parametrize("content", [b"", b"-----BEGIN PRIVATE KEY-----\nAAAA\n", b"not a pem at all"])
def test_an_unreadable_key_file_never_breaks_signing_and_is_left_alone(no_env_key, monkeypatch, content):
    # A corrupt, empty or truncated PEM raised outside the handler, so every
    # export and /verify answered 500 until someone fixed the file by hand.
    monkeypatch.setattr(config, "TEMPORARY_DISK", False)
    config.SIGNING_KEY_PATH.write_bytes(content)
    signer = signing._load()
    assert signer.source == "ephemeral"
    assert config.SIGNING_KEY_PATH.read_bytes() == content  # it may be the real key: never overwrite


def test_a_password_protected_key_file_is_reported_not_crashed(no_env_key, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    monkeypatch.setattr(config, "TEMPORARY_DISK", False)
    key = signing.Ed25519PrivateKey.generate()
    config.SIGNING_KEY_PATH.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b"pw")))
    assert signing._load().source == "ephemeral"
