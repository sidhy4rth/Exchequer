"""Checking a report: the public signing key, and a verifier.

Both are public on purpose. The people who need to check an Exchequer report
-- an exchange's compliance desk, a court, the defence -- are not users of
the tool, and the check involves no case data: it reads only the report text
it is given and keeps nothing.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from .. import config
from ..evidence import KEYS_PUBLISHED_AT
from ..signing import ALGORITHM, get_signer, verify_report

router = APIRouter()

MAX_REPORT_BYTES = 2_000_000  # the largest real reports are ~200 KB


@router.get("/signing-key")
def signing_key() -> dict[str, Any]:
    """The public half of the key that signs this server's reports.

    Compare `fingerprint_sha256` with the one published at
    `keys_published_at`, which no server controls."""
    signer = get_signer()
    return {
        "algorithm": ALGORITHM,
        "fingerprint": signer.fingerprint,
        "fingerprint_sha256": signer.fingerprint_sha256,
        "public_key_pem": signer.public_pem,
        "persistent": signer.persistent,
        "source": signer.source,
        "issued_by": config.PUBLIC_URL or None,
        "keys_published_at": KEYS_PUBLISHED_AT,
    }


@router.post("/verify")
async def verify(request: Request) -> dict[str, Any]:
    """Check a text report, sent as the raw request body.

    The body is read here, but decoded and checked in a worker thread: this
    handler runs on the event loop that serves every visitor, and parsing a
    couple of megabytes there stalled them all."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_REPORT_BYTES:
            raise HTTPException(status_code=413, detail="That is larger than any Exchequer report.")
    return await run_in_threadpool(_check, bytes(body))


def _check(body: bytes) -> dict[str, Any]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Send the report as UTF-8 text.") from exc
    return verify_report(text)
