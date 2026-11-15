"""Changing the public address does not break reports signed before the change.

config.PUBLIC_URL is EXCHEQUER_PUBLIC_URL, or else RENDER_EXTERNAL_URL. On
Render only the second is set, so reports and /signing-key name the
onrender.com address. When the owner sets EXCHEQUER_PUBLIC_URL to the domain,
the address changes but the signing key does not. Reports already sent out
must still verify as genuine (same official key) and keep naming the address
they were signed under, which /verify reads from the report itself. Reports
signed after the change, and /signing-key, name the new address.

Only config.PUBLIC_URL is monkeypatched; nothing here touches the network.
"""
from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app import config, signing
from app.evidence import seal_text
from app.main import app

client = TestClient(app)
OLD_URL = "https://exchequer-old.example"
NEW_URL = "https://exchequer-new.example"
BODY = "EXCHEQUER CASE REPORT\n(report format v2.2)\nSent 9.5 ETH to Binance 14"


@pytest.fixture(autouse=True)
def _official_current_key(tmp_path, monkeypatch):
    """List this server's current key as official, as signing_keys.json does for the live key."""
    signer = signing.get_signer()
    path = tmp_path / "signing_keys.json"
    path.write_text(json.dumps({"keys": [{
        "fingerprint_sha256": signer.fingerprint_sha256,
        "public_key_b64": base64.b64encode(signer.public_raw).decode(),
        "in_use_from": "2026-11-06", "retired": None, "revoked": False}]}))
    monkeypatch.setattr(signing, "OFFICIAL_KEYS_PATH", path)
    monkeypatch.setattr(signing, "_official", None)
    monkeypatch.setattr(config, "PUBLIC_URL", OLD_URL)
    yield


def _verify(sealed: str) -> dict:
    r = client.post("/verify", content=sealed.encode("utf-8"))
    assert r.status_code == 200
    return r.json()


def test_a_report_signed_before_the_address_changed_still_verifies(monkeypatch):
    before = seal_text(BODY)
    assert f"Issued by        : {OLD_URL}" in before

    monkeypatch.setattr(config, "PUBLIC_URL", NEW_URL)
    r = _verify(before)
    assert r["status"] == "genuine" and r["genuine"] is True
    assert r["official"] is True and r["signature_ok"] is True
    assert r["issued_by"] == OLD_URL  # read from the signed report, not from config
    assert r["key_fingerprint_sha256"] == signing.get_signer().fingerprint_sha256


def test_a_report_signed_after_the_change_names_the_new_address(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", NEW_URL)
    after = seal_text(BODY)
    assert f"Issued by        : {NEW_URL}" in after
    assert OLD_URL not in after
    r = _verify(after)
    assert r["status"] == "genuine" and r["official"] is True
    assert r["issued_by"] == NEW_URL


def test_the_signing_key_endpoint_follows_the_address_but_keeps_the_key(monkeypatch):
    before = client.get("/signing-key").json()
    assert before["issued_by"] == OLD_URL and before["official"] is True

    monkeypatch.setattr(config, "PUBLIC_URL", NEW_URL)
    after = client.get("/signing-key").json()
    assert after["issued_by"] == NEW_URL and after["official"] is True
    assert after["fingerprint_sha256"] == before["fingerprint_sha256"]
    assert after["public_key_pem"] == before["public_key_pem"]
