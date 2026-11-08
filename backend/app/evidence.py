"""Evidence integrity: a record of every provider response a trace was built from.

A trace is only as trustworthy as the data it read, and that data came from a
third party over the network at a particular moment. If a finding is ever
challenged, the question will not be "is the arithmetic right" -- that can be
re-done from the report -- but "was the input what you say it was, and when did
you get it". This module answers that the only way it can be answered after the
fact: every response the clients used is hashed at the moment it arrives, with
the request that produced it (credential stripped) and a UTC timestamp, and the
set is stored with the case.

What this establishes, exactly: that the bytes hashed here are the bytes the
trace was computed from. A reviewer who fetches the same query today and gets
the same hash has shown the provider's answer has not changed; one who gets a
different hash has learned that the chain (or the provider) moved on, which for
append-only history means newer transactions exist. It does not establish that
the provider was truthful -- that is what the public explorer and the on-chain
data are for -- and it does not make a response tamper-proof; it makes
tampering detectable, because the manifest hash is printed in the report and
the report's own hash is printed under it.

A response served from the process cache is the same bytes retrieved earlier,
so it is recorded with its original hash and original retrieval time, marked
as cached. That is not a second retrieval and must not be presented as one.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class EvidenceRecord:
    provider: str      # etherscan | nodereal | trongrid
    request: str       # the query, canonical, credential removed
    retrieved_at: str  # UTC, ISO 8601
    sha256: str        # of the raw response body, as received
    bytes: int
    from_cache: bool = False
    # A cache hit only: SHA-256 of the canonical JSON of the cached value the
    # trace used (value_sha256). The cache holds the parsed value, not the
    # provider's bytes, so `sha256` alone cannot be checked against it.
    value_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        if out["value_sha256"] is None:
            del out["value_sha256"]  # a live record keeps the shape stored cases have
        return out


def value_sha256(value: Any) -> str | None:
    """SHA-256 of `value` as canonical JSON (sorted keys, no spaces), or None
    if it is not representable as JSON."""
    try:
        return sha256_hex(json.dumps(value, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError):
        return None


_NO_VALUE = object()


class EvidenceLog:
    """Per-trace, thread-safe. One client owns one log; a level of the walk is
    fetched concurrently, so `record` may be called from several threads."""

    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []
        self._lock = threading.Lock()

    def record(self, provider: str, request: str, body: bytes, *,
               retrieved_at: str | None = None, from_cache: bool = False) -> EvidenceRecord:
        rec = EvidenceRecord(
            provider=provider,
            request=request,
            retrieved_at=retrieved_at or utc_now_iso(),
            sha256=sha256_hex(body),
            bytes=len(body),
            from_cache=from_cache,
        )
        with self._lock:
            self._records.append(rec)
        return rec

    def record_cached(self, provider: str, request: str, meta: dict[str, Any] | None,
                      value: Any = _NO_VALUE) -> None:
        """A cache hit re-uses bytes retrieved earlier; carry their hash and time,
        and the hash of the cached `value` the trace is about to use."""
        if not meta:
            return
        rec = EvidenceRecord(
            provider=provider, request=request,
            retrieved_at=meta["retrieved_at"], sha256=meta["sha256"],
            bytes=meta["bytes"], from_cache=True,
            value_sha256=None if value is _NO_VALUE else value_sha256(value),
        )
        with self._lock:
            self._records.append(rec)

    @property
    def records(self) -> list[EvidenceRecord]:
        with self._lock:
            return list(self._records)

    def manifest(self) -> dict[str, Any]:
        return build_manifest(self.records)


def manifest_sha256(records: list[EvidenceRecord]) -> str:
    """One hash over every response hash. Sorted, so the same set of responses
    yields the same manifest whatever order the concurrent fetches finished in;
    a trace re-run against unchanged data reproduces it exactly."""
    lines = sorted(f"{r.sha256}  {r.provider}  {r.request}" for r in records)
    return sha256_hex("\n".join(lines))


def build_manifest(records: list[EvidenceRecord]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda r: (r.retrieved_at, r.provider, r.request))
    times = [r.retrieved_at for r in ordered]
    return {
        "algorithm": "sha256",
        "count": len(ordered),
        "retrieved": sum(1 for r in ordered if not r.from_cache),
        "from_cache": sum(1 for r in ordered if r.from_cache),
        "providers": sorted({r.provider for r in ordered}),
        "first_retrieved_at": times[0] if times else None,
        "last_retrieved_at": times[-1] if times else None,
        "manifest_sha256": manifest_sha256(ordered),
        "records": [r.to_dict() for r in ordered],
    }


CONTENT_HASH_MARK = "CONTENT HASH"
# Line starts that only the seal may write. read_seal cuts a report at the
# first line beginning "CONTENT HASH (", so a body line like that would make
# a genuine report read as changed.
SEAL_MARKS = (CONTENT_HASH_MARK + " (", "SIGNATURE (")
# The hash line exactly as seal_text writes it: the only wording ever issued,
# then 64 lower-case hex digits. Nothing covers this line, so anything else in
# it -- an "addendum" inside the brackets, words before or after the hash --
# is text nobody signed, and the report is damaged.
HASH_CAPTION = f"{CONTENT_HASH_MARK} (SHA-256 of every byte above this line): "
_HASH_LINE = re.compile(re.escape(HASH_CAPTION) + r"(?P<hex>[0-9a-f]{64})")


def hash_line_value(line: str) -> str | None:
    """The hash a CONTENT HASH line carries, or None if the line is not
    exactly as seal_text writes it."""
    match = _HASH_LINE.fullmatch(line)
    return match.group("hex") if match else None

# The only lines seal_text writes below the hash line, besides the signature.
# Append-only: every line ever issued must stay accepted, or the reports that
# carry it stop verifying. Since report format v2.2 a signed report has no
# line after its signature: the how-to is in the signed ISSUER block above.
UNSIGNED_HOW = "To verify: hash the report up to, not including, this line."
SIGNED_HOW = ("To verify: paste this report at /verify on the server that issued it, or check "
              "the signature with the public key from /signing-key.")
TEMPORARY_KEY_NOTE = " (Signed with a temporary key: it verifies only until the server restarts.)"
SIGNED_HOW_LINES = (SIGNED_HOW, SIGNED_HOW + TEMPORARY_KEY_NOTE)
HOW_LINES = (UNSIGNED_HOW, *SIGNED_HOW_LINES)

# The ISSUER block: the last lines of a signed body (v2.2 on), so the server
# that issued a report and the full fingerprint of its key are signed with it.
ISSUED_BY = "Issued by        : "
SIGNING_KEY = "Signing key      : "
TO_VERIFY = "To verify        : "
# Where the official key fingerprints are published, outside any server.
KEYS_PUBLISHED_AT = "https://github.com/sidhy4rth/Exchequer/blob/main/SECURITY.md#report-signing-key"
_OLD_SIGNATURE = re.compile(r"key [0-9a-f]{16}\): ")
_KEY_VALUE = re.compile(r"Ed25519, SHA-256 fingerprint (?P<fp>[0-9a-f]{64})(?: \(a temporary key: .*\))?")


def issuer_block(public_url: str, fingerprint_sha256: str, persistent: bool) -> list[str]:
    """The lines seal_text signs below a report: who issued it, with which key."""
    where = f"{public_url}/verify" if public_url else "/verify on the server that issued it"
    key = f"Ed25519, SHA-256 fingerprint {fingerprint_sha256}"
    if not persistent:
        key += " (a temporary key: it verifies only until this server restarts)"
    return ([ISSUED_BY + public_url] if public_url else []) + [
        SIGNING_KEY + key,
        TO_VERIFY + f"paste this whole file at {where} and compare the key",
        " " * len(TO_VERIFY) + f"above with the one Exchequer publishes at {KEYS_PUBLISHED_AT}",
    ]


def read_issuer(body: str) -> dict[str, str | None] | None:
    """{"issued_by", "signing_key"} from a signed body's ISSUER block, or None.

    Read only from the last lines, where seal_text writes it -- never searched
    for in the body, which holds third-party text. A Signing key line that is
    not exactly what seal_text writes gives signing_key "" (it then matches no key)."""
    tail = body.split("\n")[-4:]
    for i, line in enumerate(tail):
        if line.startswith(SIGNING_KEY):
            match = _KEY_VALUE.fullmatch(line[len(SIGNING_KEY):])
            above = tail[i - 1] if i > 0 else ""
            return {"issued_by": above[len(ISSUED_BY):] if above.startswith(ISSUED_BY) else None,
                    "signing_key": match.group("fp") if match else ""}
    return None


@dataclass(frozen=True)
class Seal:
    """A sealed text report split at its seal.

    `body` is what the hash and the signature cover. `extra` holds any line
    below the hash line that seal_text did not write: nothing covers those, so
    a report with extra lines must never be called unchanged."""
    body: str
    hash_line: str
    signature_line: str | None
    extra: tuple[str, ...]
    bom_removed: bool = False

    @property
    def claimed_hash(self) -> str | None:
        """The hash the hash line states; None when the line is not exactly as issued."""
        return hash_line_value(self.hash_line)


def read_seal(text: str) -> Seal | None:
    """Split a report at its first CONTENT HASH line; None if it has none.

    Below that line only the exact lines seal_text writes are accepted -- the
    SIGNATURE line, then (in reports before v2.2) the "To verify" line that
    goes with it: the signed one after a signature, the unsigned one without.
    Trailing spaces, line endings and blank lines at the end are forgiven,
    since copy and paste change them; any other line is extra."""
    from .signing import SIGNATURE_MARK

    text = text.replace("\r\n", "\n")
    # One byte-order mark, as a Windows editor adds it, is not part of the
    # report (reports start with a rule line). Exactly one: more is a change.
    bom = text.startswith("\ufeff")
    if bom:
        text = text[1:]
    idx = text.find(f"\n{CONTENT_HASH_MARK} (")
    if idx < 0:
        return None
    lines = [line.rstrip() for line in text[idx + 1:].split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    hash_line, rest = lines[0], lines[1:]
    signature_line = None
    if rest and rest[0].startswith(SIGNATURE_MARK + " ("):
        signature_line, rest = rest[0], rest[1:]
    # The how-line goes with how the report was sealed: the unsigned one with
    # no signature, the signed one only after a 16-hex key (before v2.2).
    if signature_line is None:
        accepted: tuple[str, ...] = (UNSIGNED_HOW,)
    else:
        accepted = SIGNED_HOW_LINES if _OLD_SIGNATURE.search(signature_line) else ()
    if rest and rest[0] in accepted:
        rest = rest[1:]
    return Seal(text[:idx], hash_line, signature_line, tuple(rest), bom)


def seal_text(text: str, sign: bool = True) -> str:
    """Append a content hash, and this server's signature, to a text report.

    Signed, the ISSUER block (issuer_block) is added to `text` first, so the
    issuing server and its full key fingerprint are covered too, and nothing
    follows the signature. The hash covers every byte above it. To verify:
    take the report up to (not including) the line that begins with `CONTENT
    HASH`, strip the single newline before it, and SHA-256 the result. The
    signature (signing.py) is Ed25519 over those same bytes: the hash shows the
    text is unchanged, the signature that this server issued it.
    """
    if sign and (text.startswith(SEAL_MARKS[0]) or f"\n{SEAL_MARKS[0]}" in text):
        # Signed, it would verify as changed: never issue that.
        raise ValueError("The report body contains a CONTENT HASH line of its own; refusing to sign it.")
    if sign and "\r\n" in text:
        # read_seal turns CRLF into LF before hashing, so this could never verify.
        raise ValueError("The report body contains a CRLF line ending; refusing to sign it.")
    if not sign:
        return "\n".join([text, f"{HASH_CAPTION}{sha256_hex(text)}", UNSIGNED_HOW]) + "\n"
    from . import config
    from .signing import ALGORITHM, SIGNATURE_MARK, get_signer

    signer = get_signer()
    text = "\n".join([text, *issuer_block(config.PUBLIC_URL, signer.fingerprint_sha256, signer.persistent)])
    lines = [text, f"{HASH_CAPTION}{sha256_hex(text)}",
             f"{SIGNATURE_MARK} ({ALGORITHM} over the same bytes, key {signer.fingerprint_sha256}): "
             f"{signer.sign(text.encode('utf-8'))}"]
    return "\n".join(lines) + "\n"


def verify_sealed_text(sealed: str) -> bool:
    """The hash-only check: the hash line is exactly as issued, the body
    matches it, and nothing was added below."""
    seal = read_seal(sealed)
    if seal is None or seal.extra or seal.claimed_hash is None:
        return False
    return sha256_hex(seal.body) == seal.claimed_hash
