"""Ed25519 signatures on exported reports.

The content hash at the foot of a text report (evidence.seal_text) proves a
report has not changed since it was hashed -- but anyone who edits a report
can hash it again. A signature cannot be redone without this server's private
key, so a signed report that verifies was produced here, unchanged.

The key:
* EXCHEQUER_SIGNING_KEY, the 32-byte private seed in base64, if set; else
* a PEM file beside the case store (on Railway, the /data volume), made on
  first start with owner-only permissions; else, if that cannot be written,
* a key for this process only. Reports it signs say so, because they stop
  verifying against the published key after a restart.

The public half is served at GET /signing-key, and POST /verify checks a
report against it. Offline, with OpenSSL:

    openssl pkeyutl -verify -pubin -inkey exchequer.pub.pem -rawin \\
        -in body.txt -sigfile sig.bin

where body.txt is the report up to (not including) the newline before the
CONTENT HASH line, and sig.bin is the base64-decoded SIGNATURE value.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from . import config

logger = logging.getLogger(__name__)

ALGORITHM = "Ed25519"
SIGNATURE_MARK = "SIGNATURE"


@dataclass(frozen=True)
class Signer:
    private: Ed25519PrivateKey
    source: str  # "environment", "file" or "ephemeral"

    @property
    def public(self) -> Ed25519PublicKey:
        return self.private.public_key()

    @property
    def public_raw(self) -> bytes:
        return self.public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    @property
    def fingerprint(self) -> str:
        """First 16 hex digits of SHA-256 over the raw public key."""
        return hashlib.sha256(self.public_raw).hexdigest()[:16]

    @property
    def public_pem(self) -> str:
        return self.public.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

    @property
    def persistent(self) -> bool:
        return self.source != "ephemeral"

    def sign(self, message: bytes) -> str:
        return base64.b64encode(self.private.sign(message)).decode()


_signer: Signer | None = None
_lock = threading.Lock()


def get_signer() -> Signer:
    global _signer
    with _lock:
        if _signer is None:
            _signer = _load()
            logger.info("Report signing key %s (%s)", _signer.fingerprint, _signer.source)
        return _signer


def reset_for_tests(signer: Signer | None = None) -> None:
    global _signer
    with _lock:
        _signer = signer


def _load() -> Signer:
    seed = os.getenv("EXCHEQUER_SIGNING_KEY", "").strip()
    if seed:
        try:
            raw = base64.b64decode(seed, validate=True)
            return Signer(Ed25519PrivateKey.from_private_bytes(raw), "environment")
        except (binascii.Error, ValueError):
            logger.error("EXCHEQUER_SIGNING_KEY is not a base64 32-byte Ed25519 seed; ignoring it")

    path: Path = config.SIGNING_KEY_PATH
    try:
        if path.is_file():
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            if isinstance(key, Ed25519PrivateKey):
                return Signer(key, "file")
            logger.error("%s is not an Ed25519 key; making a new one in memory", path)
            return Signer(Ed25519PrivateKey.generate(), "ephemeral")
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(pem)
        logger.info("Created report signing key at %s", path)
        return Signer(key, "file")
    except OSError as exc:
        logger.warning("Cannot keep a signing key at %s (%s); this process signs with a "
                       "temporary key", path, exc)
        return Signer(Ed25519PrivateKey.generate(), "ephemeral")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify_report(text: str) -> dict:
    """Check a sealed (and possibly signed) text report.

    Returns what a reader needs: whether the content hash matches, whether a
    signature is present, whether it verifies against this server's key."""
    from .evidence import CONTENT_HASH_MARK, sha256_hex

    text = text.replace("\r\n", "\n")
    marker = f"\n{CONTENT_HASH_MARK} ("
    idx = text.find(marker)
    if idx < 0:
        return {"sealed": False, "hash_ok": False, "signed": False, "signature_ok": False,
                "detail": "No CONTENT HASH line: this is not an Exchequer text report, "
                          "or its last lines were cut off."}
    body = text[:idx]
    tail = text[idx + 1:].split("\n")
    claimed = tail[0].rsplit(": ", 1)[-1].strip()
    hash_ok = sha256_hex(body) == claimed

    signer = get_signer()
    sig_line = next((line for line in tail[1:] if line.startswith(SIGNATURE_MARK + " (")), None)
    result = {
        "sealed": True,
        "hash_ok": hash_ok,
        "content_sha256": sha256_hex(body),
        "signed": sig_line is not None,
        "signature_ok": False,
        "key_fingerprint": None,
        "this_server_key": signer.fingerprint,
    }
    if sig_line is None:
        result["detail"] = (
            "Unsigned report (made before reports were signed). The hash only shows "
            "whether the text was changed after hashing, not who hashed it."
            if hash_ok else "The text does not match its content hash: it was changed."
        )
        return result

    fingerprint = sig_line.split("key ", 1)[-1].split(")", 1)[0].strip()
    result["key_fingerprint"] = fingerprint
    try:
        signature = base64.b64decode(sig_line.rsplit(": ", 1)[-1].strip(), validate=True)
    except (binascii.Error, ValueError):
        result["detail"] = "The SIGNATURE line is damaged."
        return result
    if fingerprint != signer.fingerprint:
        result["detail"] = ("Signed with a different key than this server's "
                            f"({fingerprint}, this server uses {signer.fingerprint}).")
        return result
    try:
        signer.public.verify(signature, body.encode("utf-8"))
        result["signature_ok"] = True
    except InvalidSignature:
        pass
    if result["signature_ok"] and hash_ok:
        result["detail"] = "Genuine and unchanged: signed by this server, every byte as issued."
    elif result["signature_ok"]:
        result["detail"] = "The signature matches but the CONTENT HASH line was edited."
    else:
        result["detail"] = "The signature does not match: the report was changed after signing."
    return result
