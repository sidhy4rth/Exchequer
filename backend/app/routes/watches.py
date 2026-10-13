"""The watchlist: addresses this browser wants to hear about, and what moved.

    POST   /watches                    watch an address (optionally with a webhook)
    GET    /watches                    this browser's watches, with unread counts
    DELETE /watches/{id}               stop watching
    POST   /watches/{id}/check         check now, at most once a minute
    GET    /alerts                     this browser's alerts, newest first
    POST   /alerts/read                mark some or all read

Everything here belongs to the owner key the browser sends (ownership.py);
without one there is nothing to list and nothing can be watched.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import ownership, watchlist

router = APIRouter()


class WatchRequest(BaseModel):
    address: str = Field(..., max_length=80)
    chain: str | None = Field(None, max_length=16)
    asset: str | None = Field(None, max_length=16)
    note: str = Field("", max_length=200)
    case_id: str | None = Field(None, max_length=36)
    webhook_url: str | None = Field(None, max_length=500)


class ReadRequest(BaseModel):
    alert_ids: list[str] | None = Field(None, max_length=500)


def _owner(http: Request) -> str:
    owner = ownership.owner_hash_from_headers(http.headers)
    if owner is None:
        raise HTTPException(status_code=400, detail="This browser sent no owner key, so it has no watchlist.")
    return owner


@router.post("/watches", status_code=201)
def add_watch(body: WatchRequest, http: Request) -> dict[str, Any]:
    owner = _owner(http)
    try:
        watch = watchlist.create_watch(owner, body.address, body.chain, body.asset,
                                       body.note, body.case_id, body.webhook_url)
    except watchlist.WatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return watchlist.watch_summary(watch)


@router.get("/watches")
def get_watches(http: Request) -> dict[str, Any]:
    owner = ownership.owner_hash_from_headers(http.headers)
    watches = watchlist.list_watches(owner) if owner else []
    return {"count": len(watches), "watches": watches,
            "interval_seconds": watchlist.config.WATCH_INTERVAL_SECONDS,
            "running": watchlist.config.WATCHER_ENABLED}


@router.delete("/watches/{watch_id}")
def delete_watch(watch_id: str, http: Request) -> dict[str, Any]:
    if not watchlist.remove_watch(_owner(http), watch_id):
        raise HTTPException(status_code=404, detail="No such watch.")
    return {"removed": watch_id}


@router.post("/watches/{watch_id}/check")
def check_now(watch_id: str, http: Request) -> dict[str, Any]:
    owner = _owner(http)
    watch = watchlist.get_owned_watch(owner, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="No such watch.")
    since = watchlist.seconds_since_check(watch)
    if since is not None and since < watchlist.MIN_MANUAL_CHECK_SECONDS:
        wait = int(watchlist.MIN_MANUAL_CHECK_SECONDS - since) + 1
        raise HTTPException(status_code=429, detail=f"Checked {int(since)} s ago. Try again in {wait} s.",
                            headers={"Retry-After": str(wait)})
    new = watchlist.check_watch(watch_id)
    refreshed = watchlist.get_owned_watch(owner, watch_id)
    return {"new_alerts": new, "watch": watchlist.watch_summary(refreshed) if refreshed else None}


@router.get("/alerts")
def get_alerts(http: Request, unread: bool = Query(False), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    owner = ownership.owner_hash_from_headers(http.headers)
    alerts = watchlist.list_alerts(owner, unread_only=unread, limit=limit) if owner else []
    return {"count": len(alerts), "alerts": alerts}


@router.post("/alerts/read")
def read_alerts(body: ReadRequest, http: Request) -> dict[str, Any]:
    return {"marked": watchlist.mark_read(_owner(http), body.alert_ids)}
