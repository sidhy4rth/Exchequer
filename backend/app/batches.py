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
against the client's hourly trace limit in full, up front.

One trace at a time, sharing the server's running ceiling with everyone
else: a batch is patient, an investigator at the console is not. A restart
stops a batch; the rows already traced keep their cases and the rest are
marked interrupted.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import Counter
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from . import config, models
from .correlation import correlate
from .pipeline import TraceRequest

logger = logging.getLogger(__name__)

MAX_ROWS = 25
PENDING, RUNNING, DONE, FAILED, INTERRUPTED = "pending", "running", "done", "failed", "interrupted"


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
    batch = models.Batch(id=str(uuid.uuid4()), owner_hash=owner, name=(name or "")[:120],
                         created_at=models.utc_now_iso(), status=RUNNING, rows_json=json.dumps(rows))
    with models.session() as s:
        s.add(batch)
        s.commit()
        s.refresh(batch)
        s.expunge(batch)
    return batch


def _save_rows(batch_id: str, rows: list[dict[str, Any]], status: str | None = None) -> None:
    with models.session() as s:
        batch = s.get(models.Batch, batch_id)
        if batch is None:
            return
        batch.rows_json = json.dumps(rows)
        if status:
            batch.status = status
        s.commit()


def run(batch_id: str, owner: str, acquire, release, trace_fn, store_fn) -> None:
    """Trace every pending row in order. Injected callables keep this testable:
    acquire/release a running slot, trace a TraceRequest, store a payload."""
    with models.session() as s:
        batch = s.get(models.Batch, batch_id)
        rows = json.loads(batch.rows_json) if batch else []
    for row in rows:
        if row["status"] != PENDING:
            continue
        row["status"] = RUNNING
        _save_rows(batch_id, rows)
        while not acquire():
            time.sleep(2)  # wait for a free slot rather than refusing
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
        _save_rows(batch_id, rows)
    _save_rows(batch_id, rows, status=DONE)


def start(batch_id: str, owner: str, acquire, release, trace_fn, store_fn) -> None:
    threading.Thread(target=run, args=(batch_id, owner, acquire, release, trace_fn, store_fn),
                     name=f"batch-{batch_id[:8]}", daemon=True).start()


def mark_interrupted() -> None:
    """At startup: batches a restart cut short say so, row by row."""
    with models.session() as s:
        for batch in s.scalars(select(models.Batch).where(models.Batch.status == RUNNING)):
            rows = json.loads(batch.rows_json)
            for row in rows:
                if row["status"] in (PENDING, RUNNING):
                    row["status"] = INTERRUPTED
            batch.rows_json = json.dumps(rows)
            batch.status = INTERRUPTED
        s.commit()


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
    with models.session() as s:
        batch = s.get(models.Batch, batch_id)
        if batch is None or batch.owner_hash != owner:
            return None
        s.expunge(batch)
        return batch


def list_for(owner: str) -> list[dict[str, Any]]:
    with models.session() as s:
        batches = list(s.scalars(select(models.Batch).where(models.Batch.owner_hash == owner)
                                 .order_by(models.Batch.created_at.desc()).limit(50)))
        return [{k: v for k, v in summary(b).items() if k != "rows"} for b in batches]
