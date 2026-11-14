"""Call detail records read against a case (suite feature 5, second slice).

The officer reads a CDR an Indian operator supplied in the browser
(frontend/src/components/case/cdr.js): the top contacts by count and by total
duration, each number's first and last contact, the IMEIs the number was used
in. Nothing leaves the browser until the officer saves a summary they confirmed
-- numbers and counts, never the CDR's rows -- and this module keeps it.

Saved summaries share the statement_imports table (statement_imports.py) with
source "cdr": it is the same thing, what an officer confirmed from a file read
in the browser, never the file. Statement listings leave them out.

What a saved row may claim is checked here, not taken on trust:
- a number is normalised as the identifier register does (identifiers.phone), so
  +91 98xxx, 098xxx and 9198xxx are the same number; a short code, a landline or
  an SMS sender name is kept as printed;
- "case_identifier" only when the number is an active phone identifier of this
  case the viewer may read, "other_case" only when another case the viewer may
  read has it (identifiers.also_in, the cross-case links).

A number is a lead, never a person: subscriber details come from the operator
under a lawful request. The audit log gets counts only (routes/cdr.py).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from . import identifiers, models
from .statement_imports import StatementError, _text, listing, room_for, withdrawal

SOURCE = "cdr"
KINDS = {"subject": "The CDR's own number", "number": "A number it was in touch with", "imei": "A handset (IMEI)"}
# Why a row is kept. top_contact: the officer picked it from the top contacts;
# case_identifier / other_case: checked here (see above).
REASONS = ("top_contact", "case_identifier", "other_case")
ROWS_MAX, CHECK_MAX, COUNT_MAX = 200, 50, 10_000_000

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUMBER = re.compile(r"\d{3,15}")  # as printed: a + number must be one the register holds
_SENDER = re.compile(r"[A-Z0-9]{2}-[A-Z0-9]{3,11}")  # an SMS header such as AX-ABCDEF
_IMEI = re.compile(r"\d{14,16}")  # 14 without the check digit, 15, or 16 with a software version


class CdrError(StatementError):
    """What was sent is missing, malformed or not allowed; the message says which."""


def number(raw: Any) -> str:
    """A number as the register keeps it, or as printed when it is not a phone number the register holds."""
    text = str(raw or "").strip()
    if _SENDER.fullmatch(text.upper()):
        return text.upper()
    try:
        return identifiers.phone(text)
    except identifiers.IdentifierError:
        pass
    bare = re.sub(r"[\s().-]", "", text)
    if not _NUMBER.fullmatch(bare):
        raise CdrError("a number is 3 to 15 digits, a phone number with its country code, or an SMS sender such as AX-ABCDEF.")
    return bare


def _count(raw: Any, key: str, where: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= COUNT_MAX:
        raise CdrError(f"{where}: {key} is a whole number from 0 to {COUNT_MAX}.")
    return raw


def _day(raw: Any, key: str, where: str) -> str:
    text = str(raw or "")
    try:
        if not _DATE.fullmatch(text) or not 2000 <= date.fromisoformat(text).year <= 2100:
            raise ValueError
    except ValueError as exc:
        raise CdrError(f"{where}: the {key} date is YYYY-MM-DD.") from exc
    return text


def _own_phones(viewer: Any, case_id: str) -> set[str]:
    return {r["value"] for r in identifiers.list_for(viewer, case_id) if r["kind"] == "phone" and r["status"] == "active"}


def _elsewhere(viewer: Any, case_id: str, values: set[str]) -> dict[str, list[dict[str, Any]]]:
    """For each number, the other cases the viewer may read that have it as an active phone identifier."""
    rows = [{"kind": "phone", "value": v, "identifier_id": v, "status": "active"} for v in sorted(values)]
    return identifiers.also_in(viewer, case_id, rows)


def clean_row(raw: Any, index: int) -> dict[str, Any]:
    where = f"Row {index + 1}"
    if not isinstance(raw, dict):
        raise CdrError(f"{where} is not a CDR summary row.")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise CdrError(f"{where}: say what it is: one of {', '.join(KINDS)}.")
    reasons = raw.get("reasons", [])
    if (not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons)
            or not set(reasons) <= set(REASONS) or len(set(reasons)) != len(reasons)):
        raise CdrError(f"{where}: the reasons are some of {', '.join(REASONS)}.")
    if kind == "number" and not reasons:
        raise CdrError(f"{where}: say why this number is kept.")
    if kind == "imei" and reasons:
        raise CdrError(f"{where}: a handset is kept without reasons.")
    if kind == "subject" and "top_contact" in reasons:
        raise CdrError(f"{where}: the CDR's own number is not one of its contacts.")
    value = str(raw.get("value") or "").strip()
    if kind == "imei" and not _IMEI.fullmatch(value):
        raise CdrError(f"{where}: an IMEI is 14 to 16 digits.")
    if kind != "imei":
        try:
            value = number(value)
        except CdrError as exc:
            raise CdrError(f"{where}: {exc}") from exc
    first, last = _day(raw.get("first"), "first", where), _day(raw.get("last"), "last", where)
    if first > last:
        raise CdrError(f"{where}: the first date is after the last.")
    row: dict[str, Any] = {"kind": kind, "value": value, "first": first, "last": last,
                           "reasons": [r for r in REASONS if r in reasons]}
    keys = ("events",) if kind == "imei" else ("calls", "sms", "seconds")
    for key in keys:
        row[key] = _count(raw.get(key), key, where)
    if sum(row[k] for k in keys if k != "seconds") == 0:
        raise CdrError(f"{where}: a row with no calls, messages or events is not worth keeping.")
    return row


def summary(r: models.StatementImport) -> dict[str, Any]:
    return {"import_id": r.id, "case_id": r.case_id, "title": r.title, "row_count": r.row_count,
            "rows": json.loads(r.rows_json or "[]"), "created_at": r.created_at, "created_by": r.created_by,
            "withdrawn": withdrawal(r)}


def create(owner: str, case_id: str, fields: dict[str, Any], viewer: Any) -> dict[str, Any]:
    raw_rows = fields.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise CdrError("Choose at least one row to keep.")
    if len(raw_rows) > ROWS_MAX:
        raise CdrError(f"Keep at most {ROWS_MAX} rows at a time: the summary, not the CDR.")
    rows = [clean_row(r, i) for i, r in enumerate(raw_rows)]
    if sum(r["kind"] == "subject" for r in rows) > 1:
        raise CdrError("A CDR has one number of its own.")
    claimed = {r["value"] for r in rows if {"case_identifier", "other_case"} & set(r["reasons"])}
    own = _own_phones(viewer, case_id) if claimed else set()
    elsewhere = _elsewhere(viewer, case_id, claimed) if claimed else {}
    for i, r in enumerate(rows):
        if "case_identifier" in r["reasons"] and r["value"] not in own:
            raise CdrError(f"Row {i + 1}: that number is not a phone identifier of this case.")
        if "other_case" in r["reasons"] and not elsewhere.get(r["value"]):
            raise CdrError(f"Row {i + 1}: no other case you can read has that number.")
    title = _text(fields.get("title"), "title", "The CDR")
    with models.session() as s:
        if s.scalar(select(models.Case.id).where(models.Case.id == case_id)) is None:
            raise CdrError("No case with that id.")
        try:
            room_for(s, owner, case_id, viewer, "imports")  # the statements' caps: one table
        except StatementError as exc:
            raise CdrError(str(exc)) from exc
        r = models.StatementImport(
            id=str(uuid.uuid4()), owner_hash=owner, case_id=case_id,
            officer_id=getattr(viewer, "officer_id", None), unit_id=getattr(viewer, "unit_id", None),
            source=SOURCE, currency="", title=title, row_count=len(rows), rows_json=json.dumps(rows),
            created_at=models.utc_now_iso(), created_by=getattr(viewer, "id", None) or "unknown",
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        return summary(r)


def list_for(viewer: Any, case_id: str, withdrawn: bool = False) -> list[dict[str, Any]]:
    """The CDR summaries the viewer may read; withdrawn ones only when asked for."""
    return listing(viewer, case_id, (SOURCE,), summary, withdrawn)


def check(viewer: Any, case_id: str, raw: Any) -> list[dict[str, Any]]:
    """The numbers the officer chose to check: each normalised, whether this case has it as a phone
    identifier, and the other cases the viewer may read that have it. Only these numbers are looked up."""
    if not isinstance(raw, list) or not raw or len(raw) > CHECK_MAX:
        raise CdrError(f"Choose 1 to {CHECK_MAX} numbers to check.")
    values = []
    for i, n in enumerate(raw):
        try:
            values.append(identifiers.phone(str(n or "")))
        except identifiers.IdentifierError as exc:
            raise CdrError(f"Number {i + 1} is not a phone number the identifier register can hold.") from exc
    own = _own_phones(viewer, case_id)
    elsewhere = _elsewhere(viewer, case_id, set(values))
    return [{"number": v, "on_this_case": v in own,
             "also_in": [{k: o[k] for k in ("case_id", "recorded_at", "context")} for o in elsewhere.get(v, [])]}
            for v in values]


def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """What the audit log may hold: how many rows of each kind and reason, never a number."""
    out = {kind: sum(r["kind"] == kind for r in rows) for kind in KINDS}
    out.update({reason: sum(reason in r["reasons"] for r in rows) for reason in REASONS})
    return out
