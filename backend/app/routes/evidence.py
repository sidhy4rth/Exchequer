"""What a stored case is exported as: the report, the transfer graph and the
draft request letters. Each reads the case as it was traced, never re-run.

Each takes the caller and records what it did. `user` does nothing here until R23
and R24 land; having it now means these routes do not change when they do."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response

from .. import audit, graph_export, models, request_letters
from ..auth import CurrentUser
from ..report import build_report, render_text_report
from ..report_pdf import render_pdf

router = APIRouter()


@router.get("/trace/{case_id}/report")
def get_report(
    case_id: str,
    user: CurrentUser,
    format: str = Query("json", pattern="^(json|text|pdf)$", description="json, text or pdf"),
):
    """Exportable summary suitable for a law-enforcement handoff."""
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")

    report = build_report(case)
    if format == "pdf":
        response = Response(
            render_pdf(report, render_text_report(report)),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}.pdf"'},
        )
    elif format == "text":
        response = PlainTextResponse(
            render_text_report(report),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="exchequer-{case_id[:8]}.txt"'
                )
            },
        )
    else:
        response = report
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
