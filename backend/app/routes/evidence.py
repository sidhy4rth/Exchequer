"""What a stored case is exported as: the report, the transfer graph and the
draft request letters. Each reads the case as it was traced, never re-run.

Each takes the caller and records what it did. `user` does nothing here until R23
and R24 land; having it now means these routes do not change when they do."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response

from .. import audit, graph_export, models, rate_limit, report_cache, request_letters
from ..auth import CurrentUser
from ..report_pdf import render_pdf

router = APIRouter()

# A stored case never changes, so a browser may keep its report for an hour.
KEEP = {"Cache-Control": "private, max-age=3600"}


def _pdf(case: models.Case, http: Request) -> bytes:
    """The case's PDF: kept after its first render (report_cache.py). A render
    is the costliest thing a visitor can ask for, so a miss is charged to the
    client's and the site's hourly PDF limits and only one runs at a time."""
    cached = report_cache.cached_pdf(case)
    if cached is not None:
        return cached
    client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
    refused = rate_limit.charge(report_cache.pdf_renders, report_cache.pdf_renders_total, client)
    if refused is not None:
        wait, who = refused
        raise HTTPException(
            status_code=429, headers={"Retry-After": str(int(wait))},
            detail=("Too many PDF reports prepared " + ("for you" if who == "client" else "on this server")
                    + " in the last hour; try again later, or download the text report, which is the signed one."))
    if not report_cache.render_slot.acquire(blocking=False):
        report_cache.pdf_renders.refund(client)
        report_cache.pdf_renders_total.refund(rate_limit.TOTAL)
        raise HTTPException(status_code=429, headers={"Retry-After": "5"},
                            detail="A report is being prepared; try again in a few seconds.")
    try:
        pdf = report_cache.cached_pdf(case)  # made while this request waited for the slot
        if pdf is None:
            pdf = render_pdf(report_cache.report(case), report_cache.text(case))
            report_cache.store_pdf(case, pdf)
        return pdf
    finally:
        report_cache.render_slot.release()


@router.get("/trace/{case_id}/report")
def get_report(
    case_id: str,
    user: CurrentUser,
    http: Request,
    format: str = Query("json", pattern="^(json|text|pdf)$", description="json, text or pdf"),
):
    """Exportable summary suitable for a law-enforcement handoff.

    Every format of a case is the same report, rendered once (report_cache.py)."""
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")

    if format == "pdf":
        response = Response(
            _pdf(case, http),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}.pdf"', **KEEP},
        )
    elif format == "text":
        response = PlainTextResponse(
            report_cache.text(case),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="exchequer-{case_id[:8]}.txt"'
                ),
                **KEEP,
            },
        )
    else:
        response = report_cache.report(case)
    audit.record("case.report_export", case_id=case_id, detail={"format": format})
    return response


@router.get("/trace/{case_id}/graph")
def export_graph(
    case_id: str,
    user: CurrentUser,
    format: str = Query("graphml", pattern="^(graphml|csv)$", description="graphml or csv"),
) -> Response:
    """The case's transfer graph for Gephi, yEd, Maltego (GraphML) or a spreadsheet (CSV)."""
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    if format == "csv":
        body, media, ext = graph_export.to_csv(case_id, case.result), "text/csv", "csv"
    else:
        body, media, ext = graph_export.to_graphml(case_id, case.result), "application/graphml+xml", "graphml"
    audit.record("case.graph_export", case_id=case_id, detail={"format": format})
    return Response(body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}-graph.{ext}"'})


@router.get("/trace/{case_id}/letters")
def list_letters(case_id: str, user: CurrentUser) -> dict[str, Any]:
    """Which request letters this case can support: to the exchange, to Tether."""
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    letters = request_letters.available(case.result)
    audit.record("case.letters_list", case_id=case_id)
    return {"case_id": case_id, "letters": letters}


@router.get("/trace/{case_id}/letter")
def get_letter(
    case_id: str,
    user: CurrentUser,
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
    audit.record("case.letter_draft", case_id=case_id, detail={"to": to, "format": "text"})
    return PlainTextResponse(
        text,
        headers={"Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}-request-{to}.txt"'},
    )
