"""The audit log (app/audit.py), read back.

    GET /audit/verify          recompute the whole chain: {ok, rows, first_bad_seq}
    GET /audit?case_id=...     one case's events, for the browser or unit that traced it

/audit/verify is for the operator: like /health/detail it answers 404 unless
EXCHEQUER_HEALTH_TOKEN is set, and 401 to anything but that bearer token
(R23's admin session will also do). A case's events go only to its owner,
or to any signed-in officer of the unit that traced it (ownership.reader),
who sees fellow officers of the unit by id. Anyone else who opened it shows
only as "another browser": who else holds the link is no one's business.
"""
from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from .. import audit, case_privacy, config, models, ownership
from ..auth import CurrentUser
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
def case_events(http: Request, user: CurrentUser, case_id: Annotated[OneLine, Query(max_length=36)]) -> dict[str, Any]:
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    viewer = ownership.reader(case, user)  # the whole unit reads the unit's cases
    if not case_privacy.is_owner(case.owner_hash, viewer):
        raise HTTPException(status_code=403, detail="Only the browser or unit that traced this case can read its audit log.")
    unit = user.unit_id if user.unit_id is not None and case.unit_id == user.unit_id else None
    events = audit.events_for(case_id, viewer, officer_id=user.officer_id, unit_id=unit)
    return {"case_id": case_id, "count": len(events), "events": events}
