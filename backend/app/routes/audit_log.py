"""The audit log (app/audit.py), read back.

    GET /audit/verify          recompute the whole chain: {ok, rows, first_bad_seq}
    GET /audit?case_id=...     one case's events, for the browser that traced it

/audit/verify is for the operator: like /health/detail it answers 404 unless
EXCHEQUER_HEALTH_TOKEN is set, and 401 to anything but that bearer token
(R23's admin session will also do). A case's events go only to its owner,
and even the owner sees any other browser that opened it only as "another
browser": who else holds the link is no one's business.
"""
from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from .. import audit, case_privacy, config, models, ownership
from ..input_rules import OneLine

router = APIRouter()


def _operator(request: Request) -> None:
    if not config.HEALTH_TOKEN:
        raise HTTPException(status_code=404, detail="Not Found")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), config.HEALTH_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Not authorised.")


@router.get("/audit/verify", include_in_schema=False)
def verify_log(request: Request) -> dict[str, Any]:
    _operator(request)
    return audit.verify()


@router.get("/audit")
def case_events(http: Request, case_id: Annotated[OneLine, Query(max_length=36)]) -> dict[str, Any]:
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    viewer = ownership.owner_hash_from_headers(http.headers)
    if not case_privacy.is_owner(case.owner_hash, viewer):
        raise HTTPException(status_code=403, detail="Only the browser that traced this case can read its audit log.")
    events = audit.events_for(case_id, viewer)
    return {"case_id": case_id, "count": len(events), "events": events}
