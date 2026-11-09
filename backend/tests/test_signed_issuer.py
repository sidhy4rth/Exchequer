"""A signed report says, inside what it signs, who issued it and with which key.

Before (r1-evidence-crypto-3), the signed body named no issuer and no key: the
only pointer to a verifier was an unsigned "paste this report at /verify on the
server that issued it", and the key was cut to 16 hex digits. Anyone running a
copy of the public repo could issue made-up reports that its own /verify called
genuine, and a recipient had nothing to tell the two apart. Now the issuer URL
and the full key fingerprint are signed, nothing follows the signature, a
report naming this server but signed by another key is called forged, and
reports signed with an earlier official key (backend/data/signing_keys.json)
still verify, with a note.
"""
from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import config, signing
from app.evidence import CONTENT_HASH_MARK, SIGNED_HOW, seal_text, sha256_hex
from app.main import app

client = TestClient(app)
URL = "https://exchequer.example"
BODY = "EXCHEQUER CASE REPORT\n(report format v2.2)\nSent 9.5 ETH to Binance 14"


@pytest.fixture(autouse=True)
def _public_url(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", URL)
    monkeypatch.setattr(signing, "_official", None)  # re-read the key list per test
    yield


def _signed_by(other: signing.Signer, body: str = BODY) -> str:
    mine = signing.get_signer()
    signing.reset_for_tests(other)
    try:
        return seal_text(body)
    finally:
        signing.reset_for_tests(mine)


def _old_style(body: str) -> str:
    """A report as v2.1 sealed it: 16-hex key on the signature, an unsigned how-line after."""
    signer = signing.get_signer()
    return "\n".join([body, f"{CONTENT_HASH_MARK} (SHA-256 of every byte above this line): {sha256_hex(body)}",
                      f"SIGNATURE (Ed25519 over the same bytes, key {signer.fingerprint}): "
                      f"{signer.sign(body.encode())}", SIGNED_HOW]) + "\n"


def _keyring(tmp_path, monkeypatch, *entries: dict) -> None:
    path = tmp_path / "signing_keys.json"
    path.write_text(json.dumps({"keys": list(entries)}))
    monkeypatch.setattr(signing, "OFFICIAL_KEYS_PATH", path)
    monkeypatch.setattr(signing, "_official", None)


def _entry(signer: signing.Signer, **over) -> dict:
    return {"fingerprint_sha256": signer.fingerprint_sha256,
            "public_key_b64": base64.b64encode(signer.public_raw).decode(),
            "in_use_from": "2026-11-06", "retired": None, "revoked": False, **over}


# -- what a sealed report carries ------------------------------------------------------
def test_the_issuer_and_the_full_key_are_inside_the_signed_body():
    sealed = seal_text(BODY)
    body = sealed.split(f"\n{CONTENT_HASH_MARK} (", 1)[0]
    signer = signing.get_signer()
    assert f"Issued by        : {URL}" in body
    assert f"Signing key      : Ed25519, SHA-256 fingerprint {signer.fingerprint_sha256}" in body
    assert f"{URL}/verify" in body
    assert len(signer.fingerprint_sha256) == 64


def test_nothing_follows_the_signature_and_it_names_the_full_key():
    lines = seal_text(BODY).rstrip("\n").split("\n")
    assert lines[-1].startswith("SIGNATURE (")
    assert f"key {signing.get_signer().fingerprint_sha256})" in lines[-1]


def test_a_new_report_verifies_and_says_who_issued_it():
    r = signing.verify_report(seal_text(BODY))
    assert r["status"] == "genuine"
    assert r["issued_by"] == URL
    assert r["key_fingerprint_sha256"] == signing.get_signer().fingerprint_sha256


def test_without_a_public_url_the_issuer_line_is_left_out(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    sealed = seal_text(BODY)
    assert "Issued by" not in sealed
    assert signing.verify_report(sealed)["status"] == "genuine"


def test_a_report_sealed_the_old_way_still_verifies():
    r = signing.verify_report(_old_style(BODY.replace("v2.2", "v2.1")))
    assert r["status"] == "genuine" and r["issued_by"] is None


def test_an_unsigned_how_line_after_a_signature_is_extra():
    from app.evidence import UNSIGNED_HOW

    old = _old_style(BODY).replace(SIGNED_HOW, UNSIGNED_HOW)
    assert signing.verify_report(old)["extra_content"] is True


# -- clones and forgeries --------------------------------------------------------------
def test_another_key_claiming_this_server_is_forged():
    clone = signing.Signer(Ed25519PrivateKey.generate(), "file")
    r = signing.verify_report(_signed_by(clone))
    assert r["status"] == "forged_issuer" and r["genuine"] is False
    assert "forged" in r["detail"].lower()


def test_another_key_naming_another_server_is_unknown(monkeypatch):
    clone = signing.Signer(Ed25519PrivateKey.generate(), "file")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://exchequer-clone.example")
    sealed = _signed_by(clone)
    monkeypatch.setattr(config, "PUBLIC_URL", URL)
    assert signing.verify_report(sealed)["status"] == "unknown_key"


def test_an_issued_by_line_higher_up_in_the_body_is_not_read_as_the_issuer(monkeypatch):
    clone = signing.Signer(Ed25519PrivateKey.generate(), "file")
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    sealed = _signed_by(clone, BODY + f"\nIssued by        : {URL}\nmore text")
    monkeypatch.setattr(config, "PUBLIC_URL", URL)
    assert signing.verify_report(sealed)["status"] == "unknown_key"


def test_a_signing_key_line_that_disagrees_with_the_signature_is_damaged():
    signer = signing.get_signer()
    body = (BODY + f"\nIssued by        : {URL}\nSigning key      : Ed25519, SHA-256 fingerprint {'0' * 64}\n"
            "To verify        : paste this whole file at the issuer's /verify")
    sealed = "\n".join([body, f"{CONTENT_HASH_MARK} (SHA-256 of every byte above this line): {sha256_hex(body)}",
                        f"SIGNATURE (Ed25519 over the same bytes, key {signer.fingerprint_sha256}): "
                        f"{signer.sign(body.encode())}"]) + "\n"
    assert signing.verify_report(sealed)["status"] == "damaged"


# -- the list of official keys -----------------------------------------------------------
def test_a_report_signed_with_a_retired_official_key_verifies_with_a_note(tmp_path, monkeypatch):
    old = signing.Signer(Ed25519PrivateKey.generate(), "file")
    _keyring(tmp_path, monkeypatch, _entry(old, in_use_from="2026-10-01", retired="2026-11-06"))
    r = signing.verify_report(_signed_by(old))
    assert r["status"] == "genuine_earlier_key" and r["genuine"] is False
    assert r["signature_ok"] is True and r["official"] is True
    assert "2026-11-06" in r["detail"]


def test_a_report_signed_with_a_revoked_key_is_never_reassuring(tmp_path, monkeypatch):
    leaked = signing.Signer(Ed25519PrivateKey.generate(), "file")
    _keyring(tmp_path, monkeypatch, _entry(leaked, retired="2026-11-06", revoked=True))
    r = signing.verify_report(_signed_by(leaked))
    assert r["status"] == "revoked_key" and r["official"] is False


def test_the_current_key_is_official_only_when_listed(tmp_path, monkeypatch):
    _keyring(tmp_path, monkeypatch)
    assert signing.verify_report(seal_text(BODY))["official"] is False
    _keyring(tmp_path, monkeypatch, _entry(signing.get_signer()))
    r = signing.verify_report(seal_text(BODY))
    assert r["status"] == "genuine" and r["official"] is True


def test_a_malformed_key_entry_is_skipped_never_trusted(tmp_path, monkeypatch):
    other = signing.Signer(Ed25519PrivateKey.generate(), "file")
    wrong = _entry(other, fingerprint_sha256="ab" * 32)  # fingerprint does not match the key
    _keyring(tmp_path, monkeypatch, wrong, {"fingerprint_sha256": "nonsense"})
    assert signing.official_keys() == []
    assert signing.verify_report(_signed_by(other))["status"] == "forged_issuer"


def test_the_committed_key_list_is_well_formed():
    raw = json.loads(signing.OFFICIAL_KEYS_PATH.read_text())
    assert isinstance(raw.get("keys"), list)
    assert len(signing.official_keys()) == len(raw["keys"])  # every entry loads


# -- the public endpoints ------------------------------------------------------------------
def test_the_signing_key_endpoint_gives_the_full_fingerprint_and_issuer():
    key = client.get("/signing-key").json()
    signer = signing.get_signer()
    assert key["fingerprint_sha256"] == signer.fingerprint_sha256
    assert key["fingerprint"] == signer.fingerprint
    assert key["issued_by"] == URL and key["official"] is False
    pem = serialization.load_pem_public_key(key["public_key_pem"].encode())
    assert pem.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw) == signer.public_raw


def test_letters_say_where_to_verify_and_name_the_full_key():
    from app.request_letters import draft
    from test_request_letters import case

    text = draft("case-1", case(), "exchange")
    assert f"{URL}/verify" in text
    assert signing.get_signer().fingerprint_sha256 in text


def test_the_live_sites_key_is_published():
    """r1-evidence-crypto-3: with "keys": [] every report the live site signed
    read official:false. Its key (GET /signing-key on exchequer-6gnl.onrender.com,
    9 Nov 2026: source environment, persistent) is now listed, in use."""
    raw = json.loads(signing.OFFICIAL_KEYS_PATH.read_text())
    live = [k for k in raw["keys"]
            if k["fingerprint_sha256"] == "f9427acc9ebc34ef44a28caffd80a699665a1ba029b93308332042ba895f0592"]
    assert len(live) == 1 and live[0]["retired"] is None and live[0]["revoked"] is False
    assert any(k.fingerprint_sha256 == live[0]["fingerprint_sha256"] for k in signing.official_keys())
