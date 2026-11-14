"""The signing log of a custody wallet (custody.py): every movement in or out (suite feature 9).

A deposit moves seized money into the wallet; a release moves it out, and only
on the court's order, whose reference it records. Each movement goes:

  proposed  who proposed it, the amount and asset as entered, the destination
            (for a release: an address on the wallet's chain, not the wallet)
  approved  once `threshold` distinct signers of the wallet have approved it.
            The same signer never counts twice, and the proposer counts only if
            the wallet's scheme lets the proposer sign (proposer_may_sign).
  broadcast with the transaction hash, once it is sent. A release must be
            approved first; a deposit into a multisig needs no signatures.
  confirmed once the transaction is final on chain -- or cancelled, with a reason.

Each step is entered by a signed-in officer, and each approval records which
officer entered it and when. The signatures themselves happen on the signers'
hardware wallets: the server never sees a key, a seed phrase or signature data.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select

from . import config, models
from .assets import NOT_A_KEY, TX_RE, AssetError, _amount, looks_like_secret
from .custody import CustodyError, _readable, _who, append_history, retrying, same_person

KINDS = ("deposit", "release")
STEPS = {"approve": ("proposed",), "broadcast": ("proposed", "approved"), "confirm": ("broadcast",),
         "cancel": ("proposed", "approved", "broadcast")}
TEXT = {"asset": (16, "the asset (for example USDT)"), "proposed_by": (120, "who proposed it"),
        "order_ref": (200, "the court's order"), "reason": (300, "why it is cancelled"),
        "signer": (120, "which signer approved")}
MAX_PER_WALLET = 2000
SIGN_IN = "Sign in first: the signing log records which officer entered each step."


def _text(fields: dict[str, Any], key: str, required: bool = False) -> str:
    limit, what = TEXT[key]
    value = " ".join(str(fields.get(key) or "").split())
    if required and not value:
        raise CustodyError(f"Enter {what}.")
    if len(value) > limit:
        raise CustodyError(f"{what[0].upper()}{what[1:]} is longer than {limit} characters.")
    if looks_like_secret(value):
        raise CustodyError(NOT_A_KEY)
    return value


def _signed_in(viewer: Any) -> None:
    if getattr(viewer, "demo", True) or getattr(viewer, "officer_id", None) is None:
        raise CustodyError(SIGN_IN)


def _wallet(s: Any, wallet_id: str, viewer: Any) -> models.CustodyWallet | None:
    return s.scalars(select(models.CustodyWallet).where(models.CustodyWallet.id == wallet_id, _readable(viewer))).first()


def summary(m: models.CustodyMovement, threshold: int) -> dict[str, Any]:
    approvals = json.loads(m.approvals_json or "[]")
    return {
        "movement_id": m.id, "wallet_id": m.wallet_id, "case_id": m.case_id, "kind": m.kind, "asset": m.asset,
        "amount": m.amount, "destination": m.destination, "order_ref": m.order_ref, "proposed_by": m.proposed_by,
        "status": m.status, "approvals": approvals, "approvals_needed": max(threshold - len(approvals), 0),
        "threshold": threshold, "tx_hash": m.tx_hash, "created_at": m.created_at, "updated_at": m.updated_at,
        "history": json.loads(m.history_json or "[]"),
    }


def propose(wallet_id: str, fields: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    """Record a proposed deposit or release; None when the viewer has no wallet by that id."""
    _signed_in(viewer)
    kind = str(fields.get("kind") or "")
    if kind not in KINDS:
        raise CustodyError(f"Say whether it is a {' or a '.join(KINDS)}.")
    try:
        amount = _amount(fields.get("amount"))
    except AssetError as exc:
        raise CustodyError(str(exc)) from exc
    row = {"kind": kind, "asset": _text(fields, "asset", required=True), "amount": amount,
           "proposed_by": _text(fields, "proposed_by", required=True), "order_ref": _text(fields, "order_ref")}
    if kind == "release" and not row["order_ref"]:
        raise CustodyError("A release out of custody needs the court's order: enter its reference.")
    with models.session() as s:
        w = _wallet(s, wallet_id, viewer)
        if w is None:
            return None
        row["destination"] = w.address if kind == "deposit" else _destination(w, fields.get("destination"))
        count = select(func.count()).select_from(models.CustodyMovement)
        if s.scalar(count.where(models.CustodyMovement.wallet_id == w.id)) >= MAX_PER_WALLET:
            raise CustodyError(f"This wallet already has {MAX_PER_WALLET} movements on record.")
        now = models.utc_now_iso()
        m = models.CustodyMovement(
            id=str(uuid.uuid4()), wallet_id=w.id, case_id=w.case_id, status="proposed", approvals_json="[]",
            tx_hash="", created_at=now, updated_at=now,
            history_json=json.dumps([{"at": now, "by": _who(viewer), "status": "proposed"}]), **row)
        s.add(m)
        s.commit()
        s.refresh(m)
        return summary(m, w.threshold)


def _destination(w: models.CustodyWallet, raw: Any) -> str:
    value = str(raw or "").strip()
    if looks_like_secret(value):
        raise CustodyError(NOT_A_KEY)
    chain = config.CHAINS[w.chain]
    if not chain.validate_address(value):
        raise CustodyError(f"Enter where it is released to, an address on {chain.name}: {chain.address_hint(value)}.")
    if value.lower() == w.address.lower():
        raise CustodyError("A release goes out of the custody wallet, not back into it.")
    return value


def step(movement_id: str, name: str, fields: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    """Approve, broadcast, confirm or cancel a movement; None when the viewer has none by that id."""
    if name not in STEPS:
        raise CustodyError(f"The step must be one of {', '.join(STEPS)}.")
    _signed_in(viewer)
    return retrying(_step_once, movement_id, name, fields, viewer)


def _step_once(movement_id: str, name: str, fields: dict[str, Any], viewer: Any) -> dict[str, Any] | None:
    with models.session() as s:
        m = s.scalars(select(models.CustodyMovement).where(models.CustodyMovement.id == movement_id)).first()
        w = _wallet(s, m.wallet_id, viewer) if m is not None else None
        if m is None or w is None:
            return None
        if m.status not in STEPS[name]:
            raise CustodyError(f"This movement is {m.status}: it cannot be {_past(name)} now.")
        now = models.utc_now_iso()
        entry: dict[str, Any] = {"at": now, "by": _who(viewer)}
        if name == "approve":
            signer = _approver(w, m, _text(fields, "signer", required=True))
            approvals = json.loads(m.approvals_json or "[]")
            approvals.append({"signer": signer, "at": now, "recorded_by": _who(viewer)})
            m.approvals_json = json.dumps(approvals)
            entry["approved_by"] = signer
            if len(approvals) >= w.threshold:
                m.status = "approved"
        elif name == "broadcast":
            if m.kind == "release" and m.status != "approved":
                raise CustodyError(f"A release needs {w.threshold} signers' approval before it is broadcast.")
            m.tx_hash = _tx_hash(s, w, m, fields.get("tx_hash"))
            m.status = "broadcast"
        elif name == "confirm":
            m.status = "confirmed"
        else:
            entry["reason"] = _text(fields, "reason", required=True)
            m.status = "cancelled"
        entry["status"] = m.status
        append_history(m, entry)
        s.commit()
        s.refresh(m)
        return summary(m, w.threshold)


def _past(name: str) -> str:
    return {"approve": "approved", "broadcast": "broadcast", "confirm": "confirmed", "cancel": "cancelled"}[name]


def _approver(w: models.CustodyWallet, m: models.CustodyMovement, given: str) -> str:
    """The signer's name as the wallet lists it, if they may approve this movement."""
    names = {same_person(s["name"]): s["name"] for s in json.loads(w.signers_json or "[]")}
    signer = names.get(same_person(given))
    if signer is None:
        raise CustodyError("Only one of the wallet's listed signers can approve a movement.")
    if any(same_person(a["signer"]) == same_person(signer) for a in json.loads(m.approvals_json or "[]")):
        raise CustodyError(f"{signer} has already approved this movement: the same signer never counts twice.")
    if not w.proposer_may_sign and same_person(signer) == same_person(m.proposed_by):
        raise CustodyError(f"{signer} proposed this movement, and this wallet's scheme does not let a proposer sign.")
    return signer


def _tx_hash(s: Any, w: models.CustodyWallet, m: models.CustodyMovement, raw: Any) -> str:
    value = str(raw or "").strip()
    if not TX_RE.match(value):
        raise CustodyError("Enter the transaction hash as 64 hexadecimal characters.")
    value = value.lower()
    twin = s.scalar(select(models.CustodyMovement.id).where(
        models.CustodyMovement.wallet_id == w.id, models.CustodyMovement.id != m.id,
        models.CustodyMovement.tx_hash == value))
    if twin is not None:
        raise CustodyError(f"That transaction is already recorded for movement {twin[:8]} of this wallet.")
    return value


def by_wallet(viewer: Any, case_id: str) -> dict[str, list[dict[str, Any]]]:
    """The case's movements the viewer may read, grouped by wallet, oldest first."""
    if getattr(viewer, "owner_hash", None) is None and getattr(viewer, "unit_id", None) is None:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    with models.session() as s:
        rows = s.execute(select(models.CustodyMovement, models.CustodyWallet.threshold)
                         .join(models.CustodyWallet, models.CustodyWallet.id == models.CustodyMovement.wallet_id)
                         .where(models.CustodyMovement.case_id == case_id, _readable(viewer))
                         .order_by(models.CustodyMovement.created_at)).all()
        for m, threshold in rows:
            out.setdefault(m.wallet_id, []).append(summary(m, threshold))
    return out
