"""Tracing, and the case store it writes to.

POST /trace runs the pipeline and stores the result; GET /trace/{case_id}
reads a stored case back as it was when traced, never re-run. Its exports
are in evidence.py; the history list and correlation in casebook.py."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .. import api_budget, audit, case_privacy, case_refs, config, models, ownership, pipeline, rate_limit
from ..auth import CurrentUser, is_page_load
from ..contracts import on_read
from ..pipeline import TraceRequest


logger = logging.getLogger(__name__)
router = APIRouter()

# Traces in progress, server-wide; see config.TRACE_MAX_RUNNING.
_running = threading.BoundedSemaphore(config.TRACE_MAX_RUNNING)


# Running traces per connection, so one cannot hold every slot above.
_running_by_client: dict[str, int] = {}
_by_client_lock = threading.Lock()


class SlotClock:
    """How long each connection has held trace slots in the last hour.

    A slot is held a few minutes at most (the trace's wall clock), so a cap
    on how many one connection holds at once still let a few connections
    re-send traces and keep every slot busy all day. Counting the minutes held
    makes that cost many connections: one may hold slots for
    TRACE_SLOT_MINUTES_PER_HOUR (all its slots together) in any hour, running
    holds included. In memory, like the hourly limits: a restart forgets it.
    Batch rows are not counted here; they run in the batch slot."""

    MAX_KEYS = 10_000  # keys come from headers a client may invent; bounded whatever they say

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._done: dict[str, deque[tuple[float, float]]] = {}  # client -> (start, end) of finished holds
        self._open: dict[str, list[float]] = {}  # client -> starts of holds still running

    def used(self, client: str) -> float:
        """Seconds of the last hour this client held slots. Under _by_client_lock."""
        now = self._clock()
        since = now - 3600
        done = self._done.get(client)
        while done and done[0][1] <= since:
            done.popleft()
        if done is not None and not done:
            del self._done[client]
            done = None
        held = sum(end - max(start, since) for start, end in done or ())
        return held + sum(now - max(start, since) for start in self._open.get(client, ()))

    def start(self, client: str) -> None:
        self._open.setdefault(client, []).append(self._clock())

    def stop(self, client: str) -> None:
        starts = self._open.get(client)
        if not starts:
            return
        start = starts.pop(0)
        if not starts:
            del self._open[client]
        done = self._done.setdefault(client, deque())
        done.append((start, self._clock()))
        while len(self._done) > self.MAX_KEYS:  # oldest-seen first
            del self._done[next(iter(self._done))]

    def reset(self) -> None:
        self._done.clear()
        self._open.clear()


_slot_clock = SlotClock()


def _refusal(detail: str, wait: int = 30) -> HTTPException:
    return HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(wait)})


def take_slot(client: str, timed: bool = True) -> str | None:
    """Take one of the server's trace slots for `client`, or say why not.

    None on success (the caller must give it back with release(client)), else
    a sentence for the refusal. The rules, in order:

    1. A connection holds at most TRACES_RUNNING_PER_CLIENT slots at once.
    2. The last TRACE_RESERVED_SLOTS free slots are only for a connection with
       nothing running: a connection already tracing cannot take the last
       one, so a newcomer -- a presenter, a judge -- finds a slot even while
       others keep theirs busy. Filling every slot then takes as many
       connections as there are slots, not two.
    3. A connection that held slots for TRACE_SLOT_MINUTES_PER_HOUR in the
       last hour waits (`timed`; batch rows are not timed: they hold the one
       batch slot, by design for as long as a batch runs).
    4. The server runs at most TRACE_MAX_RUNNING.
    """
    with _by_client_lock:
        mine = _running_by_client.get(client, 0)
        if mine >= config.TRACES_RUNNING_PER_CLIENT > 0:
            return (f"This connection already has {mine} trace{'s' if mine != 1 else ''} running. "
                    "Wait for one to finish, or open a stored case in the meantime.")
        held = sum(_running_by_client.values())
        free = config.TRACE_MAX_RUNNING - held
        if mine and 0 < free <= config.TRACE_RESERVED_SLOTS:
            return ("This connection already has a trace running, and the last free slot is kept "
                    "for someone with none. Wait for yours to finish.")
        budget = config.TRACE_SLOT_MINUTES_PER_HOUR * 60
        if timed and budget and _slot_clock.used(client) >= budget:
            return (f"This connection has kept traces running for {config.TRACE_SLOT_MINUTES_PER_HOUR} "
                    "minutes in the last hour. Try again later, or open a stored case in the meantime.")
        if not _running.acquire(blocking=False):
            return (f"{config.TRACE_MAX_RUNNING} traces are already running. "
                    "Try again in a minute, or open a stored case in the meantime.")
        _running_by_client[client] = mine + 1
        if timed:
            _slot_clock.start(client)
    return None


def admit(http: Request, user: Any = None) -> str:
    """Refuse a trace this client may not start now (take_slot's rules, then
    its hourly limit, and a signed-in officer's own). On success the caller
    holds a running slot and must hand the returned token to `release()`.

    The hourly allowance is charged last, once a slot is taken: a visitor
    turned away because the server is busy has started nothing."""
    client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
    refused_slot = take_slot(client)
    if refused_slot is not None:
        raise _refusal(refused_slot)
    officer = case_refs.spender(user, "trace") if user is not None else None
    refused = rate_limit.charge(rate_limit.traces, rate_limit.traces_total, client, officer=officer)
    if refused is not None:
        release(client)
        case_refs.refused(officer, refused)
        wait, who = refused
        started = (f"This site has started {config.TRACES_PER_HOUR_TOTAL} traces" if who == "site"
                   else f"This connection has started {config.TRACES_PER_HOUR_PER_CLIENT} traces")
        raise _refusal(f"{started} in the last hour. Try again in {int(wait // 60) + 1} min, or open a "
                       "stored case in the meantime.", int(wait))
    return client


def release(client: str | None = None, timed: bool = True) -> None:
    """Give back a running slot; `client` is the token admit() returned, or
    the batch's connection with timed=False (none: a slot taken directly)."""
    if client is not None:
        with _by_client_lock:
            left = _running_by_client.get(client, 0) - 1
            if left > 0:
                _running_by_client[client] = left
            else:
                _running_by_client.pop(client, None)
            if timed:
                _slot_clock.stop(client)
    _running.release()


def _count(query, *args) -> int:
    """A count for the caps, read before the save. One that cannot be read
    counts as room: a store that is really down then fails the save, which
    keeps the result with a warning. Storage must never lose a completed trace."""
    try:
        return query(*args)
    except Exception:  # noqa: BLE001
        logger.warning("Could not count stored cases; saving anyway", exc_info=True)
        return 0


def connection_hash(client: str | None) -> str | None:
    """The connection that saved a case, hashed (the key is rate_limit.client_ip's:
    an IPv6 address already counts as its /64)."""
    if not client:
        return None
    return hashlib.sha256(b"exchequer-case-client:" + client.encode()).hexdigest()


def _not_saved(payload: dict[str, Any], warning: str) -> dict[str, Any]:
    payload["case_id"] = None
    payload.setdefault("warnings", []).append(warning)
    return payload


def _since(seconds: int) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _make_room(rows: int, nbytes: int) -> tuple[int, int]:
    """Evict the oldest cases nobody is using until `rows` cases and `nbytes`
    bytes are freed, or none is left: (cases, bytes) freed."""
    try:
        gone, freed = models.evict_cases(rows, _since(config.CASE_IDLE_DAYS * 86400), nbytes=nbytes)
    except Exception:  # noqa: BLE001 -- refused below as full, never lost
        logger.warning("Could not make room in the case store", exc_info=True)
        return 0, 0
    if gone:
        logger.warning("Case store full: %d unused case%s (%d bytes) gave up their place",
                       gone, "s" if gone != 1 else "", freed)
    return gone, freed


def _without_flows(payload: dict[str, Any]) -> dict[str, Any]:
    """The case without its victim_flow, nor its follow-ons', to measure. Shares the rest."""
    def bare(result: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in result.items() if k != "victim_flow"}
    out = bare(payload)
    if isinstance(payload.get("follow_ons"), list):
        out["follow_ons"] = [{**f, "result": bare(f["result"])}
                             if isinstance(f, dict) and isinstance(f.get("result"), dict) else f
                             for f in payload["follow_ons"]]
    return out


def store_result(payload: dict[str, Any], request: TraceRequest, owner: str | None,
                 client: str | None = None, officer: tuple[int | None, int | None] = (None, None)) -> dict[str, Any]:
    """Give a finished trace its case id and, unless asked not to, store it.
    `client` is the admit() token of the connection that started it;
    `officer` the signed-in officer's (id, unit id) that traced it."""
    case_id = models.new_case_id()
    created_at = models.utc_now_iso()
    if request.case_ref:  # kept as payment_intake keeps the NCRP number
        payload["intake"] = {**(payload.get("intake") or {"mode": "address", "payments": [], "ncrp_ack": None}),
                             "case_ref": request.case_ref}
    payload["case_id"] = case_id
    payload["created_at"] = created_at
    if not request.save:
        payload["case_id"] = None
        return payload

    mine = _count(models.case_count_for, owner) if owner and config.MAX_CASES_PER_OWNER else 0
    if owner and config.MAX_CASES_PER_OWNER and mine >= config.MAX_CASES_PER_OWNER:
        return _not_saved(payload, f"This browser already keeps {config.MAX_CASES_PER_OWNER:,} cases, so "
                                   "this result is shown here but was not saved: export what you need from it now.")
    connection = connection_hash(client)
    if connection and config.MAX_CASES_PER_CLIENT_PER_DAY:
        today = _count(models.case_count_from, connection, _since(86400))
        if today >= config.MAX_CASES_PER_CLIENT_PER_DAY:
            return _not_saved(payload, f"This connection has saved {config.MAX_CASES_PER_CLIENT_PER_DAY:,} "
                                       "cases in the last 24 hours, so this result is shown here but was not "
                                       "saved: export what you need from it now.")

    # One dense trace could be megabytes: refused alone over MAX_CASE_BYTES,
    # and the store as a whole is bounded in bytes as well as in cases.
    try:
        text = json.dumps(payload, default=str)
        measured = len(text)
        if config.MAX_CASE_BYTES and measured > config.MAX_CASE_BYTES:
            # The victim flows add 15-20 %, so the limit is measured without
            # them, but the case keeps them: a flow rebuilt on read from the
            # trimmed appendix would differ from the one shown now.
            measured = len(json.dumps(_without_flows(payload), default=str))
    except (TypeError, ValueError):
        text = None  # save_case reports it below
    if text is not None and config.MAX_CASE_BYTES and measured > config.MAX_CASE_BYTES:
        logger.warning("Case of %d bytes not stored (limit %d)", measured, config.MAX_CASE_BYTES)
        return _not_saved(payload, f"This result is too large to save ({measured / 1e6:.1f} MB; the limit "
                                   f"is {config.MAX_CASE_BYTES / 1e6:.1f} MB), so it is shown here but was not "
                                   "saved: export what you need from it now, or trace again with a smaller depth.")
    size = len(text) if text is not None else 0
    # Bytes as well as cases, per connection and per owner key: the counts
    # alone let one connection fill the store's bytes with dense cases.
    if connection and config.MAX_BYTES_PER_CLIENT_PER_DAY:
        today = _count(models.bytes_from, connection, _since(86400))
        if today + size > config.MAX_BYTES_PER_CLIENT_PER_DAY:
            return _not_saved(payload, f"This connection has saved {today / 1e6:.1f} MB of cases in the last 24 "
                                       f"hours, and this one ({size / 1e6:.1f} MB) would pass the "
                                       f"{config.MAX_BYTES_PER_CLIENT_PER_DAY / 1e6:,.0f} MB a connection may "
                                       "save in a day, so it is shown here but was not saved: export what you "
                                       "need from it now.")
    if owner and config.MAX_BYTES_PER_OWNER:
        kept = _count(models.bytes_for, owner)
        if kept + size > config.MAX_BYTES_PER_OWNER:
            return _not_saved(payload, f"This browser already keeps {kept / 1e6:.1f} MB of cases, and this one "
                                       f"({size / 1e6:.1f} MB) would pass the {config.MAX_BYTES_PER_OWNER / 1e6:,.0f} "
                                       "MB one browser may keep, so it is shown here but was not saved: export "
                                       "what you need from it now.")

    stored = _count(models.case_count) if config.MAX_STORED_CASES else 0
    total = _count(models.stored_bytes) if config.MAX_STORED_BYTES else 0
    if config.MAX_STORED_CASES and stored + 1 == int(config.MAX_STORED_CASES * 0.8):
        logger.warning("Case store is 80%% full (%d of %d cases)", stored + 1, config.MAX_STORED_CASES)
    if config.MAX_STORED_BYTES and total < config.MAX_STORED_BYTES * 0.8 <= total + size:
        logger.warning("Case store is 80%% full (%d of %d bytes)", total + size, config.MAX_STORED_BYTES)
    rows_over = stored + 1 - config.MAX_STORED_CASES if config.MAX_STORED_CASES else 0
    bytes_over = total + size - config.MAX_STORED_BYTES if config.MAX_STORED_BYTES else 0
    if rows_over > 0 or bytes_over > 0:
        rows, freed = _make_room(rows_over, bytes_over)
        stored, total = stored - rows, total - freed
    if config.MAX_STORED_CASES and stored >= config.MAX_STORED_CASES:
        logger.warning("Case store full (%d cases); trace not stored", config.MAX_STORED_CASES)
        return _not_saved(payload, f"The case store is full ({config.MAX_STORED_CASES:,} cases), so this "
                                   "result is shown here but was not saved: it will not appear in the case "
                                   "history and cannot be exported or reopened later. Ask the operator to "
                                   "raise EXCHEQUER_MAX_STORED_CASES.")
    if config.MAX_STORED_BYTES and total + size > config.MAX_STORED_BYTES:
        logger.warning("Case store full (%d of %d bytes); trace not stored", total, config.MAX_STORED_BYTES)
        return _not_saved(payload, f"The case store is full ({config.MAX_STORED_BYTES / 1e6:,.0f} MB), so "
                                   "this result is shown here but was not saved: it will not appear in the "
                                   "case history and cannot be exported or reopened later. Ask the operator "
                                   "to make room in the store.")

    try:
        models.save_case(case_id, payload["address"], payload, created_at=created_at,
                         owner_hash=owner or ownership.orphan_hash(), result_json=text,
                         client_hash=connection, anonymous=owner is None,
                         officer_id=officer[0], unit_id=officer[1])
    except Exception:  # storage must never lose a completed trace
        logger.exception("Failed to persist case %s", case_id)
        # No id for a case that does not exist: the page would open it, find
        # nothing, and lose the result the officer just waited for.
        payload["case_id"] = None
        payload.setdefault("warnings", []).append(
            "Result could not be saved to the case database; it is shown here "
            "but will not appear in the case history."
        )
    return payload


def record_trace(payload: dict[str, Any], via: str | None = None) -> None:
    """Audit a finished trace (CLAUDE.md rule 5): what kind of trace, not whose.

    No address and no NCRP number goes into the detail, and the case
    reference only masked: the audit log is kept for good, and is no place
    for a complaint's particulars.
    `via` names a path other than the API and jobs ("batch").
    """
    intake = payload.get("intake") or {}
    detail = {
        "chain": payload.get("chain"),
        "asset": payload.get("asset"),
        "direction": payload.get("direction"),
        "mode": intake.get("mode", "address"),
        # Distinct hashes: one payment can arrive as several transfers (legs).
        "payments": len({p.get("tx_hash") for p in intake.get("payments") or []}),
        "saved": bool(payload.get("case_id")),
        "exchange_reached": bool(payload.get("exchange")),
    }
    if intake.get("case_ref"):
        detail["case_ref"] = case_refs.mask(intake["case_ref"])
    if via:
        detail["via"] = via
    audit.record("case.trace", case_id=payload.get("case_id"), detail=detail)


def record_start(request: TraceRequest, via: str | None = None) -> None:
    """Audit that a trace began: what kind, as record_trace says it, never whose."""
    detail = {"chain": request.chain, "asset": request.asset, "direction": request.direction,
              "mode": "payments" if request.payments else "address"}
    if via:
        detail["via"] = via
    audit.record("case.trace_start", detail=detail)


def record_trace_safely(payload: dict[str, Any]) -> None:
    """record_trace, for a trace that has already finished: an audit sink that
    fails is logged, never a reason to lose the result."""
    try:
        record_trace(payload)
    except Exception:  # noqa: BLE001
        logger.exception("Could not audit case %s", payload.get("case_id"))


@router.post("/trace")
def trace(request: TraceRequest, http: Request, user: CurrentUser) -> dict[str, Any]:
    """Trace funds to or from a reported address.

    Outgoing answers "where did the victim's money go"; incoming answers "who
    sent money to this address", which on a scammer's wallet enumerates the
    other people who paid it. The whole trace runs inside this request; the
    app itself uses POST /trace/jobs, which runs it in the background.
    """
    request.case_ref = case_refs.required(user, request.case_ref)
    pipeline.check_request(request)
    slot = admit(http, user)
    record_start(request)
    try:
        # The admit() token: this connection's share of the day's provider allowance.
        with api_budget.using(api_budget.TraceBudget.for_request(request.time_budget_seconds, client=slot)):
            payload = pipeline.run_trace(request)
    finally:
        release(slot)
    stored = store_result(payload, request, user.owner_hash, client=slot, officer=(user.officer_id, user.unit_id))
    record_trace_safely(stored)
    return stored


_INDEX_HTML = config.BACKEND_DIR.parent / "frontend" / "dist" / "index.html"


def _is_page_load(http: Request) -> bool:
    """A browser opening the URL, as opposed to the app's own fetch()."""
    return is_page_load(http)


def app_page(http: Request) -> FileResponse | None:
    """The app, for a browser opening a URL the API claims first: the app's
    own pages /trace/<address>, /cases and /requests are API paths too, and a
    shared link or a reload must not show the API's JSON. None for fetch()."""
    if _is_page_load(http) and _INDEX_HTML.is_file():
        return FileResponse(_INDEX_HTML, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return None


@router.get("/trace/intake")
def trace_intake() -> dict[str, Any]:
    """What the trace form may offer: whether a trace can start from the victim's
    payment hashes (R1, EXCHEQUER_TX_INTAKE), and how many of the reported
    wallet's incoming transfers are searched for them. Registered before
    /trace/{case_id}, which would otherwise read "intake" as a case id."""
    return {"payments": config.TX_INTAKE, "lookup_limit": config.TX_INTAKE_LOOKUP_LIMIT}


@router.get("/trace/{case_id}", response_model=None)
def get_trace(case_id: str, http: Request, user: CurrentUser) -> JSONResponse | FileResponse:
    """Retrieve a previously traced case.

    /trace/<address> is also the app's own URL for a trace in progress, and
    the API claims the path first. A shared link or a reload of that page
    would get this endpoint's JSON 404; a browser navigation gets the app.

    The case is returned as a ready JSONResponse, rendered here in the worker
    thread: a plain dict would be walked by jsonable_encoder on the event
    loop, and a large case then stalled every other request.

    Anyone holding the id gets the case -- it is the reference letters print
    -- but a complaint's particulars only reach the browser that traced it
    and its officer's unit (case_privacy.py, ownership.reader). What a read adds to a case stored before it (a
    current victim flow, freeze dates, which wallets the walk read) is built
    from that same copy, so it names nothing the copy withholds."""
    if (page := app_page(http)) is not None:
        return page
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    return JSONResponse(on_read(case_privacy.for_reader(case.result, case.owner_hash, ownership.reader(case, user))))
