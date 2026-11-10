"""The watchlist: addresses this browser wants to hear about, and what moved.

    POST   /watches                    watch an address (optionally with a webhook)
    GET    /watches                    this browser's watches, with unread counts
    DELETE /watches/{id}               stop watching
    POST   /watches/{id}/check         check now, at most once a minute
    DELETE /watches/{id}/webhook       stop posting this watch's alerts to a webhook
    GET    /alerts                     this browser's alerts: unread exchange and flagged first, then newest
    POST   /alerts/read                mark some or all read

Everything here belongs to the owner key the browser sends (ownership.py);
without one there is nothing to list and nothing can be watched.
"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import api_budget, audit, case_refs, config, models, ownership, rate_limit, watchlist
from ..auth import CurrentUser
from ..input_rules import OneLine

router = APIRouter()


class WatchRequest(BaseModel):
    address: OneLine = Field(..., max_length=80)
    chain: OneLine | None = Field(None, max_length=16)
    asset: OneLine | None = Field(None, max_length=16)
    note: OneLine = Field("", max_length=200)
    case_id: OneLine | None = Field(None, max_length=36)
    # 300 characters sealed (webhook_vault) still fit the 500-character column.
    webhook_url: OneLine | None = Field(None, max_length=300)
    # Required of a signed-in officer, unless case_id is a case they may read
    # that was traced under one (case_refs.py).
    case_ref: case_refs.CaseRef = None


class ReadRequest(BaseModel):
    alert_ids: list[OneLine] | None = Field(None, max_length=500)


def _owner(http: Request) -> str:
    owner = ownership.owner_hash_from_headers(http.headers)
    if owner is None:
        raise HTTPException(status_code=400, detail="This browser sent no owner key, so it has no watchlist.")
    return owner


def _case_ref(body: WatchRequest, user: Any) -> str | None:
    """The watch's case reference: the one sent, else its case's own when this
    officer reads that case in full."""
    case = models.get_case(body.case_id) if body.case_id and not body.case_ref and not user.demo else None
    return case_refs.required(user, body.case_ref or case_refs.known(case, user), "watch")


@router.post("/watches", status_code=201)
def add_watch(body: WatchRequest, http: Request, user: CurrentUser) -> dict[str, Any]:
    ref = _case_ref(body, user)
    owner = _owner(http)
    client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
    officer = case_refs.spender(user, "watch")
    refused = rate_limit.charge(rate_limit.watches, rate_limit.watches_total, client, officer=officer)
    if refused is not None:
        case_refs.refused(officer, refused)
        wait, who = refused
        detail = (f"This site has created {config.WATCHES_PER_HOUR_TOTAL} watches in the last hour."
                  if who == "site" else
                  f"This connection has created {config.WATCHES_PER_HOUR_PER_CLIENT} watches in the last hour.")
        raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(int(wait))})
    try:
        watch = watchlist.create_watch(owner, body.address, body.chain, body.asset,
                                       body.note, body.case_id, body.webhook_url,
                                       read_head=watchlist.chain_head, client=client)
    except watchlist.WatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record("watch.create", detail={"case_ref": case_refs.mask(ref)} if ref else None)
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


@router.delete("/watches/{watch_id}/webhook")
def delete_webhook(watch_id: str, http: Request) -> dict[str, Any]:
    """A leaked or unwanted webhook can be dropped without losing the watch.
    Not charged against the watch allowance: it only removes."""
    watch = watchlist.clear_webhook(_owner(http), watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="No such watch.")
    return watchlist.watch_summary(watch)


# A manual check reads the provider fresh, past the cache, so it is bounded
# per connection and for the site as a whole, per minute. Owner keys are free,
# so the per-watch cooldown alone bounded nothing. Its reads are charged to the
# connection's share of the day's provider allowance and to the part of it
# kept for watch checks (config.WATCH_SHARE_PERCENT), so checks can never use
# up what traces need. At 3 a minute (two reads each on Ethereum) one
# connection reaches its share of that part in a few hours, not minutes; the
# site-wide ceiling takes ten connections to fill.
CHECKS_PER_MINUTE_PER_CLIENT = 3
CHECKS_PER_MINUTE_TOTAL = 30
checks_per_client = rate_limit.SlidingWindowLimiter(CHECKS_PER_MINUTE_PER_CLIENT, 60)
checks_total = rate_limit.SlidingWindowLimiter(CHECKS_PER_MINUTE_TOTAL, 60)
# Watches being checked right now: a second click while the first is still
# reading would otherwise reach the provider again (the cooldown is only
# written once a check finishes).
_checking: set[str] = set()
_checking_lock = threading.Lock()


def _too_many(detail: str, wait: float) -> HTTPException:
    return HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(int(wait) + 1)})


def _cooled_down(watch: Any) -> None:
    since = watchlist.seconds_since_check(watch)
    if since is not None and since < watchlist.MIN_MANUAL_CHECK_SECONDS:
        wait = int(watchlist.MIN_MANUAL_CHECK_SECONDS - since) + 1
        raise HTTPException(status_code=429, detail=f"Checked {int(since)} s ago. Try again in {wait} s.",
                            headers={"Retry-After": str(wait)})


@router.post("/watches/{watch_id}/check")
def check_now(watch_id: str, http: Request, user: CurrentUser) -> dict[str, Any]:
    owner = _owner(http)
    watch = watchlist.get_owned_watch(owner, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="No such watch.")
    watchlist.touch(owner, [watch_id])  # the owner still uses it: it keeps its slot
    _cooled_down(watch)
    with _checking_lock:
        if watch_id in _checking:
            raise _too_many("This watch is being checked right now.", 5)
        # Read again under the lock: a check that finished since the read
        # above has just written the time the cooldown counts from.
        _cooled_down(watchlist.get_owned_watch(owner, watch_id) or watch)
        client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
        # A signed-in officer's own hourly and daily checks count too (case_refs.py).
        officer = case_refs.spender(user, "check")
        refused = rate_limit.charge(checks_per_client, checks_total, client, officer=officer)
        if refused is not None:
            case_refs.refused(officer, refused)
            wait, who = refused
            raise _too_many("This site has made as many manual checks as it allows this minute. "
                            "Try again shortly." if who == "site" else
                            f"This connection has checked {CHECKS_PER_MINUTE_PER_CLIENT} watches "
                            "in the last minute. Try again shortly.", wait)
        _checking.add(watch_id)
    try:
        with api_budget.charged_to(client, watch=True):
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
