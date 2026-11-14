"""The case bundle (case_bundle.py, suite feature 6, #186), behind EXCHEQUER_CASE_BUNDLE.

    GET /case-bundle              whether bundles are on here, and the files one holds (404 when off)
    GET /trace/{case_id}/bundle   the zip: the signed report, the registers, the audit trail, MANIFEST.txt

Only the browser or unit that traced the case may download its bundle, or anyone
for a public demo case, whose report anyone may download. Audited by the number
of files, never their contents.
"""
from __future__ import annotations

from typing import IO, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from .. import audit, case_bundle, case_privacy, config, models
from ..auth import CurrentUser
from .evidence import KEEP, _pdf

router = APIRouter()


def _on() -> None:
    if not config.CASE_BUNDLE:
        raise HTTPException(status_code=404, detail="Not Found")


class _BundleResponse(StreamingResponse):
    """Streams the spooled zip and closes it however the response ends: sent in full, or the client gone
    before the first byte or part way (the generator's own finally runs only once it has started)."""

    def __init__(self, spool: IO[bytes], headers: dict[str, str]) -> None:
        super().__init__(case_bundle.stream(spool), media_type="application/zip", headers=headers)
        self._spool = spool

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._spool.close()


def bundle_response(spool: IO[bytes], headers: dict[str, str]) -> StreamingResponse:
    return _BundleResponse(spool, headers)


@router.get("/case-bundle")
def bundle_files(user: CurrentUser) -> dict[str, Any]:
    """Reads no case, so records nothing (like /access): what the button needs to show itself."""
    _on()
    return {"enabled": True, "files": case_bundle.names(), "max_bytes": case_bundle.MAX_BYTES}


@router.get("/trace/{case_id}/bundle")
def download_bundle(case_id: str, user: CurrentUser, http: Request) -> StreamingResponse:
    _on()
    stored = models.get_case(case_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    may, viewer = case_bundle.allowed(stored, user)
    if not may:
        raise HTTPException(status_code=403, detail="Only the browser or unit that traced this case can download its bundle.")
    asked = case_bundle.Request(
        case=case_privacy.case_for_reader(stored, viewer), stored=stored, user=user, viewer=viewer,
        owner=case_privacy.is_owner(stored.owner_hash, viewer), pdf=lambda case: _pdf(case, http))
    try:
        spool, files = case_bundle.build(asked)
    except case_bundle.TooLarge as exc:
        raise HTTPException(status_code=413, detail=(
            f"This case's bundle would be larger than {case_bundle.MAX_BYTES // (1024 * 1024)} MB. "
            "Download the report and each register on its own instead.")) from exc
    try:
        audit.record("case.bundle_download", case_id=case_id, detail={"files": files})
    except BaseException:
        spool.close()
        raise
    return bundle_response(spool, {
        **KEEP, "Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}-bundle.zip"'})
