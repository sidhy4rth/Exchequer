"""The case bundle (case_bundle.py, suite feature 6, #186), behind EXCHEQUER_CASE_BUNDLE.

    GET /case-bundle              whether bundles are on here, and the files one holds (404 when off)
    GET /trace/{case_id}/bundle   the zip: the signed report, the registers, the audit trail, MANIFEST.txt

Only the browser or unit that traced the case may download its bundle, or anyone
for a public demo case, whose report anyone may download. Audited by the number
of files, never their contents.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import audit, case_bundle, case_privacy, config, models
from ..auth import CurrentUser
from .evidence import KEEP, _pdf

router = APIRouter()


def _on() -> None:
    if not config.CASE_BUNDLE:
        raise HTTPException(status_code=404, detail="Not Found")


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
    audit.record("case.bundle_download", case_id=case_id, detail={"files": files})
    return StreamingResponse(case_bundle.stream(spool), media_type="application/zip", headers={
        **KEEP, "Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}-bundle.zip"'})
