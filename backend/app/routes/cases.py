"""Tracing, and the case store it writes to.

POST /trace runs the pipeline and stores the result; the rest read stored
cases back -- as they were when traced, never re-run -- as JSON, as a text
report, as draft request letters, or correlated with other cases."""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .. import config, models, ownership, pipeline, rate_limit, request_letters
from ..correlation import correlate, related_cases
from ..exchange_matcher import get_matcher, get_router_matcher
from ..pipeline import TraceRequest
from ..report import build_report, render_text_report



logger = logging.getLogger(__name__)
router = APIRouter()

# Traces in progress, server-wide; see config.TRACE_MAX_RUNNING.
_running = threading.BoundedSemaphore(config.TRACE_MAX_RUNNING)


@router.post("/trace")
def trace(request: TraceRequest, http: Request) -> dict[str, Any]:
    """Trace funds to or from a reported address.

    Outgoing answers "where did the victim's money go"; incoming answers "who
    sent money to this address", which on a scammer's wallet enumerates the
    other people who paid it.
    """
    client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
    wait = rate_limit.traces.check(client)
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail=(
                f"This connection has started {config.TRACES_PER_HOUR_PER_CLIENT} traces "
                f"in the last hour. Try again in {int(wait // 60) + 1} min, or open a "
                "stored case in the meantime."
            ),
            headers={"Retry-After": str(int(wait))},
        )
    if not _running.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail=(
                f"{config.TRACE_MAX_RUNNING} traces are already running. "
                "Try again in a minute, or open a stored case in the meantime."
            ),
            headers={"Retry-After": "30"},
        )
    try:
        payload = pipeline.run_trace(request)
    finally:
        _running.release()
    case_id = models.new_case_id()
    created_at = models.utc_now_iso()
    payload["case_id"] = case_id
    payload["created_at"] = created_at
    if not request.save:
        payload["case_id"] = None
        return payload

    try:
        owner = ownership.owner_hash_from_headers(http.headers) or ownership.orphan_hash()
        models.save_case(case_id, payload["address"], payload, created_at=created_at,
                         owner_hash=owner)
    except Exception:  # storage must never lose a completed trace
        logger.exception("Failed to persist case %s", case_id)
        payload.setdefault("warnings", []).append(
            "Result could not be saved to the case database; it is shown here "
            "but will not appear in the case history."
        )

    return payload


@router.get("/trace/{case_id}")
def get_trace(case_id: str) -> dict[str, Any]:
    """Retrieve a previously traced case."""
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    return case.result


@router.get("/trace/{case_id}/report")
def get_report(
    case_id: str,
    format: str = Query("json", pattern="^(json|text)$", description="json or text"),
):
    """Exportable summary suitable for a law-enforcement handoff."""
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")

    report = build_report(case)
    if format == "text":
        return PlainTextResponse(
            render_text_report(report),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="exchequer-{case_id[:8]}.txt"'
                )
            },
        )
    return report


@router.get("/trace/{case_id}/letters")
def list_letters(case_id: str) -> dict[str, Any]:
    """Which request letters this case can support: to the exchange, to Tether."""
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    return {"case_id": case_id, "letters": request_letters.available(case.result)}


@router.get("/trace/{case_id}/letter")
def get_letter(
    case_id: str,
    to: str = Query(..., pattern="^(exchange|tether)$", description="exchange or tether"),
) -> PlainTextResponse:
    """A draft request letter, filled from the case, for the officer to complete.

    A draft, never a sent document: the officer's details, the case reference
    and the legal provision are left as marked blanks.
    """
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    try:
        text = request_letters.draft(case_id, case.result, to)
    except request_letters.LetterNotApplicable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlainTextResponse(
        text,
        headers={"Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}-request-{to}.txt"'},
    )


@router.get("/cases")
def cases(http: Request, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    """History of past traces, most recent first: the caller's own cases (by
    the owner key their browser sends) and the demo cases. See ownership.py."""
    caller = ownership.owner_hash_from_headers(http.headers)
    records = models.list_cases(limit=limit, owner_hash=caller,
                                public_addresses=ownership.demo_addresses())
    # The deployed store holds the demos several times over (seeded more than
    # once); list each demo once, its newest trace. Records are newest first.
    seen_demo: set[tuple[str, str]] = set()
    kept = []
    for c in records:
        if ownership.is_public(c.owner_hash, c.address):
            key = (c.address.lower(), c.result.get("direction", "outgoing"))
            if key in seen_demo:
                continue
            seen_demo.add(key)
        kept.append(c)
    records = kept
    return {
        "count": len(records),
        "cases": [{**c.summary(), "demo": ownership.is_public(c.owner_hash, c.address)}
                  for c in records],
    }


@router.get("/cases/correlate")
def cases_correlate(
    http: Request,
    case_id: str | None = Query(None, description="only clusters that include this case"),
    min_cases: int = Query(2, ge=2, le=50),
) -> dict[str, Any]:
    """Intermediary addresses shared by two or more stored cases.

    The campaign view: separate complaints whose traced funds converge on the
    same unlabelled wallet or the same inferred deposit address. A query over
    what is already stored -- no new tracing, no API calls. Labelled exchange
    wallets, routers and sanctioned entities are never counted as shared
    intermediaries: two victims who both cashed out at Binance share a bank,
    not an offender.
    """
    records = models.all_cases()

    def known_contract_or_exchange(chain_key: str, address: str) -> bool:
        try:
            return bool(get_router_matcher(chain_key).lookup(address)
                        or get_matcher(chain_key).lookup(address))
        except config.UnknownChainError:
            return False

    clusters = correlate(records, only_case=case_id, min_cases=min_cases,
                         excluded=known_contract_or_exchange)
    # Every stored case counts towards a cluster, but only the caller's own,
    # the demo cases and the one they asked about (they hold its link) are
    # named; the rest are "another complaint". See ownership.py.
    caller = ownership.owner_hash_from_headers(http.headers)
    may_see = {c.id for c in records if ownership.visible_to(c.owner_hash, c.address, caller)}
    if case_id:
        may_see.add(case_id)
    related = related_cases(clusters, case_id) if case_id else []
    return {
        "cases_examined": len(records),
        "cluster_count": len(clusters),
        "clusters": ownership.redact_clusters(clusters, may_see),
        # The same answer grouped by the other case, which is how the trace
        # view shows it. Empty unless case_id was given.
        "related_cases": ownership.redact_related(related, may_see),
        "rule": (
            "An intermediary is any address in a stored trace, or in its follow-on "
            "traces after a swap, other than the reported address and other than a "
            "labelled exchange wallet, DEX router, sanctioned entity or mixer; a wallet "
            "Tether froze or an explorer flagged still counts. A cluster is an intermediary reached by traces "
            f"of at least {min_cases} different reported addresses on the same chain. "
            "Contracts recognised as services (a pool, WETH) and anything in the "
            "exchange or router label files are never intermediaries."
        ),
    }
