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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    def record_cached(self, provider: str, request: str, meta: dict[str, Any] | None) -> None:
        """A cache hit re-uses bytes retrieved earlier; carry their hash and time."""
        if not meta:
            return
        rec = EvidenceRecord(
            provider=provider, request=request,
            retrieved_at=meta["retrieved_at"], sha256=meta["sha256"],
            bytes=meta["bytes"], from_cache=True,
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

# The only lines seal_text writes below the hash line, besides the signature.
UNSIGNED_HOW = "To verify: hash the report up to, not including, this line."
SIGNED_HOW = ("To verify: paste this report at /verify on the server that issued it, or check "
              "the signature with the public key from /signing-key.")
TEMPORARY_KEY_NOTE = " (Signed with a temporary key: it verifies only until the server restarts.)"
HOW_LINES = (UNSIGNED_HOW, SIGNED_HOW, SIGNED_HOW + TEMPORARY_KEY_NOTE)


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


def read_seal(text: str) -> Seal | None:
    """Split a report at its first CONTENT HASH line; None if it has none.

    Below that line only the exact lines seal_text writes are accepted -- the
    SIGNATURE line, then one known "To verify" line -- in that order. Trailing
    spaces, line endings and blank lines at the end are forgiven, since copy
    and paste change them; any other line is extra."""
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
    if rest and rest[0] in HOW_LINES:
        rest = rest[1:]
    return Seal(text[:idx], hash_line, signature_line, tuple(rest), bom)


def seal_text(text: str, sign: bool = True) -> str:
    """Append a content hash, and this server's signature, to a text report.

    The hash covers every byte of `text` exactly as given. To verify: take the
    report up to (not including) the line that begins with `CONTENT HASH`,
    strip the single newline before it, and SHA-256 the result. The signature
    (signing.py) is Ed25519 over those same bytes: the hash shows the text is
    unchanged, the signature that this server issued it.
    """
    if sign and (text.startswith(SEAL_MARKS[0]) or f"\n{SEAL_MARKS[0]}" in text):
        # Signed, it would verify as changed: never issue that.
        raise ValueError("The report body contains a CONTENT HASH line of its own; refusing to sign it.")
    digest = sha256_hex(text)
    lines = [text, f"{CONTENT_HASH_MARK} (SHA-256 of every byte above this line): {digest}"]
    if sign:
        from .signing import ALGORITHM, SIGNATURE_MARK, get_signer

        signer = get_signer()
        lines.append(f"{SIGNATURE_MARK} ({ALGORITHM} over the same bytes, key {signer.fingerprint}): "
                     f"{signer.sign(text.encode('utf-8'))}")
        lines.append(SIGNED_HOW if signer.persistent else SIGNED_HOW + TEMPORARY_KEY_NOTE)
    else:
        lines.append(UNSIGNED_HOW)
    return "\n".join(lines) + "\n"


def verify_sealed_text(sealed: str) -> bool:
    """The hash-only check: the body matches its hash and nothing was added below."""
    seal = read_seal(sealed)
    if seal is None or seal.extra:
        return False
    claimed = seal.hash_line.rsplit(": ", 1)[-1].strip()
    return sha256_hex(seal.body) == claimed
