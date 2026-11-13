"""The asset register: every amount frozen or seized in a case (suite feature 9).

Finding a seed phrase is not seizing the money: anyone else with a copy can still
move it. Money is secure once it sits where the government alone controls it --
the unit's custody wallet, or held by an exchange, a bank or the token's issuer
on a request -- and a case must then say, at any moment, how much is held where,
who can move it, and what the court has ordered. That is this register.

A row records:

  holder        custody (the unit's own wallet), exchange, bank, or issuer
  asset/amount  exact decimal text: a register of seized money must not round
  held_at       the custody wallet's address, or the exchange's or bank's name
  tx_hash       the transfer into custody (required for custody)
  key_holders   who holds the keys, by name: "2 of 3: Insp. Rao, SI Iyer, SI Pal"
  seized_on     India's date of the seizure; the court's order on custody is due
                DEADLINE_DAYS later (BNSS s.497, as the Karnataka High Court read
                it in Mukesh Jain), until order_ref records it
  request_id    the freeze request that produced the hold, if any

and ends in an outcome: released to the victim, returned to its owner,
confiscated or sold, with the transaction (outcome_tx) or order (outcome_ref)
that did it. Nothing is deleted: every change is kept in the row's history,
and the audit log (routes/assets.py) records which fields changed.

The register never holds a key. A private key, seed phrase or extended key typed
into any field is refused (SECRET), and so is any 64-hex string outside the
hash fields: a raw private key looks exactly like a transaction hash, so a hash
goes only in the field made for it.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, or_, select

from . import config, models
from .display_text import one_line

IST = timezone(timedelta(hours=5, minutes=30), "IST")
DEADLINE_DAYS = 45
HOLDERS = {
    "custody": "the unit's custody wallet",
    "exchange": "held at an exchange",
    "bank": "held at a bank",
    "issuer": "frozen by the token's issuer",
}
OUTCOMES = ("released_to_victim", "returned_to_owner", "confiscated", "sold")
STATUSES = ("held", *OUTCOMES)
# What may change after a row is made. The amount, asset and seizure date never
# do: a wrong one is corrected by a note and, if need be, a new row.
CHANGEABLE = ("status", "order_ref", "outcome_ref", "outcome_tx", "key_holders", "notes")
TEXT_LIMITS = {"asset": 16, "chain": 16, "held_at": 120, "key_holders": 200, "order_ref": 200,
               "outcome_ref": 200, "notes": 2000}
HASH_FIELDS = ("tx_hash", "outcome_tx")
TX_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")
AMOUNT_MAX = Decimal("1e15")
MAX_PER_OWNER, MAX_TOTAL, HISTORY_MAX = 500, 50_000, 100

# The BIP39 English wordlist (data/bip39_english.txt, 2048 words, SHA-256
# 2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda), copied from
# python-mnemonic 0.21 (MIT, (c) 2013-2016 Pavol Rusnak). Seed phrases are drawn
# from it; an ordinary sentence almost never strings twelve of its words together.
BIP39 = frozenset((config.DATA_DIR / "bip39_english.txt").read_text(encoding="utf-8").split())
SEED_WORDS = 12

NOT_A_KEY = ("This looks like a private key or seed phrase. Never type one here: keep it offline with the "
             "officers who hold it. (A transaction hash goes in its own field.)")
SECRET = [
    re.compile(r"(?<![0-9a-fA-F])(?:0x)?[0-9a-fA-F]{64}(?![0-9a-fA-F])"),        # raw key (or a hash out of place)
    re.compile(r"\b[5KLc][1-9A-HJ-NP-Za-km-z]{50,51}\b"),                         # WIF key
    re.compile(r"\b[xyztuvXYZTUV]prv[1-9A-HJ-NP-Za-km-z]{100,}\b"),               # extended private key
]


def _seed_phrase(text: str) -> bool:
    """Twelve or more BIP39 words in a row, whatever separates them."""
    run = 0
    for word in re.findall(r"[A-Za-z]+", text):
        run = run + 1 if word.lower() in BIP39 else 0
        if run >= SEED_WORDS:
            return True
    return False


class AssetError(ValueError):
    """What was given is missing, malformed or not allowed; the message says which."""


def _now() -> str:
    return models.utc_now_iso()


def _now_ist() -> datetime:
    return datetime.now(tz=IST)


def _today() -> date:
    return _now_ist().date()


def looks_like_secret(text: str) -> bool:
    """A private key, WIF or extended key, a 64-hex string, or twelve BIP39
    words in a row: what no register field may hold (exhibits.py uses it too)."""
    return any(p.search(text) for p in SECRET) or _seed_phrase(text)


def _text(fields: dict[str, Any], key: str, what: str, required: bool = False) -> str:
    value = one_line(fields.get(key) or "").strip()
    if required and not value:
        raise AssetError(f"Enter {what}.")
    if len(value) > TEXT_LIMITS[key]:
        raise AssetError(f"{what[0].upper()}{what[1:]} is longer than {TEXT_LIMITS[key]} characters.")
    if looks_like_secret(value):
        raise AssetError(NOT_A_KEY)
    return value


def _hash(fields: dict[str, Any], key: str) -> str:
    value = str(fields.get(key) or "").strip()
    if value and not TX_RE.match(value):
        raise AssetError("Enter the transaction hash as 64 hexadecimal characters.")
    return value.lower()


def _amount(raw: Any) -> str:
    if isinstance(raw, bool):
        raise AssetError("Enter the amount as a number.")
    try:
        value = Decimal(re.sub(r"[,\s]", "", str(raw if raw is not None else "")))
    except InvalidOperation as exc:
        raise AssetError("Enter the amount as a number.") from exc
    if not value.is_finite():
        raise AssetError("Enter the amount as a number.")
    if not 0 < value < AMOUNT_MAX:
        raise AssetError("The amount must be more than zero.")
    return format(value, "f")


def _seized_on(raw: Any) -> str:
    try:
        day = date.fromisoformat(str(raw or ""))
    except ValueError as exc:
        raise AssetError("Enter the date of the seizure as YYYY-MM-DD.") from exc
    if day > _today():
        raise AssetError("The seizure date is in the future.")
    if day.year < 2009:
        raise AssetError("The seizure date is before any cryptocurrency existed.")
    return day.isoformat()


def _readable(user: Any) -> Any:
    """The rows `user` may read and change: their browser's, and their unit's."""
    own = models.SeizedAsset.owner_hash == user.owner_hash
    return own if getattr(user, "unit_id", None) is None else or_(own, models.SeizedAsset.unit_id == user.unit_id)


def _who(user: Any) -> str:
    return getattr(user, "id", None) or "unknown"


def summary(r: models.SeizedAsset) -> dict[str, Any]:
    deadline = date.fromisoformat(r.seized_on) + timedelta(days=DEADLINE_DAYS)
    due = r.status == "held" and not r.order_ref
    return {
        "asset_id": r.id, "case_id": r.case_id, "holder": r.holder, "holder_label": HOLDERS.get(r.holder, r.holder),
        "asset": r.asset, "amount": r.amount, "chain": r.chain, "held_at": r.held_at, "tx_hash": r.tx_hash,
        "key_holders": r.key_holders, "request_id": r.request_id, "seized_on": r.seized_on,
        "order_ref": r.order_ref, "status": r.status, "outcome_ref": r.outcome_ref, "outcome_tx": r.outcome_tx,
        "notes": r.notes, "created_at": r.created_at, "updated_at": r.updated_at,
        "deadline": deadline.isoformat(), "days_left": (deadline - _today()).days, "due": due,
        "history": json.loads(r.history_json or "[]"),
    }


def create(owner: str, case_id: str, fields: dict[str, Any], viewer: Any = None) -> dict[str, Any]:
    holder = str(fields.get("holder") or "")
    if holder not in HOLDERS:
        raise AssetError(f"Say where it is held: one of {', '.join(HOLDERS)}.")
    row = {
        "holder": holder,
        "asset": _text(fields, "asset", "the asset (for example USDT or INR)", required=True),
        "amount": _amount(fields.get("amount")),
        "chain": _text(fields, "chain", "the chain"),
        "held_at": _text(fields, "held_at", "where it is held"),
        "tx_hash": _hash(fields, "tx_hash"),
        "key_holders": _text(fields, "key_holders", "who holds the keys"),
        "seized_on": _seized_on(fields.get("seized_on")),
        "order_ref": _text(fields, "order_ref", "the court's order"),
        "notes": _text(fields, "notes", "the notes"),
    }
    if holder == "custody" and not row["tx_hash"]:
        raise AssetError("Money moved into the custody wallet has a transaction: enter its hash.")
    request_id = str(fields.get("request_id") or "").strip()[:36] or None
    with models.session() as s:
        if s.scalar(select(models.Case.id).where(models.Case.id == case_id)) is None:
            raise AssetError("No case with that id.")
        count = select(func.count()).select_from(models.SeizedAsset)
        if s.scalar(count.where(models.SeizedAsset.owner_hash == owner)) >= MAX_PER_OWNER:
            raise AssetError(f"This browser already has {MAX_PER_OWNER} assets on record.")
        if s.scalar(count) >= MAX_TOTAL:
            raise AssetError("The asset register is full on this deployment; ask its operator.")
        now = _now()
        r = models.SeizedAsset(
            id=str(uuid.uuid4()), owner_hash=owner, case_id=case_id, status="held", request_id=request_id,
            officer_id=getattr(viewer, "officer_id", None), unit_id=getattr(viewer, "unit_id", None),
            outcome_ref="", outcome_tx="", created_at=now, updated_at=now,
            history_json=json.dumps([{"at": now, "by": _who(viewer), "status": "held"}]), **row,
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        return summary(r)


def update(asset_id: str, changes: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    """Change a row the viewer may read; None when there is none."""
    unknown = set(changes) - set(CHANGEABLE)
    if unknown:
        raise AssetError(f"These cannot be changed: {', '.join(sorted(unknown))}.")
    with models.session() as s:
        r = s.scalars(select(models.SeizedAsset).where(models.SeizedAsset.id == asset_id, _readable(viewer))).first()
        if r is None:
            return None
        if r.status != "held" and set(changes) - {"notes"}:
            raise AssetError(f"This asset is already {r.status.replace('_', ' ')}; add a note instead.")
        clean: dict[str, str] = {}
        for key in ("order_ref", "outcome_ref", "key_holders", "notes"):
            if key in changes:
                clean[key] = _text(changes, key, key.replace("_", " "))
        if "outcome_tx" in changes:
            clean["outcome_tx"] = _hash(changes, "outcome_tx")
        status = changes.get("status")
        if status is not None and status != r.status:
            if status not in OUTCOMES:
                raise AssetError(f"status must be one of {', '.join(OUTCOMES)}.")
            if not (clean.get("outcome_tx") or clean.get("outcome_ref") or r.outcome_tx or r.outcome_ref):
                raise AssetError("Record the transaction or the order that ended the hold.")
            clean["status"] = status
        changed = sorted(k for k, v in clean.items() if getattr(r, k) != v)
        for key in changed:
            setattr(r, key, clean[key])
        if changed:
            now = _now()
            r.updated_at = now
            history = json.loads(r.history_json or "[]")
            history.append({"at": now, "by": _who(viewer), "status": r.status, "changed": changed})
            r.history_json = json.dumps(history[-HISTORY_MAX:])
            s.commit()
            s.refresh(r)
        out = summary(r)
        out["changed"] = changed
        return out


def list_for(viewer: Any, case_id: str) -> list[dict[str, Any]]:
    if getattr(viewer, "owner_hash", None) is None and getattr(viewer, "unit_id", None) is None:
        return []
    with models.session() as s:
        rows = s.scalars(select(models.SeizedAsset).where(models.SeizedAsset.case_id == case_id, _readable(viewer))
                         .order_by(models.SeizedAsset.seized_on, models.SeizedAsset.created_at)).all()
        return [summary(r) for r in rows]


def due_for(viewer: Any, within_days: int = 7) -> list[dict[str, Any]]:
    """Held rows with no court order yet whose deadline is within `within_days`
    days or already past, soonest (or most overdue) first."""
    if getattr(viewer, "owner_hash", None) is None and getattr(viewer, "unit_id", None) is None:
        return []
    latest = (_today() + timedelta(days=within_days) - timedelta(days=DEADLINE_DAYS)).isoformat()
    with models.session() as s:
        rows = s.scalars(select(models.SeizedAsset).where(
            models.SeizedAsset.status == "held", models.SeizedAsset.order_ref == "",
            models.SeizedAsset.seized_on <= latest, _readable(viewer))
            .order_by(models.SeizedAsset.seized_on).limit(100)).all()
        return [summary(r) for r in rows]
