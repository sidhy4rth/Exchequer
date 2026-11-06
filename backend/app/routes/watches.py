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

import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import config, ownership, rate_limit, watchlist

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
    client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
    refused = rate_limit.charge(rate_limit.watches, rate_limit.watches_total, client)
    if refused is not None:
        wait, who = refused
        detail = (f"This site has created {config.WATCHES_PER_HOUR_TOTAL} watches in the last hour."
                  if who == "site" else
                  f"This connection has created {config.WATCHES_PER_HOUR_PER_CLIENT} watches in the last hour.")
        raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(int(wait))})
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
    # Whether and how often checks run is for anyone. When they last ran is
    # said only of this browser's own watches: the site-wide count and the
    # time of anyone's last check stay in the token-gated /health/detail.
    watcher: dict[str, Any] = {"enabled": config.WATCHER_ENABLED,
                               "interval_seconds": config.WATCH_INTERVAL_SECONDS}
    if owner:
        mine = watchlist.watcher_status(owner)
        watcher |= {"stale": mine["stale"], "last_check_at": mine["last_check_at"]}
    return {"count": len(watches), "watches": watches,
            "interval_seconds": config.WATCH_INTERVAL_SECONDS,
            "running": config.WATCHER_ENABLED,
            # What the watcher has actually done, for the panel to say (R30).
            "watcher": watcher}


@router.delete("/watches/{watch_id}")
def delete_watch(watch_id: str, http: Request) -> dict[str, Any]:
    if not watchlist.remove_watch(_owner(http), watch_id):
        raise HTTPException(status_code=404, detail="No such watch.")
    return {"removed": watch_id}


# A manual check reads the provider fresh, past the cache, so it is bounded
# per connection and for the site as a whole, per minute. Owner keys are free,
# so the per-watch cooldown alone bounded nothing.
CHECKS_PER_MINUTE_PER_CLIENT = 10
CHECKS_PER_MINUTE_TOTAL = 60
checks_per_client = rate_limit.SlidingWindowLimiter(CHECKS_PER_MINUTE_PER_CLIENT, 60)
checks_total = rate_limit.SlidingWindowLimiter(CHECKS_PER_MINUTE_TOTAL, 60)
_TOTAL = "all"
# Watches being checked right now: a second click while the first is still
# reading would otherwise reach the provider again (the cooldown is only
# written once a check finishes).
_checking: set[str] = set()
_checking_lock = threading.Lock()


def _too_many(detail: str, wait: float) -> HTTPException:
    return HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(int(wait) + 1)})


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
    with _checking_lock:
        if watch_id in _checking:
            raise _too_many("This watch is being checked right now.", 5)
        if checks_total.remaining(_TOTAL) == 0:
            raise _too_many("This site has made as many manual checks as it allows this minute. "
                            "Try again shortly.", 30)
        client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
        wait = checks_per_client.check(client)
        if wait is not None:
            raise _too_many(f"This connection has checked {CHECKS_PER_MINUTE_PER_CLIENT} watches "
                            "in the last minute. Try again shortly.", wait)
        checks_total.check(_TOTAL)
        _checking.add(watch_id)
    try:
        new = watchlist.check_watch(watch_id)
    finally:
        with _checking_lock:
            _checking.discard(watch_id)
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
