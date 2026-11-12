"""What a stored case is exported as: the report, the transfer graph and the
draft request letters. Each reads the case as it was traced, never re-run.

Each takes the caller and records what it did. The browser that traced a case
gets it as stored; anyone else holding the link gets it without the complaint's
particulars or anything that leads to the victim's wallet (case_privacy.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response

from pydantic import BaseModel

from .. import (audit, case_privacy, freeze_requests, models, notice_letters, ownership, rate_limit, report_cache,
               request_letters)
from ..auth import CurrentUser
from ..report_pdf import render_pdf

router = APIRouter()

# Never kept by the browser: the owner's copy holds the NCRP number, the
# victim's wallet and the payment hashes, and a shared PC's disk cache would
# hand them to the next user (r2-g2-log-redaction-http-edges-2-7). The server's
# report_cache already saves the re-render.
KEEP = {"Cache-Control": "no-store"}


def _case_or_404(case_id: str, user: CurrentUser) -> models.Case:
    """The case as this caller may read it."""
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    return case_privacy.case_for_reader(case, ownership.reader(case, user))


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
            built = report_cache.report(case)
            pdf = render_pdf(built, report_cache.text(case))
            report_cache.store_pdf(case, pdf, built["generated_at"])
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
    case = _case_or_404(case_id, user)

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
    case = _case_or_404(case_id, user)
    media, ext = ("text/csv", "csv") if format == "csv" else ("application/graphml+xml", "graphml")
    body = report_cache.graph(case, format)
    audit.record("case.graph_export", case_id=case_id, detail={"format": format})
    return Response(body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}-graph.{ext}"', **KEEP})


@router.get("/trace/{case_id}/letters")
def list_letters(case_id: str, user: CurrentUser) -> dict[str, Any]:
    """Which request letters this case can support: the urgent freeze letters first, then the information letters."""
    case = _case_or_404(case_id, user)
    letters = request_letters.available(case.result)
    audit.record("case.letters_list", case_id=case_id)
    return {"case_id": case_id, "letters": letters}


class NoticeDetails(BaseModel):
    """What the officer types for a bank or telecom notice (notice_letters.py).
    Sent in the body, never the URL: account and phone numbers are personal data."""

    to: str
    bank: str | None = None
    account: str | None = None
    ifsc: str | None = None
    operator: str | None = None
    phone: str | None = None
    source: str | None = None
    period_from: str | None = None
    period_to: str | None = None
    order: str | None = None
    amount: float | str | None = None


@router.post("/trace/{case_id}/notice")
def draft_notice(case_id: str, body: NoticeDetails, user: CurrentUser) -> PlainTextResponse:
    """A draft notice to a bank or a telecom operator, from the case and the officer's details.

    A draft like the exchange letters: the legal provision is a marked blank, and
    a bank hold needs the Magistrate's order and a second officer's sign-off. The
    audit row and the file name say which notice was drafted, never the numbers in it.
    """
    case = _case_or_404(case_id, user)
    details = body.model_dump(exclude={"to"})
    try:
        signed = freeze_requests.approval(case_id, body.to, user) if freeze_requests.needs_signoff(body.to) else None
        text = notice_letters.draft(case_id, case.result, body.to, details, signed)
    except notice_letters.NoticeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record("case.notice_draft", case_id=case_id, detail={"to": body.to})
    return PlainTextResponse(text, headers={
        **KEEP, "Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}-notice-{body.to}.txt"'})


@router.get("/trace/{case_id}/letter")
def get_letter(
    case_id: str,
    user: CurrentUser,
    to: str = Query(..., pattern=f"^({'|'.join(request_letters.LETTERS)})$",
                    description="exchange or tether; exchange-freeze or tether-freeze for the urgent freeze letter"),
) -> PlainTextResponse:
    """A draft request letter, filled from the case, for the officer to complete.

    A draft, never a sent document: the officer's details, the case reference
    and the legal provision are left as marked blanks, and the letter says it
    is not valid until an officer signs it on official letterhead.
    """
    case = _case_or_404(case_id, user)
    try:
        signed = freeze_requests.approval(case_id, to, user) if freeze_requests.needs_signoff(to) else None
        text = request_letters.draft(case_id, case.result, to, signed)
    except request_letters.LetterNotApplicable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record("case.letter_draft", case_id=case_id, detail={"to": to, "format": "text"})
    return PlainTextResponse(
        text,
        headers={"Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}-request-{to}.txt"'},
    )
