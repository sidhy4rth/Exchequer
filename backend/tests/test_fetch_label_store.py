"""The build-time fetch of the private label store.

It must never break a build that has no token (CI, a fork, a local docker
build), must refuse a file whose checksum does not match, and must leave no
half-written store behind.
"""
from __future__ import annotations

import gzip
import hashlib

import pytest

from scripts import fetch_label_store as fetch


def test_unconfigured_or_tokenless_builds_still_succeed(monkeypatch, tmp_path, capsys):
    for key in ("LABEL_STORE_REPO", "LABEL_STORE_TAG", "LABEL_STORE_SHA256"):
        monkeypatch.delenv(key, raising=False)
    assert fetch.main() == 0
    assert "not configured" in capsys.readouterr().out

    monkeypatch.setenv("LABEL_STORE_REPO", "owner/private")
    monkeypatch.setenv("LABEL_STORE_TAG", "t")
    monkeypatch.setenv("LABEL_STORE_SHA256", "0" * 64)
    monkeypatch.setenv("LABEL_STORE_TOKEN_FILE", str(tmp_path / "absent"))
    assert fetch.main() == 0
    assert "no token" in capsys.readouterr().out


def test_install_verifies_the_checksum_and_writes_atomically(tmp_path):
    payload = b"SQLite format 3\x00" + b"x" * 1000
    gz = tmp_path / "label_store.db.gz"
    gz.write_bytes(gzip.compress(payload))
    out = tmp_path / "data" / "label_store.db"

    with pytest.raises(ValueError, match="checksum mismatch"):
        fetch.install(gz, "0" * 64, out)
    assert not out.exists() and not out.with_suffix(".partial").exists()

    fetch.install(gz, hashlib.sha256(gz.read_bytes()).hexdigest(), out)
    assert out.read_bytes() == payload
