"""Custody wallets: the unit's multisig wallets for seized crypto (suite feature 9).

Money seized on chain is safe only where the government alone controls it: a
multisig wallet whose keys sit on hardware wallets held by named officers, so
no one person can move it. This module keeps the record of each such wallet a
case uses -- never the wallet itself. The procedure an officer follows to set
one up is docs/custody-procedure.md.

A record holds:

  chain, address    the multisig wallet, checked by the chain's address validator
  scheme            as the officer entered it ("Safe on Ethereum", "Tron multi-sign permission")
  threshold         m of n: how many distinct signers must approve a movement; at least two
  signers           the n signers by name, role and unit only
  proposer_may_sign whether the scheme lets the officer who proposes a movement also approve it
  set_up_by/on      who set the wallet up, and the day
  asset_ids         the asset-register rows (assets.py) of money moved into it

The server never receives, stores or generates a private key, seed phrase,
extended key or signature: every text field refuses text shaped like one
(assets.looks_like_secret). Nothing is deleted; every change is history.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm.exc import StaleDataError

from . import config, models
from .assets import NOT_A_KEY, looks_like_secret
from .display_text import one_line

IST = timezone(timedelta(hours=5, minutes=30), "IST")
TEXT = {"scheme": (120, "the multisig scheme (for example Safe on Ethereum)"), "set_up_by": (120, "who set it up"),
        "notes": (2000, "the notes"), "name": (120, "the signer's name"), "role": (60, "the signer's role"),
        "unit": (120, "the signer's unit")}
SIGNERS_MIN, SIGNERS_MAX, LINKS_MAX = 2, 15, 50
CHANGEABLE = ("notes", "asset_ids")
MAX_PER_OWNER, MAX_TOTAL, HISTORY_MAX = 200, 20_000, 500
WRITE_TRIES = 3  # two writes to one wallet at once: the second re-reads and tries again


class CustodyError(ValueError):
    """What was given is missing, malformed or not allowed; the message says which."""


class DuplicateWallet(CustodyError):
    """This case already records that wallet."""


class CustodyConflict(RuntimeError):
    """Another write to the same record kept landing first; try again."""


def _now() -> str:
    return models.utc_now_iso()


def _today() -> date:
    return datetime.now(tz=IST).date()


def _who(user: Any) -> str:
    return getattr(user, "id", None) or "unknown"


def _text(fields: dict[str, Any], key: str, required: bool = False) -> str:
    limit, what = TEXT[key]
    value = re.sub(r"\s+", " ", one_line(fields.get(key) or "")).strip()
    if required and not value:
        raise CustodyError(f"Enter {what}.")
    if len(value) > limit:
        raise CustodyError(f"{what[0].upper()}{what[1:]} is longer than {limit} characters.")
    if looks_like_secret(value):
        raise CustodyError(NOT_A_KEY)
    return value


def _chain(raw: Any) -> config.Chain:
    chain = config.CHAINS.get(str(raw or "").strip().lower())
    if chain is None:
        raise CustodyError(f"Say which chain the wallet is on: one of {', '.join(sorted(config.CHAINS))}.")
    return chain


def _address(chain: config.Chain, raw: Any) -> str:
    value = str(raw or "").strip()
    if looks_like_secret(value):
        raise CustodyError(NOT_A_KEY)
    if not chain.validate_address(value):
        raise CustodyError(f"Enter the multisig wallet's address on {chain.name}: {chain.address_hint(value)}.")
    return value


def _threshold(raw: Any, n: int) -> int:
    if isinstance(raw, bool):
        raise CustodyError("Enter the threshold as a whole number.")
    try:
        m = int(str(raw).strip())
    except ValueError as exc:
        raise CustodyError("Enter the threshold as a whole number.") from exc
    if m < 2:
        raise CustodyError("A custody wallet needs at least two signatures: one person alone must never move seized money.")
    if m > n:
        raise CustodyError(f"The threshold ({m}) is more than the number of signers ({n}).")
    return m


def same_person(name: str) -> str:
    """How two signer names are compared: case and spacing do not make a new person."""
    return re.sub(r"\s+", " ", name).strip().casefold()


def _signers(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not SIGNERS_MIN <= len(raw) <= SIGNERS_MAX:
        raise CustodyError(f"List the wallet's signers: between {SIGNERS_MIN} and {SIGNERS_MAX}, by name.")
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise CustodyError("Give each signer as a name, a role and a unit.")
        signer = {"name": _text(item, "name", required=True), "role": _text(item, "role"), "unit": _text(item, "unit")}
        key = same_person(signer["name"])
        if key in seen:
            raise CustodyError(f"{signer['name']} is listed twice: each signer is a different person.")
        seen.add(key)
        out.append(signer)
    if looks_like_secret(" ".join(" ".join(s.values()) for s in out)):  # a seed split across the fields
        raise CustodyError(NOT_A_KEY)
    return out


def _set_up_on(raw: Any) -> str:
    try:
        day = date.fromisoformat(str(raw or ""))
    except ValueError as exc:
        raise CustodyError("Enter the day the wallet was set up as YYYY-MM-DD.") from exc
    if day > _today():
        raise CustodyError("The day the wallet was set up is in the future.")
    if day.year < 2009:
        raise CustodyError("The day the wallet was set up is before any cryptocurrency existed.")
    return day.isoformat()


def _readable(user: Any, table: Any = None) -> Any:
    """The rows `user` may read and change: their browser's, and their unit's."""
    table = table or models.CustodyWallet
    own = table.owner_hash == user.owner_hash
    return own if getattr(user, "unit_id", None) is None else or_(own, table.unit_id == user.unit_id)


def _asset_ids(s: Any, raw: Any, case_id: str, viewer: Any) -> list[str]:
    """Asset-register rows of this case the viewer may read, held in custody."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list) or len(raw) > LINKS_MAX:
        raise CustodyError(f"Link at most {LINKS_MAX} asset-register rows.")
    ids = list(dict.fromkeys(str(i).strip()[:36] for i in raw if str(i).strip()))
    if not ids:
        return []
    found = dict(s.execute(select(models.SeizedAsset.id, models.SeizedAsset.holder).where(
        models.SeizedAsset.id.in_(ids), models.SeizedAsset.case_id == case_id,
        _readable(viewer, models.SeizedAsset))).all())
    for asset_id in ids:
        if asset_id not in found:
            raise CustodyError("A linked asset is not in this case's asset register.")
        if found[asset_id] != "custody":
            raise CustodyError("Only an asset held in the custody wallet can be linked to it.")
    return ids


def summary(r: models.CustodyWallet) -> dict[str, Any]:
    signers = json.loads(r.signers_json or "[]")
    return {
        "wallet_id": r.id, "case_id": r.case_id, "chain": r.chain,
        "chain_name": config.CHAINS[r.chain].name if r.chain in config.CHAINS else r.chain,
        "address": r.address, "scheme": r.scheme, "threshold": r.threshold, "signer_count": len(signers),
        "signers": signers, "proposer_may_sign": r.proposer_may_sign, "set_up_by": r.set_up_by,
        "set_up_on": r.set_up_on, "asset_ids": json.loads(r.asset_ids_json or "[]"), "notes": r.notes,
        "created_at": r.created_at, "updated_at": r.updated_at, "history": json.loads(r.history_json or "[]"),
    }


class _Owner:
    """A viewer that is only a browser's owner key, for callers that pass no viewer."""

    unit_id = None

    def __init__(self, owner_hash: str) -> None:
        self.owner_hash = owner_hash


def create(owner: str, case_id: str, fields: dict[str, Any], viewer: Any = None) -> dict[str, Any]:
    viewer = viewer or _Owner(owner)
    chain = _chain(fields.get("chain"))
    signers = _signers(fields.get("signers"))
    row = {
        "chain": chain.key, "address": _address(chain, fields.get("address")),
        "scheme": _text(fields, "scheme", required=True), "threshold": _threshold(fields.get("threshold"), len(signers)),
        "signers_json": json.dumps(signers), "proposer_may_sign": fields.get("proposer_may_sign") is True,
        "set_up_by": _text(fields, "set_up_by", required=True), "set_up_on": _set_up_on(fields.get("set_up_on")),
        "notes": _text(fields, "notes"),
    }
    with models.session() as s:
        if s.scalar(select(models.Case.id).where(models.Case.id == case_id)) is None:
            raise CustodyError("No case with that id.")
        twin = s.scalar(select(models.CustodyWallet.id).where(
            models.CustodyWallet.case_id == case_id, models.CustodyWallet.chain == row["chain"],
            func.lower(models.CustodyWallet.address) == row["address"].lower(), _readable(viewer)))
        if twin is not None:
            raise DuplicateWallet(f"This case already records that wallet ({twin[:8]}).")
        count = select(func.count()).select_from(models.CustodyWallet)
        if s.scalar(count.where(models.CustodyWallet.owner_hash == owner)) >= MAX_PER_OWNER:
            raise CustodyError(f"This browser already has {MAX_PER_OWNER} custody wallets on record.")
        if s.scalar(count) >= MAX_TOTAL:
            raise CustodyError("The custody records are full on this deployment; ask its operator.")
        links = _asset_ids(s, fields.get("asset_ids"), case_id, viewer)
        now = _now()
        r = models.CustodyWallet(
            id=str(uuid.uuid4()), owner_hash=owner, case_id=case_id, officer_id=getattr(viewer, "officer_id", None),
            unit_id=getattr(viewer, "unit_id", None), asset_ids_json=json.dumps(links), created_at=now,
            updated_at=now, history_json=json.dumps([{"at": now, "by": _who(viewer), "action": "recorded"}]), **row,
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        return summary(r)


def retrying(write: Any, *args: Any) -> Any:
    for _ in range(WRITE_TRIES):
        try:
            return write(*args)
        except StaleDataError:
            continue
    raise CustodyConflict(args[0])


def append_history(r: Any, entry: dict[str, Any]) -> None:
    """Add to a record's history. A full one refuses: dropping old entries would lose the first."""
    history = json.loads(r.history_json or "[]")
    if len(history) >= HISTORY_MAX:
        raise CustodyError(f"This record's history is full ({HISTORY_MAX} entries); ask the deployment's operator.")
    history.append(entry)
    r.history_json = json.dumps(history)
    r.updated_at = entry["at"]


def update(wallet_id: str, changes: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    """Change the notes or the linked asset rows; None when the viewer has no wallet by that id.
    The chain, address, scheme, threshold and signers never change: a new wallet is a new record."""
    unknown = set(changes) - set(CHANGEABLE)
    if unknown:
        raise CustodyError(f"These cannot be changed: {', '.join(sorted(unknown))}.")
    return retrying(_update_once, wallet_id, changes, viewer)


def _update_once(wallet_id: str, changes: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    with models.session() as s:
        r = s.scalars(select(models.CustodyWallet).where(models.CustodyWallet.id == wallet_id, _readable(viewer))).first()
        if r is None:
            return None
        clean: dict[str, str] = {}  # column -> new value
        if "notes" in changes:
            clean["notes"] = _text(changes, "notes")
        if "asset_ids" in changes:
            clean["asset_ids_json"] = json.dumps(_asset_ids(s, changes["asset_ids"], r.case_id, viewer))
        columns = [k for k, v in clean.items() if getattr(r, k) != v]
        for key in columns:
            setattr(r, key, clean[key])
        changed = sorted(k.removesuffix("_json") for k in columns)
        if changed:
            append_history(r, {"at": _now(), "by": _who(viewer), "action": "changed", "changed": changed})
            s.commit()
            s.refresh(r)
        out = summary(r)
        out["changed"] = changed
        return out


def list_for(viewer: Any, case_id: str) -> list[dict[str, Any]]:
    if getattr(viewer, "owner_hash", None) is None and getattr(viewer, "unit_id", None) is None:
        return []
    with models.session() as s:
        rows = s.scalars(select(models.CustodyWallet).where(models.CustodyWallet.case_id == case_id, _readable(viewer))
                         .order_by(models.CustodyWallet.set_up_on, models.CustodyWallet.created_at)).all()
        return [summary(r) for r in rows]
