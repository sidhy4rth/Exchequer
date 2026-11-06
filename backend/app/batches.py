"""Trace a list of reported addresses, then look across them.

A cyber cell receives complaints in bulk -- an export from the reporting
portal, a spreadsheet from a bank -- and the useful question is often not
"where did this one go" but "which of these are the same operation". A batch
takes up to MAX_ROWS rows (address, chain, asset, direction, depth and the
complaint's own reference), traces them one after another in the
background, stores each as an ordinary case owned by the browser that sent
the batch, and then correlates the batch's cases with each other: the
wallets two or more of these complaints share, and the exchanges they
reached.

Rows are checked before anything runs, so a typo is reported against its
row number rather than discovered twenty minutes in. The batch is charged
against the client's hourly trace limit in full, up front; rows that never
reach a trace are given back when the batch ends.

One trace at a time, sharing the server's running ceiling with everyone
else: a batch is patient, an investigator at the console is not. A restart
stops a batch; the rows already traced keep their cases and the rest are
marked interrupted. A batch always ends: done, or failed with each
unfinished row saying why -- never 'running' with no runner behind it.

The store can be shared by two instances at once (Render runs the old one
beside the new during a deploy), so a batch belongs to whichever runner keeps
its heartbeat fresh: only one silent for STALE_AFTER_SECONDS is marked
interrupted, and every progress write is made only while the batch is still
running, so a runner whose batch was interrupted stops instead of
overwriting it.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import Counter
from typing import Any

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from . import config, models
from .correlation import correlate
from .pipeline import TraceRequest

logger = logging.getLogger(__name__)

MAX_ROWS = 25
# Of the server's trace slots (config.TRACE_MAX_RUNNING), all batches together
# hold at most BATCH_SLOTS, so live traces always find the rest free. A browser
# has one active batch at a time, the site at most MAX_ACTIVE_BATCHES; the
# others are refused rather than queued behind each other for hours.
BATCH_SLOTS = 1
MAX_ACTIVE_BATCHES = 3
PENDING, RUNNING, DONE, FAILED, INTERRUPTED = "pending", "running", "done", "failed", "interrupted"
# A store write that fails (a dropped connection, a busy SQLite file, a pool
# with no free connection) is tried again after each of these waits, seconds.
SAVE_RETRY_DELAYS = (0.5, 2.0, 5.0)
_STORE_ERRORS = (DBAPIError, PoolTimeoutError)
_sleep = time.sleep  # tests skip the waits
STORE_GAVE_UP = "Stopped: the case store could not be written. Run these rows again."
# A running batch's runner writes heartbeat_at at least this often (seconds);
# one silent for STALE_AFTER_SECONDS has no runner left.
HEARTBEAT_SECONDS = 30.0
STALE_AFTER_SECONDS = 120


class BatchGone(Exception):
    """The batch is no longer running (interrupted by another instance): stop."""


class BatchError(ValueError):
    def __init__(self, message: str, row_errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.row_errors = row_errors or []


def validate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalised rows, or BatchError listing every bad row by number (1-based)."""
    if not rows:
        raise BatchError("The batch has no rows.")
    if len(rows) > MAX_ROWS:
        raise BatchError(f"A batch holds at most {MAX_ROWS} rows; this one has {len(rows)}. Split it.")
    clean, errors = [], []
    for n, raw in enumerate(rows, start=1):
        address = str(raw.get("address") or "").strip()
        try:
            chain = config.get_chain((raw.get("chain") or None) and str(raw["chain"]).strip().lower())
        except config.UnknownChainError as exc:
            errors.append({"row": n, "error": str(exc)})
            continue
        if not chain.validate_address(address):
            errors.append({"row": n, "error": f"'{address[:60]}' is not a valid {chain.name} address."})
            continue
        asset = str(raw.get("asset") or chain.native_symbol).strip().upper()
        if asset != chain.native_symbol.upper() and chain.find_token(asset) is None:
            errors.append({"row": n, "error": f"{chain.name} has no traceable asset '{asset}'."})
            continue
        direction = str(raw.get("direction") or "outgoing").strip().lower()
        if direction not in ("outgoing", "incoming"):
            errors.append({"row": n, "error": "direction must be outgoing or incoming."})
            continue
        try:
            depth = int(raw.get("max_depth") or raw.get("depth") or config.TRACE_MAX_DEPTH)
        except (TypeError, ValueError):
            errors.append({"row": n, "error": "depth must be a whole number from 1 to 6."})
            continue
        if not 1 <= depth <= 6:
            errors.append({"row": n, "error": "depth must be a whole number from 1 to 6."})
            continue
        clean.append({
            "row": n, "address": address, "chain": chain.key, "asset": asset,
            "direction": direction, "max_depth": depth,
            "reference": str(raw.get("reference") or "")[:120],
            "status": PENDING, "case_id": None, "exchange": None, "confidence": None, "error": None,
        })
    if errors:
        raise BatchError(f"{len(errors)} row{'s' if len(errors) != 1 else ''} cannot be traced as written.", errors)
    return clean


def create(owner: str, name: str, rows: list[dict[str, Any]]) -> models.Batch:
    now = models.utc_now_iso()
    batch = models.Batch(id=str(uuid.uuid4()), owner_hash=owner, name=(name or "")[:120],
                         created_at=now, status=RUNNING, rows_json=json.dumps(rows), heartbeat_at=now)
    with models.session() as s:
        s.add(batch)
        s.commit()
        s.refresh(batch)
        s.expunge(batch)
    return batch


def _retrying(what: str, fn):
    """fn(), tried again after each of SAVE_RETRY_DELAYS when the store fails."""
    for delay in (*SAVE_RETRY_DELAYS, None):
        try:
            return fn()
        except _STORE_ERRORS as exc:
            if delay is None:
                raise
            logger.warning("Batch store %s failed (%s); trying again in %.1f s", what, type(exc).__name__, delay)
            _sleep(delay)


def _load_rows(batch_id: str) -> list[dict[str, Any]]:
    with models.session() as s:
        batch = s.get(models.Batch, batch_id)
        return json.loads(batch.rows_json) if batch else []


def _write(batch_id: str, rows: list[dict[str, Any]], status: str | None = None) -> None:
    """Write the rows (and a heartbeat) while the batch is still running;
    BatchGone if it is not -- another instance marked it interrupted."""
    values: dict[str, Any] = {"rows_json": json.dumps(rows), "heartbeat_at": models.utc_now_iso()}
    if status:
        values["status"] = status
    with models.session() as s:
        stmt = update(models.Batch).where(models.Batch.id == batch_id, models.Batch.status == RUNNING)
        written = s.execute(stmt.values(**values).execution_options(synchronize_session=False)).rowcount
        s.commit()
    if written != 1:
        raise BatchGone(batch_id)


def _save_rows(batch_id: str, rows: list[dict[str, Any]], status: str | None = None) -> None:
    _retrying("save", lambda: _write(batch_id, rows, status))


def fail(batch_id: str, message: str, rows: list[dict[str, Any]] | None = None) -> None:
    """End the batch failed, every unfinished row saying why. Best effort:
    never raises (a restart still marks it interrupted)."""
    try:
        rows = rows or _retrying("load", lambda: _load_rows(batch_id))
        for row in rows:
            if row["status"] in (PENDING, RUNNING):
                row.update(status=FAILED, error=message)
        _retrying("save", lambda: _write(batch_id, rows, FAILED))
    except BatchGone:
        pass  # already ended elsewhere: leave what that wrote
    except Exception:  # noqa: BLE001 -- the caller is already handling a failure
        logger.exception("Batch %s could not be marked failed", batch_id)


def run(batch_id: str, owner: str, acquire, release, trace_fn, store_fn, record_fn=None) -> None:
    """Trace every pending row in order. Injected callables keep this testable:
    acquire/release a running slot, trace a TraceRequest, store a payload,
    record (audit) a stored payload.

    Store writes are retried; if the store still cannot be written the batch
    ends failed rather than staying 'running' with nothing behind it."""
    rows: list[dict[str, Any]] = []
    try:
        rows = _retrying("load", lambda: _load_rows(batch_id))
        for row in rows:
            if row["status"] != PENDING:
                continue
            row["status"] = RUNNING
            _save_rows(batch_id, rows)
            while not acquire():
                time.sleep(2)  # wait for a free slot rather than refusing
            payload = None
            try:
                request = TraceRequest(address=row["address"], chain=row["chain"], asset=row["asset"],
                                       direction=row["direction"], max_depth=row["max_depth"])
                payload = store_fn(trace_fn(request), request, owner)
                row.update(status=DONE, case_id=payload.get("case_id"), exchange=payload.get("exchange"),
                           confidence=payload.get("confidence"))
            except HTTPException as exc:
                row.update(status=FAILED, error=str(exc.detail)[:300])
            except Exception:  # noqa: BLE001 -- one bad row must not stop the batch
                logger.exception("Batch %s row %s failed", batch_id, row["row"])
                row.update(status=FAILED, error="The trace failed unexpectedly.")
            finally:
                release()
            if record_fn is not None and row["status"] == DONE:
                try:
                    record_fn(payload)
                except Exception:  # noqa: BLE001 -- the case is stored; the row stays done
                    logger.exception("Batch %s row %s: audit failed", batch_id, row["row"])
            _save_rows(batch_id, rows)
        _save_rows(batch_id, rows, status=DONE)
    except BatchGone:
        logger.warning("Batch %s is no longer running here (interrupted elsewhere); stopping", batch_id)
    except Exception:  # noqa: BLE001 -- the batch must not stay 'running' with no runner
        logger.exception("Batch %s stopped", batch_id)
        fail(batch_id, STORE_GAVE_UP, rows)


def start(batch_id: str, owner: str, acquire, release, trace_fn, store_fn, on_done=None,
          record_fn=None) -> None:
    """Run the batch in its own thread; `on_done()` once it ends, however it
    ends. Raises if no thread can be started: the caller then fails the batch."""
    def target() -> None:
        stop = threading.Event()
        try:
            # A row can trace for minutes; the heartbeat says the runner is alive meanwhile.
            threading.Thread(target=_heartbeat, args=(batch_id, stop), name=f"heartbeat-{batch_id[:8]}",
                             daemon=True).start()
        except RuntimeError:
            logger.warning("Batch %s runs without a heartbeat thread", batch_id)
        try:
            run(batch_id, owner, acquire, release, trace_fn, store_fn, record_fn)
        finally:
            stop.set()
            if on_done is not None:
                on_done()
    threading.Thread(target=target, name=f"batch-{batch_id[:8]}", daemon=True).start()


def _beat_once(batch_id: str) -> bool:
    """Refresh the heartbeat; False once the batch is no longer running."""
    with models.session() as s:
        stmt = (update(models.Batch).where(models.Batch.id == batch_id, models.Batch.status == RUNNING)
                .values(heartbeat_at=models.utc_now_iso()).execution_options(synchronize_session=False))
        beaten = s.execute(stmt).rowcount
        s.commit()
    return beaten == 1


def _heartbeat(batch_id: str, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            if not _beat_once(batch_id):
                return
        except Exception as exc:  # noqa: BLE001 -- a missed beat is retried; a long outage reads as silent
            logger.warning("Batch %s heartbeat failed: %s", batch_id, type(exc).__name__)


def _iso_ago(seconds: float) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _interrupt_silent(stale_after: float, *criteria) -> int:
    """Running batches whose heartbeat is older than `stale_after` seconds (or
    missing) have no runner left: mark them, row by row, interrupted. Each is
    changed only if its heartbeat is still the one read, so a runner that
    wrote meanwhile keeps its batch. Returns how many were marked."""
    beat = models.Batch.heartbeat_at
    marked = 0
    with models.session() as s:
        silent = list(s.scalars(select(models.Batch).where(
            models.Batch.status == RUNNING, or_(beat.is_(None), beat < _iso_ago(stale_after)), *criteria)))
        for batch in silent:
            rows = json.loads(batch.rows_json)
            for row in rows:
                if row["status"] in (PENDING, RUNNING):
                    row["status"] = INTERRUPTED
            stmt = (update(models.Batch)
                    .where(models.Batch.id == batch.id, models.Batch.status == RUNNING,
                           beat.is_not_distinct_from(batch.heartbeat_at))
                    .values(rows_json=json.dumps(rows), status=INTERRUPTED)
                    .execution_options(synchronize_session=False))
            marked += s.execute(stmt).rowcount
        s.commit()
    return marked


def mark_interrupted(stale_after: float = STALE_AFTER_SECONDS) -> int:
    """At startup: batches a restart cut short say so, row by row. A batch
    another instance is still running (fresh heartbeat) is left alone."""
    return _interrupt_silent(stale_after)


def _silent(batch: models.Batch) -> bool:
    return batch.status == RUNNING and (batch.heartbeat_at is None
                                        or batch.heartbeat_at < _iso_ago(STALE_AFTER_SECONDS))


def summary(batch: models.Batch, with_correlation: bool = False, excluded=None) -> dict[str, Any]:
    rows = json.loads(batch.rows_json)
    counts = Counter(r["status"] for r in rows)
    out: dict[str, Any] = {
        "batch_id": batch.id, "name": batch.name, "created_at": batch.created_at,
        "status": batch.status, "total": len(rows),
        "done": counts[DONE], "failed": counts[FAILED], "pending": counts[PENDING] + counts[RUNNING],
        "interrupted": counts[INTERRUPTED],
        "rows": rows,
    }
    if with_correlation:
        case_ids = [r["case_id"] for r in rows if r.get("case_id")]
        cases = [c for c in (models.get_case(cid) for cid in case_ids) if c is not None]
        clusters = correlate(cases, min_cases=2, excluded=excluded)
        by_case = {r["case_id"]: r for r in rows if r.get("case_id")}
        out["exchanges"] = Counter(r["exchange"] for r in rows if r.get("exchange")).most_common()
        out["shared_wallets"] = [{
            "address": c["address"], "chain": c["chain"],
            "inferred_exchange": c.get("inferred_exchange"), "risk_category": c.get("risk_category"),
            "rows": sorted({by_case[m["case_id"]]["row"] for m in c["cases"] if m["case_id"] in by_case}),
            "references": sorted({by_case[m["case_id"]]["reference"] for m in c["cases"]
                                  if m["case_id"] in by_case and by_case[m["case_id"]]["reference"]}),
        } for c in clusters]
    return out


def get(owner: str, batch_id: str) -> models.Batch | None:
    """The owner's batch; one whose runner has gone silent is marked
    interrupted first, so the page stops waiting for it."""
    for _ in range(2):
        with models.session() as s:
            batch = s.get(models.Batch, batch_id)
            if batch is None or batch.owner_hash != owner:
                return None
            s.expunge(batch)
        if not _silent(batch):
            return batch
        _interrupt_silent(STALE_AFTER_SECONDS, models.Batch.id == batch_id)
    return batch


def list_for(owner: str) -> list[dict[str, Any]]:
    _interrupt_silent(STALE_AFTER_SECONDS, models.Batch.owner_hash == owner)
    with models.session() as s:
        batches = list(s.scalars(select(models.Batch).where(models.Batch.owner_hash == owner)
                                 .order_by(models.Batch.created_at.desc()).limit(50)))
        return [{k: v for k, v in summary(b).items() if k != "rows"} for b in batches]
