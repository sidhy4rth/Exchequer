"""The draft s.63(4) certificate (certificates.py, suite feature 6, issue #112).

    POST /trace/{case_id}/certificate   a PDF draft of the Schedule's certificate for some of the
                                        case's exhibits, with the device particulars the officer typed
    POST /trace/{case_id}/report-certificate   the same for Exchequer's own report of the case: the
                                        report file itself (base64) is checked as /verify checks it,
                                        and the certificate states the SHA-256 of exactly that file

The particulars travel in the body, never the URL, go into the PDF and are kept
nowhere else. The audit row names the exhibits, never what was typed. Drafts are
limited per connection, like the other registers' writes.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import audit, certificates
from ..auth import CurrentUser
from ..pdf_verify import DETAILS, PdfBusy
from .evidence import _case_or_404
from .requests import _allow_write, _owner

router = APIRouter()


class CertificateRequest(BaseModel):
    exhibit_ids: list[str] = Field(..., max_length=certificates.EXHIBITS_MAX)
    device: str = Field("", max_length=32)
    device_other: str = Field("", max_length=120)
    make_model: str = Field("", max_length=120)
    color: str = Field("", max_length=40)
    serial: str = Field("", max_length=80)
    device_id: str = Field("", max_length=120)
    other_info: str = Field("", max_length=300)
    control: list[str] = Field(default_factory=list, max_length=len(certificates.CONTROL))


class ReportCertificateRequest(BaseModel):
    report_b64: str = Field(..., max_length=(certificates.REPORT_MAX * 4) // 3 + 4)
    file_name: str = Field("", max_length=200)
    device: str = Field("", max_length=32)
    device_other: str = Field("", max_length=120)
    make_model: str = Field("", max_length=120)
    color: str = Field("", max_length=40)
    serial: str = Field("", max_length=80)
    device_id: str = Field("", max_length=120)
    other_info: str = Field("", max_length=300)
    control: list[str] = Field(default_factory=list, max_length=len(certificates.CONTROL))


@router.post("/trace/{case_id}/certificate")
def draft_certificate(case_id: str, body: CertificateRequest, user: CurrentUser, http: Request) -> Response:
    _allow_write(http)
    _owner(user)  # no owner key: no exhibits to certify
    try:
        draft = certificates.draft(case_id, body.exhibit_ids, body.model_dump(exclude={"exhibit_ids"}), user)
    except certificates.CertificateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pdf = certificates.render_pdf(draft)
    audit.record("exhibit.certificate_draft", case_id=case_id, detail={"exhibit_ids": body.exhibit_ids})
    return Response(pdf, media_type="application/pdf", headers={
        "Cache-Control": "no-store",
        "Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}-s63-certificate-draft.pdf"'})


@router.post("/trace/{case_id}/report-certificate")
def draft_report_certificate(case_id: str, body: ReportCertificateRequest, user: CurrentUser, http: Request) -> Response:
    _allow_write(http)
    _case_or_404(case_id, user)
    details = body.model_dump(exclude={"report_b64", "file_name"})
    try:
        report = certificates.decode_report(body.report_b64)
        draft = certificates.draft_report(case_id, report, body.file_name, details, user)
    except certificates.CertificateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PdfBusy as exc:
        raise HTTPException(status_code=503, detail=DETAILS["pdf_busy"], headers={"Retry-After": "30"}) from exc
    pdf = certificates.render_pdf(draft)
    audit.record("case.report_certificate_draft", case_id=case_id, detail={"report_sha256_16": draft["records"][0]["sha256"][:16]})  # the audit log blanks 20+ characters
    return Response(pdf, media_type="application/pdf", headers={
        "Cache-Control": "no-store",
        "Content-Disposition": f'attachment; filename="exchequer-{case_id[:8]}-s63-certificate-report-draft.pdf"'})
