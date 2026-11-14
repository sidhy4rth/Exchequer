"""Bank and exchange statement rows kept with a case (suite feature 5, first slice).

The officer reads a bank statement, or a transaction statement an exchange sent,
in the browser (frontend/src/components/case/statement.js). The browser lines it
up with the case: rows whose amount and date match a payment, UPI/IMPS/NEFT/RTGS
references in the narrations, narrations that name a known exchange. Nothing
leaves the browser until the officer saves the rows they confirmed; this module
keeps those rows, never the rest of the statement.

What a saved row may claim is checked here, not taken on trust:
- an exchange is named only by one of the repository's own canonical exchange
  names (the `exchange` field of the label files, as ExchangeMatcher lists them),
  and only when the row's narration or counterparty contains it as a whole word;
- a reference is a bank reference (letters and digits) or a transaction hash;
- free text is one line and refused when it looks like a key or seed phrase.

A row is a lead for a notice to the bank or the exchange, never a finding: only
the bank can say whose account a credit came from.

Account numbers, references and narrations stay in the case record. The audit
log gets counts only (routes/statements.py).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, or_, select

from . import config, models
from .assets import NOT_A_KEY, looks_like_secret
from .display_text import one_line

SOURCES = {"bank": "Bank statement", "exchange": "Exchange statement"}
DIRECTIONS = ("debit", "credit")
# Why the officer kept a row. amount_date: its amount and date match a payment
# on the case; utr: it carries a UPI/IMPS/NEFT/RTGS reference (UTR or RRN); exchange:
# its narration names a known exchange; tx_hash: it names a transfer of the trace.
REASONS = ("amount_date", "utr", "exchange", "tx_hash")
# One import holds up to 200 rows of at most about 760 bytes each (ASCII), about
# 150 KB. Counted in imports, like the other registers (assets.py, exhibits.py),
# but far lower: an import is a hundred of their rows. Fifty per case is many
# more statements and CDRs than one case gets; a unit's cap holds however many
# browser keys its officers use; the total bounds the table at about 1.5 GB
# even if every import were full (a real one of about 20 rows is some 15 KB).
ROWS_MAX = 200
MAX_PER_CASE, MAX_PER_UNIT, MAX_PER_OWNER, MAX_TOTAL = 50, 1000, 200, 10_000
TEXT = {"title": 120, "narration": 300, "counterparty": 120}

# Canonical names that are also ordinary words in an Indian statement ("HDFC
# LIQUID FUND", a "Gemini" shop): a narration containing one says nothing about
# that exchange, so these are never matched from text.
ORDINARY_WORDS = frozenset({"liquid", "bullish", "gemini", "uphold"})

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?")
_CURRENCY = re.compile(r"[A-Z][A-Z0-9]{1,11}")
_TX_HASH = re.compile(r"(0x)?[0-9a-fA-F]{64}")
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9/._-]{0,39}")


class StatementError(ValueError):
    """What was sent is missing, malformed or not allowed; the message says which."""


def exchange_names() -> list[str]:
    """Every canonical exchange name in the label files, on every chain, less the
    ordinary words: the only names a narration may be matched against."""
    from .exchange_matcher import get_matcher  # loads the label files; only when asked

    names: set[str] = set()
    for key in config.CHAINS:
        names.update(get_matcher(key).exchanges)
    return sorted((n for n in names if n.lower() not in ORDINARY_WORDS), key=str.lower)


def names_in(text: str, names: list[str]) -> list[str]:
    """The names that `text` contains as whole words, ignoring case."""
    return [n for n in names
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", text, re.IGNORECASE)]


def _text(value: Any, key: str, where: str) -> str:
    text = one_line(value or "").strip()
    if len(text) > TEXT[key]:
        raise StatementError(f"{where}: the {key} is longer than {TEXT[key]} characters.")
    if looks_like_secret(text):
        raise StatementError(f"{where}: {NOT_A_KEY}")
    return text


def _amount(raw: Any, where: str) -> str:
    if isinstance(raw, bool) or raw is None:
        raise StatementError(f"{where}: enter the amount as a number.")
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise StatementError(f"{where}: enter the amount as a number.") from exc
    if not value.is_finite() or value <= 0 or value >= Decimal("1e15") or value != value.quantize(Decimal("1e-8")):
        raise StatementError(f"{where}: the amount must be above zero, with at most 8 decimal places.")
    return format(value.normalize(), "f")


def _reference(raw: Any, where: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if _TX_HASH.fullmatch(text):
        return text.lower()
    if not _REFERENCE.fullmatch(text) or looks_like_secret(text):
        raise StatementError(f"{where}: a reference is up to 40 letters and digits, or a transaction hash.")
    return text


def clean_row(raw: Any, index: int, names: list[str]) -> dict[str, Any]:
    where = f"Row {index + 1}"
    if not isinstance(raw, dict):
        raise StatementError(f"{where} is not a statement row.")
    day = str(raw.get("date") or "")
    try:
        if not _DATE.fullmatch(day) or not 2000 <= date.fromisoformat(day).year <= 2100:
            raise ValueError
    except ValueError as exc:
        raise StatementError(f"{where}: the date is YYYY-MM-DD.") from exc
    at = str(raw.get("time") or "")
    if at and not _TIME.fullmatch(at):
        raise StatementError(f"{where}: the time is HH:MM.")
    if raw.get("direction") not in DIRECTIONS:
        raise StatementError(f"{where}: say whether it is a debit or a credit.")
    reasons = raw.get("reasons")
    if (not isinstance(reasons, list) or not reasons or not all(isinstance(r, str) for r in reasons)
            or not set(reasons) <= set(REASONS) or len(set(reasons)) != len(reasons)):
        raise StatementError(f"{where}: say why it is kept: {', '.join(REASONS)}.")
    row = {
        "date": day, "time": at, "direction": raw["direction"], "amount": _amount(raw.get("amount"), where),
        "reference": _reference(raw.get("reference"), where),
        "narration": _text(raw.get("narration"), "narration", where),
        "counterparty": _text(raw.get("counterparty"), "counterparty", where),
        "reasons": [r for r in REASONS if r in reasons], "exchange": "",
    }
    if "exchange" in reasons:
        claimed = str(raw.get("exchange") or "")
        found = names_in(f"{row['narration']} {row['counterparty']}", names)
        if claimed not in found:
            raise StatementError(f"{where}: the exchange must be a known exchange's name, as its narration "
                                 "or counterparty gives it.")
        row["exchange"] = claimed
    if "utr" in reasons and not row["reference"]:
        raise StatementError(f"{where}: kept for its UTR, but it has no reference.")
    if "tx_hash" in reasons and not _TX_HASH.fullmatch(row["reference"]):
        raise StatementError(f"{where}: kept for a transaction hash, but its reference is not one.")
    return row


def _readable(user: Any) -> Any:
    """The imports `user` may read: their browser's, and their unit's."""
    own = models.StatementImport.owner_hash == user.owner_hash
    unit = getattr(user, "unit_id", None)
    return own if unit is None else or_(own, models.StatementImport.unit_id == unit)


def summary(r: models.StatementImport) -> dict[str, Any]:
    return {"import_id": r.id, "case_id": r.case_id, "source": r.source, "source_label": SOURCES.get(r.source, r.source),
            "currency": r.currency, "title": r.title, "row_count": r.row_count, "rows": json.loads(r.rows_json or "[]"),
            "created_at": r.created_at, "created_by": r.created_by}


def room_for(s: Any, owner: str, case_id: str, viewer: Any, what: str) -> None:
    """Refuse a new import (a statement's or a CDR's: they share the table) once the
    case, the unit, the browser or the deployment holds its cap."""
    count = select(func.count()).select_from(models.StatementImport)
    if s.scalar(count.where(models.StatementImport.case_id == case_id)) >= MAX_PER_CASE:
        raise StatementError(f"This case already has {MAX_PER_CASE} imports on record.")
    unit = getattr(viewer, "unit_id", None)
    if unit is not None and s.scalar(count.where(models.StatementImport.unit_id == unit)) >= MAX_PER_UNIT:
        raise StatementError(f"Your unit already has {MAX_PER_UNIT} imports on record; ask the operator.")
    if s.scalar(count.where(models.StatementImport.owner_hash == owner)) >= MAX_PER_OWNER:
        raise StatementError(f"This browser already has {MAX_PER_OWNER} {what} on record.")
    if s.scalar(count) >= MAX_TOTAL:
        raise StatementError("The import records are full on this deployment; ask its operator.")


def create(owner: str, case_id: str, fields: dict[str, Any], viewer: Any) -> dict[str, Any]:
    source = fields.get("source")
    if source not in SOURCES:
        raise StatementError(f"Say what the statement is: one of {', '.join(SOURCES)}.")
    currency = str(fields.get("currency") or "").strip().upper()
    if not _CURRENCY.fullmatch(currency):
        raise StatementError("Say the statement's currency, such as INR or USDT.")
    raw_rows = fields.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise StatementError("Choose at least one row to keep.")
    if len(raw_rows) > ROWS_MAX:
        raise StatementError(f"Keep at most {ROWS_MAX} rows at a time: the matches, not the statement.")
    names = exchange_names() if any(isinstance(r, dict) and isinstance(r.get("reasons"), list)
                                    and "exchange" in r["reasons"] for r in raw_rows) else []
    rows = [clean_row(r, i, names) for i, r in enumerate(raw_rows)]
    title = _text(fields.get("title"), "title", "The statement")
    with models.session() as s:
        if s.scalar(select(models.Case.id).where(models.Case.id == case_id)) is None:
            raise StatementError("No case with that id.")
        room_for(s, owner, case_id, viewer, "statement imports")
        r = models.StatementImport(
            id=str(uuid.uuid4()), owner_hash=owner, case_id=case_id,
            officer_id=getattr(viewer, "officer_id", None), unit_id=getattr(viewer, "unit_id", None),
            source=source, currency=currency, title=title, row_count=len(rows), rows_json=json.dumps(rows),
            created_at=models.utc_now_iso(), created_by=getattr(viewer, "id", None) or "unknown",
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        return summary(r)


def list_for(viewer: Any, case_id: str) -> list[dict[str, Any]]:
    if getattr(viewer, "owner_hash", None) is None and getattr(viewer, "unit_id", None) is None:
        return []
    with models.session() as s:
        rows = s.scalars(select(models.StatementImport).where(
            models.StatementImport.case_id == case_id, models.StatementImport.source.in_(SOURCES), _readable(viewer))
            .order_by(models.StatementImport.created_at)).all()  # a CDR's summary (cdr_imports.py) is listed there
        return [summary(r) for r in rows]


def reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """How many saved rows were kept for each reason: what the audit log may hold."""
    return {reason: sum(reason in r["reasons"] for r in rows) for reason in REASONS}
