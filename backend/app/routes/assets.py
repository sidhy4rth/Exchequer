"""The asset register (assets.py): what was frozen or seized in a case.

    GET   /trace/{case_id}/assets   the case's rows this browser or unit may read
    POST  /trace/{case_id}/assets   record one
    PATCH /assets/{asset_id}        the court's order, key holders, notes, the outcome
    GET   /assets/due               held rows whose court deadline is within ?days= (default 7)

Each write is limited per connection, like the requests log, and audited by
which fields changed: never their text, which may name officers.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import assets, audit
from ..auth import CurrentUser
from .requests import _allow_write, _owner

router = APIRouter()


class NewAsset(BaseModel):
    holder: str = Field(..., max_length=16)
    asset: str = Field(..., max_length=16)
    amount: str | float = Field(..., union_mode="left_to_right")
    chain: str = Field("", max_length=16)
    held_at: str = Field("", max_length=120)
    tx_hash: str = Field("", max_length=80)
    key_holders: str = Field("", max_length=200)
    seized_on: str = Field(..., max_length=10)
    order_ref: str = Field("", max_length=200)
    notes: str = Field("", max_length=2000)
    request_id: str | None = Field(None, max_length=36)


class AssetChange(BaseModel):
    status: str | None = Field(None, max_length=24)
    order_ref: str | None = Field(None, max_length=200)
    outcome_ref: str | None = Field(None, max_length=200)
    outcome_tx: str | None = Field(None, max_length=80)
    key_holders: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=2000)


@router.get("/trace/{case_id}/assets")
def list_assets(case_id: str, user: CurrentUser) -> dict[str, Any]:
    rows = assets.list_for(user, case_id)
    audit.record("asset.list", case_id=case_id)
    return {"case_id": case_id, "count": len(rows), "assets": rows, "deadline_days": assets.DEADLINE_DAYS}


@router.post("/trace/{case_id}/assets", status_code=201)
def add_asset(case_id: str, body: NewAsset, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    try:
        made = assets.create(_owner(user), case_id, body.model_dump(), user)
    except assets.AssetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record("asset.add", case_id=case_id, detail={"asset_id": made["asset_id"], "holder": made["holder"]})
    return made


@router.patch("/assets/{asset_id}")
def change_asset(asset_id: str, body: AssetChange, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    try:
        updated = assets.update(asset_id, body.model_dump(exclude_none=True), user)
    except assets.AssetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="No asset with that id that you can change.")
    changed = updated.pop("changed")
    if changed:
        audit.record("asset.update", case_id=updated["case_id"], detail={"asset_id": asset_id, "changed": changed})
    return updated


@router.get("/assets/due")
def due_assets(user: CurrentUser, days: int = Query(7, ge=0, le=90)) -> dict[str, Any]:
    rows = assets.due_for(user, within_days=days)
    return {"count": len(rows), "assets": rows, "deadline_days": assets.DEADLINE_DAYS}
