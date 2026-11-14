"""Scanning a phone or computer export in the browser (suite feature 2, slice 1).

    GET   /trace/{case_id}/export-scan   whether this server offers the scan (404 while
                                         config.EXPORT_SCAN is off, which hides the panel)
    POST  /trace/{case_id}/export-scan   record that a scan ran, by its counts

The officer's browser reads the export (a chats or notes file from a phone or
computer extraction) and looks for wallet addresses, transaction hashes and
seed-phrase-shaped runs of words. The file, and everything found in it, stays
in that browser: this server is told only how many lines and bytes were read
and how many of each kind turned up, so the audit trail shows that a scan ran
and who ran it. A count is not evidence; the export itself is, and it is
registered as an exhibit by its hashes (exhibits.py).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .. import audit, config, models
from ..auth import CurrentUser
from .requests import _allow_write

router = APIRouter()
# Far above any real export; only stops a nonsense number reaching the audit row.
_MOST = 10**12


class ScanCounts(BaseModel):
    # Counts only: anything else in the body is refused, so a value or a word cannot ride along.
    model_config = ConfigDict(extra="forbid")

    lines: int = Field(..., ge=0, le=_MOST)
    bytes: int = Field(..., ge=0, le=_MOST)
    addresses: int = Field(..., ge=0, le=_MOST)
    tx_hashes: int = Field(..., ge=0, le=_MOST)
    seed_runs: int = Field(..., ge=0, le=_MOST)


def _offered(case_id: str) -> None:
    if not config.EXPORT_SCAN:
        raise HTTPException(status_code=404, detail="Not Found")
    if models.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")


@router.get("/trace/{case_id}/export-scan")
def scan_offered(case_id: str, user: CurrentUser) -> dict[str, Any]:
    _offered(case_id)
    audit.record("export_scan.open", case_id=case_id)
    return {"case_id": case_id, "enabled": True}


@router.post("/trace/{case_id}/export-scan", status_code=201)
def scan_ran(case_id: str, body: ScanCounts, user: CurrentUser, http: Request) -> dict[str, Any]:
    _offered(case_id)
    _allow_write(http)
    audit.record("export_scan.run", case_id=case_id, detail=body.model_dump())
    return {"case_id": case_id, "recorded": True}
