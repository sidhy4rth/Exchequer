"""Ed25519 signatures on exported reports.

The content hash at the foot of a text report (evidence.seal_text) proves a
report has not changed since it was hashed -- but anyone who edits a report
can hash it again. A signature cannot be redone without this server's private
key, so a signed report that verifies was produced here, unchanged.

The key:
* EXCHEQUER_SIGNING_KEY, the 32-byte private seed in base64, if set; else
* a PEM file beside the case store (on Railway, the /data volume), made on
  first start with owner-only permissions on Linux (Windows ignores the mode,
  so there the file takes its folder's permissions); else, if that cannot be
  written,
* a key for this process only. Reports it signs say so, because they stop
  verifying against the published key after a restart.

The public half is served at GET /signing-key, and POST /verify checks a
report against it. Since report format v2.2 the signed body itself names the
issuing server and the key's full SHA-256 fingerprint (evidence.issuer_block),
so a report from a clone of this repo that claims this server is told apart.
Offline, with OpenSSL:

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
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
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
        return self.fingerprint_sha256[:16]

    @property
    def fingerprint_sha256(self) -> str:
        """SHA-256 over the raw public key, all 64 hex digits: what reports sign and publish."""
        return hashlib.sha256(self.public_raw).hexdigest()

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


def _seed_bytes(seed: str) -> bytes | None:
    """A 32-byte seed from base64 (standard or URL-safe, padded or not) or hex."""
    if len(seed) == 64:
        try:
            return bytes.fromhex(seed)
        except ValueError:
            pass
    padded = seed + "=" * (-len(seed) % 4)
    for decode in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw = decode(padded, validate=True) if decode is base64.b64decode else decode(padded)
        except (binascii.Error, ValueError):
            continue
        if len(raw) == 32:
            return raw
    return None


def _load() -> Signer:
    seed = os.getenv("EXCHEQUER_SIGNING_KEY", "").strip()
    if seed:
        raw = _seed_bytes(seed)
        if raw is not None:
            return Signer(Ed25519PrivateKey.from_private_bytes(raw), "environment")
        logger.error("EXCHEQUER_SIGNING_KEY is not a 32-byte Ed25519 seed (base64 or hex); ignoring it")
    signer = _load_file()
    if signer.source == "file" and config.TEMPORARY_DISK:
        # A disk wiped on restart takes the key file with it: every wake signs
        # with a new key, and earlier reports stop verifying. Say so.
        logger.error("The report signing key is kept on a disk this host wipes on restart; "
                     "set EXCHEQUER_SIGNING_KEY so reports keep verifying")
        return Signer(signer.private, "ephemeral")
    return signer


def _load_file() -> Signer:
    path: Path = config.SIGNING_KEY_PATH
    try:
        if path.is_file():
            try:
                key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
                # Empty, truncated, password-protected or not a key. It may be
                # the real key and recoverable, so it is never overwritten;
                # this process signs with a marked temporary key meanwhile.
                logger.error("%s cannot be read as a private key (%s); fix or remove it. Signing with "
                             "a temporary key until then", path, type(exc).__name__)
                return Signer(Ed25519PrivateKey.generate(), "ephemeral")
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
# The SIGNATURE line as seal_text writes it (a 64-hex key since v2.2, 16 before);
# anything else is damaged. A strict pattern, so a fingerprint with a look-alike
# or invisible character cannot pass as a foreign key.
_SIG = re.compile(r"SIGNATURE \(Ed25519 over the same bytes, key (?P<fp>[0-9a-f]{64}|[0-9a-f]{16})\): "
                  r"(?P<sig>[A-Za-z0-9+/]{86}==)")
# Every report in this format or later is signed when issued (8fdbdbc), so one
# without a signature had it removed. The version sits in text a forger can
# edit: this only sharpens the message; an unsigned report never reads as fine.
SIGNED_FROM = (2, 1)
_FORMAT = re.compile(r"\(report format v(\d+)\.(\d+)\)")

DETAILS = {
    "not_a_report": "No CONTENT HASH line: this is not an Exchequer text report, or its last lines were cut off.",
    "changed": "The text does not match its seal: it was changed after it was issued.",
    "signature_missing": ("Signature missing. Every report in this format is signed when issued, so this one "
                          "was altered. Do not rely on it."),
    "unsigned": ("No signature, so nothing shows who made this report. Its content hash matches, but anyone "
                 "can compute a content hash."),
    "unknown_key": ("This report names a signing key this server does not know, so its signature cannot be "
                    "checked here. Do not rely on it."),
    "damaged": "The SIGNATURE line is damaged, so the signature cannot be checked. Do not rely on it.",
    "genuine": "Genuine and unchanged: signed by this server, and nothing was added below the signature.",
    "forged_issuer": ("Claims to be issued by this server but is not signed with any key it has used. Treat it "
                      "as forged."),
    "key_mismatch": ("The signed 'Signing key' line names a different key from the one that made the signature. "
                     "Do not rely on it."),
}


def _declares_signed_format(body: str) -> bool:
    from .evidence import read_issuer

    return any((int(a), int(b)) >= SIGNED_FROM for a, b in _FORMAT.findall(body)) or read_issuer(body) is not None


def verify_report(text: str) -> dict:
    """Check a sealed (and possibly signed) text report.

    `status` is the one verdict to act on: genuine, text_added, changed,
    signature_missing, unsigned, unknown_key, forged_issuer, damaged or
    not_a_report; the page shows it as given. `genuine` is True only for
    "genuine". The hash and the signature cover only the text above the
    CONTENT HASH line, so a line added below it is text nobody signed
    (`extra_content`). `issued_by` is read from the signed ISSUER block, and
    only once the signature has verified."""
    from .evidence import read_issuer, read_seal, sha256_hex

    seal = read_seal(text)
    if seal is None:
        return {"status": "not_a_report", "sealed": False, "hash_ok": False, "signed": False,
                "signature_ok": False, "signature_checked": False, "genuine": False,
                "extra_content": False, "detail": DETAILS["not_a_report"]}
    body = seal.body
    claimed = seal.hash_line.rsplit(": ", 1)[-1].strip()
    hash_ok = sha256_hex(body) == claimed
    extra = len(seal.extra)
    added = (f"{extra} line{'s were' if extra != 1 else ' was'} added below the seal, and nothing "
             f"covers {'them' if extra != 1 else 'it'}: treat everything below the CONTENT HASH line "
             "as not issued by Exchequer.")

    signer = get_signer()
    sig_line = seal.signature_line
    result = {
        "sealed": True,
        "hash_ok": hash_ok,
        "content_sha256": sha256_hex(body),
        "signed": sig_line is not None,
        "signature_ok": False,
        "signature_checked": False,
        "genuine": False,
        "extra_content": extra > 0,
        "extra_lines": extra,
        "bom_removed": seal.bom_removed,
        "key_fingerprint": None,
        "key_fingerprint_sha256": None,
        "claimed_key": None,
        "issued_by": None,
        "this_server_key": signer.fingerprint,
        "this_server_key_sha256": signer.fingerprint_sha256,
    }

    def done(status: str, detail: str | None = None) -> dict:
        result["status"] = status
        result["genuine"] = status == "genuine"
        result["detail"] = detail or DETAILS[status]
        if seal.bom_removed:
            result["detail"] += " (A byte-order mark added by an editor was ignored.)"
        return result

    if sig_line is None:
        if not hash_ok:
            return done("changed")
        status = "signature_missing" if _declares_signed_format(body) else "unsigned"
        return done(status, f"{DETAILS[status]} Also, {added}" if extra else None)

    match = _SIG.fullmatch(sig_line)
    if match is None:
        return done("damaged")
    fingerprint = match.group("fp")
    if fingerprint not in (signer.fingerprint, signer.fingerprint_sha256):
        result["claimed_key"] = fingerprint
        issuer = read_issuer(body)
        if config.PUBLIC_URL and issuer and issuer["issued_by"] == config.PUBLIC_URL:
            return done("forged_issuer")
        return done("unknown_key")
    full = signer.fingerprint_sha256
    result["key_fingerprint"], result["key_fingerprint_sha256"] = full[:16], full
    result["signature_checked"] = True
    try:
        signer.public.verify(base64.b64decode(match.group("sig"), validate=True), body.encode("utf-8"))
        result["signature_ok"] = True
    except (InvalidSignature, binascii.Error, ValueError):
        return done("changed")
    issuer = read_issuer(body)
    if issuer is not None and issuer["signing_key"] != full:
        return done("damaged", DETAILS["key_mismatch"])
    result["issued_by"] = issuer["issued_by"] if issuer else None
    if not hash_ok:
        return done("changed", "The signature matches but the CONTENT HASH line was edited.")
    if extra:
        return done("text_added", f"The signed part is genuine, but {added}")
    return done("genuine")
