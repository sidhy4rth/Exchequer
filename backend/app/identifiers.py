"""Case identifiers: what the victim reported besides the wallet (suite feature 4, OSINT).

A fraud complaint rarely stops at a wallet. The victim was sent to a scam site,
talked to a Telegram handle or a phone number, paid a UPI ID. The officer records
each one here by hand, for the case, with who entered it and when. Later slices
look up public facts about a domain and link the same identifier across cases;
this one only records, so nothing here is a lookup result.

Each value is kept twice: as the officer typed it, and normalised (a domain in
lower case without its scheme or path, a phone number as +<country><number>, a
Telegram username without the @ or link) so the same identifier in two cases is
the same string. An identifier is a lead, never an identity: only the registrar,
the telecom or the bank can say whose it is.

Nothing is deleted. One entered by mistake is withdrawn, with a reason, and stays
in the history. Free-text fields refuse private keys and seed phrases.

Links across cases (slice 3, also_in): the same kind and normalised value, active,
in another case. Only among identifiers the viewer may read -- their browser's and
their unit's -- so another unit's cases are never revealed, not even as a count.
Two complaints naming the same UPI ID or Telegram username is a lead that they
reached the same people, not proof of it.
"""
from __future__ import annotations

import ipaddress
import json
import re
import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm.exc import StaleDataError

from . import models
from .assets import NOT_A_KEY, looks_like_secret
from .display_text import one_line

KINDS = {
    "domain": "Website domain",
    "telegram": "Telegram username",
    "phone": "Phone number",
    "upi": "UPI ID",
}
STATUSES = ("active", "withdrawn")
TEXT = {"context": (200, "where it was seen"), "notes": (2000, "the notes"), "note": (300, "why")}
ENTERED_MAX = 300
CHANGEABLE = ("context", "notes", "status", "note")
MAX_PER_OWNER, MAX_TOTAL, HISTORY_MAX = 5000, 500_000, 1000
WRITE_TRIES = 3

# Names that are never a scam site's own domain: local, private or reserved.
_RESERVED_TLDS = {"localhost", "local", "internal", "intranet", "lan", "home", "corp", "test", "example",
                  "invalid", "onion", "arpa", "localdomain"}
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TELEGRAM = re.compile(r"^[a-z][a-z0-9_]{3,31}$")
_UPI = re.compile(r"^[a-z0-9][a-z0-9._-]{1,255}@[a-z][a-z0-9]{1,63}$")


class IdentifierError(ValueError):
    """What was given is missing, malformed or not allowed; the message says which."""


class DuplicateIdentifier(IdentifierError):
    """The same identifier is already recorded for this case."""


class IdentifierConflict(RuntimeError):
    """Another write to the same identifier kept landing first; try again."""


def _now() -> str:
    return models.utc_now_iso()


def _who(user: Any) -> str:
    return getattr(user, "id", None) or "unknown"


def _text(fields: dict[str, Any], key: str) -> str:
    limit, what = TEXT[key]
    value = one_line(fields.get(key) or "").strip()
    if len(value) > limit:
        raise IdentifierError(f"{what[0].upper()}{what[1:]} is longer than {limit} characters.")
    if looks_like_secret(value):
        raise IdentifierError(NOT_A_KEY)
    return value


# -- normalising what was typed ---------------------------------------------------------------
def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def domain(raw: str) -> str:
    """A website's host name, lower case: 'https://www.Scam-Shop.in/pay?x=1' -> 'scam-shop.in'.

    Refuses IP addresses, single-label and reserved names (localhost, .local, .internal):
    the lookup slice fetches facts about this name, so it must be a public domain."""
    text = raw.strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)  # a scheme
    text = re.split(r"[/?#\\]", text, maxsplit=1)[0]  # a path, query or fragment
    if "@" in text:
        raise IdentifierError("Enter the website's domain alone, without a user name or password in it.")
    if text.startswith("[") or re.search(r":\d*$", text):
        text = re.sub(r":\d*$", "", text)  # a port
    text = text.strip(".").removeprefix("www.")
    if _is_ip(text.strip("[]")):
        raise IdentifierError("Enter the website's domain name, not an IP address.")
    try:
        text = text.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise IdentifierError("That is not a domain name a website can have.") from exc
    labels = text.split(".")
    if len(text) > 253 or len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise IdentifierError("Enter a website domain such as scam-shop.in.")
    if labels[-1] in _RESERVED_TLDS or not re.fullmatch(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}", labels[-1]):
        raise IdentifierError("That domain cannot be a public website: check its ending (.in, .com …).")
    return text


def telegram(raw: str) -> str:
    """A Telegram username, lower case, without @ or link: '@Crypto_Help' or 't.me/Crypto_Help' -> 'crypto_help'."""
    text = raw.strip()
    text = re.sub(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/", "", text, flags=re.I)
    text = text.removeprefix("@").split("?")[0].strip("/").lower()
    if not _TELEGRAM.match(text):
        raise IdentifierError("Enter the Telegram username: 5 to 32 letters, digits or _, starting with a letter.")
    return text


def phone(raw: str) -> str:
    """A phone number as +<country code><number>. A ten-digit number starting 6 to 9 is
    taken as Indian (+91); any other number needs its country code."""
    text = raw.strip()
    if re.search(r"[^\d\s()+.-]", text):
        raise IdentifierError("Enter the phone number with digits only, and a + before the country code.")
    plus = text.startswith("+") or text.startswith("00")
    digits = re.sub(r"\D", "", text)
    if text.startswith("00"):
        digits = digits[2:]
    if not plus:
        if len(digits) == 11 and digits.startswith("0") and digits[1] in "6789":
            digits = "91" + digits[1:]
        elif len(digits) == 10 and digits[0] in "6789":
            digits = "91" + digits
        elif len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
            pass
        else:
            raise IdentifierError("Enter the phone number with its country code, e.g. +91 98xxx xxxxx or +44 …")
    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        raise IdentifierError("That is not a phone number: with its country code it has 8 to 15 digits.")
    if digits.startswith("91") and (len(digits) != 12 or digits[2] not in "6789"):
        raise IdentifierError("An Indian mobile number has 10 digits after +91, starting with 6, 7, 8 or 9.")
    return "+" + digits


def upi(raw: str) -> str:
    """A UPI ID (VPA), lower case: 'Shop.Pay@okaxis'."""
    text = raw.strip().lower()
    if not _UPI.match(text):
        raise IdentifierError("Enter the UPI ID as name@bank, e.g. shop.pay@okaxis.")
    return text


NORMALISE = {"domain": domain, "telegram": telegram, "phone": phone, "upi": upi}


def normalise(kind: str, raw: Any) -> str:
    if kind not in KINDS:
        raise IdentifierError(f"Say what it is: one of {', '.join(KINDS)}.")
    text = one_line(raw or "").strip()
    if not text:
        raise IdentifierError(f"Enter the {KINDS[kind].lower()}.")
    if len(text) > ENTERED_MAX:
        raise IdentifierError(f"That is longer than {ENTERED_MAX} characters.")
    if looks_like_secret(text):
        raise IdentifierError(NOT_A_KEY)
    return NORMALISE[kind](text)


# -- the register -------------------------------------------------------------------------------
def _readable(user: Any) -> Any:
    """The identifiers `user` may read and change: their browser's, and their unit's."""
    own = models.CaseIdentifier.owner_hash == user.owner_hash
    return own if getattr(user, "unit_id", None) is None else or_(own, models.CaseIdentifier.unit_id == user.unit_id)


class _Owner:
    """A viewer that is only a browser's owner key, for callers that pass no viewer."""

    unit_id = None

    def __init__(self, owner_hash: str) -> None:
        self.owner_hash = owner_hash


def summary(r: models.CaseIdentifier) -> dict[str, Any]:
    return {
        "identifier_id": r.id, "case_id": r.case_id, "kind": r.kind, "kind_label": KINDS.get(r.kind, r.kind),
        "value": r.value, "entered": r.entered, "context": r.context, "notes": r.notes, "status": r.status,
        "created_at": r.created_at, "updated_at": r.updated_at, "history": json.loads(r.history_json or "[]"),
    }


def create(owner: str, case_id: str, fields: dict[str, Any], viewer: Any = None) -> dict[str, Any]:
    kind = str(fields.get("kind") or "")
    value = normalise(kind, fields.get("value"))
    row = {"kind": kind, "value": value, "entered": one_line(fields.get("value") or "").strip(),
           "context": _text(fields, "context"), "notes": _text(fields, "notes")}
    with models.session() as s:
        if s.scalar(select(models.Case.id).where(models.Case.id == case_id)) is None:
            raise IdentifierError("No case with that id.")
        # Only among identifiers the viewer may read: another unit's are not theirs to learn about.
        twin = s.scalars(select(models.CaseIdentifier).where(
            models.CaseIdentifier.case_id == case_id, models.CaseIdentifier.kind == kind,
            models.CaseIdentifier.value == value, _readable(viewer or _Owner(owner)))).first()
        if twin is not None:
            raise DuplicateIdentifier(f"This {KINDS[kind].lower()} is already recorded for this case.")
        count = select(func.count()).select_from(models.CaseIdentifier)
        if s.scalar(count.where(models.CaseIdentifier.owner_hash == owner)) >= MAX_PER_OWNER:
            raise IdentifierError(f"This browser already has {MAX_PER_OWNER} identifiers on record.")
        if s.scalar(count) >= MAX_TOTAL:
            raise IdentifierError("The identifier register is full on this deployment; ask its operator.")
        now = _now()
        r = models.CaseIdentifier(
            id=str(uuid.uuid4()), owner_hash=owner, case_id=case_id, status="active",
            officer_id=getattr(viewer, "officer_id", None), unit_id=getattr(viewer, "unit_id", None),
            created_at=now, updated_at=now,
            history_json=json.dumps([{"at": now, "by": _who(viewer), "action": "recorded"}]), **row,
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        return summary(r)


def _append(r: models.CaseIdentifier, entry: dict[str, Any]) -> None:
    history = json.loads(r.history_json or "[]")
    if len(history) >= HISTORY_MAX:
        raise IdentifierError(f"This identifier's history is full ({HISTORY_MAX} entries); ask the deployment's operator.")
    history.append(entry)
    r.history_json = json.dumps(history)
    r.updated_at = entry["at"]


def update(identifier_id: str, changes: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    """Change where it was seen or the notes, withdraw it, or add a note; None when the viewer has none by that id."""
    unknown = set(changes) - set(CHANGEABLE)
    if unknown:
        raise IdentifierError(f"These cannot be changed: {', '.join(sorted(unknown))}.")
    for _ in range(WRITE_TRIES):
        try:
            return _update_once(identifier_id, changes, viewer)
        except StaleDataError:
            continue
    raise IdentifierConflict(identifier_id)


def _update_once(identifier_id: str, changes: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    with models.session() as s:
        r = s.scalars(select(models.CaseIdentifier).where(
            models.CaseIdentifier.id == identifier_id, _readable(viewer))).first()
        if r is None:
            return None
        if r.status != "active" and set(changes) - {"notes", "note"}:
            raise IdentifierError(f"This identifier was already {r.status}; add a note instead.")
        clean = {key: _text(changes, key) for key in ("context", "notes") if key in changes}
        status = changes.get("status")
        if status is not None and status != r.status:
            if status != "withdrawn":
                raise IdentifierError("status can only become withdrawn.")
            clean["status"] = status
        changed = sorted(k for k, v in clean.items() if getattr(r, k) != v)
        note = _text(changes, "note") if "note" in changes else ""
        if "status" in changed and not note:
            raise IdentifierError("Say why it is withdrawn: it stays in the case's history.")
        for key in changed:
            setattr(r, key, clean[key])
        if changed or note:
            entry: dict[str, Any] = {"at": _now(), "by": _who(viewer), "action": "changed" if changed else "noted"}
            if changed:
                entry["changed"] = changed
            if note:
                entry["note"] = note
            _append(r, entry)
            s.commit()
            s.refresh(r)
        out = summary(r)
        out["changed"] = changed
        return out


def list_for(viewer: Any, case_id: str) -> list[dict[str, Any]]:
    if getattr(viewer, "owner_hash", None) is None and getattr(viewer, "unit_id", None) is None:
        return []
    with models.session() as s:
        rows = s.scalars(select(models.CaseIdentifier).where(
            models.CaseIdentifier.case_id == case_id, _readable(viewer))
            .order_by(models.CaseIdentifier.created_at)).all()
        return [summary(r) for r in rows]


def also_in(viewer: Any, case_id: str, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """For each active row of `case_id`, the other cases the viewer may read that have the same
    identifier, active: {identifier_id: [{case_id, identifier_id, recorded_at, context}, ...]}."""
    wanted = {(r["kind"], r["value"]): r["identifier_id"] for r in rows if r["status"] == "active"}
    if not wanted or (getattr(viewer, "owner_hash", None) is None and getattr(viewer, "unit_id", None) is None):
        return {}
    with models.session() as s:
        others = s.scalars(select(models.CaseIdentifier).where(
            models.CaseIdentifier.value.in_({v for _, v in wanted}),
            models.CaseIdentifier.case_id != case_id,
            models.CaseIdentifier.status == "active",
            _readable(viewer)).order_by(models.CaseIdentifier.created_at)).all()
        out: dict[str, list[dict[str, Any]]] = {}
        seen: set[tuple[str, str]] = set()
        for o in others:
            mine = wanted.get((o.kind, o.value))
            if mine is None or (mine, o.case_id) in seen:  # same value, other kind; or a case already listed
                continue
            seen.add((mine, o.case_id))
            out.setdefault(mine, []).append({"case_id": o.case_id, "identifier_id": o.id,
                                             "recorded_at": o.created_at, "context": o.context})
        return out
