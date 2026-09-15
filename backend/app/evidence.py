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


def seal_text(text: str) -> str:
    """Append a content hash to a text report.

    The hash covers every byte of `text` exactly as given. To verify: take the
    report up to (not including) the line that begins with `CONTENT HASH`,
    strip the single newline before it, and SHA-256 the result.
    """
    digest = sha256_hex(text)
    return (
        f"{text}\n"
        f"{CONTENT_HASH_MARK} (SHA-256 of every byte above this line): {digest}\n"
        "To verify: hash the report up to, not including, this line.\n"
    )


def verify_sealed_text(sealed: str) -> bool:
    marker = f"\n{CONTENT_HASH_MARK} ("
    idx = sealed.find(marker)
    if idx < 0:
        return False
    body = sealed[:idx]
    line = sealed[idx + 1:].split("\n", 1)[0]
    claimed = line.rsplit(": ", 1)[-1].strip()
    return sha256_hex(body) == claimed
