"""Custody wallets (custody.py): the multisig wallets a case's seized crypto is held in.

    GET   /trace/{case_id}/custody   the case's custody wallets this browser or unit may read
    POST  /trace/{case_id}/custody   record one (409 when the case already records it)
    PATCH /custody/{wallet_id}       notes, and the asset-register rows moved into it
    POST  /custody/{wallet_id}/movements              propose a deposit or a release (custody_log.py)
    POST  /custody/movements/{movement_id}/{step}     approve, broadcast, confirm or cancel it

Behind config.CUSTODY_WALLETS (off by default): switched off, the list says so
and every write is refused. No route ever takes a key: the fields that could
hold one refuse it. Writes are limited per connection, like the requests log,
and audited by what happened, never by the text, which names officers.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import audit, config, custody, custody_log
from ..auth import CurrentUser
from .requests import _allow_write, _owner

router = APIRouter()
SWITCHED_OFF = "Custody wallet records are switched off on this deployment."


class Signer(BaseModel):
    name: str = Field(..., max_length=120)
    role: str = Field("", max_length=60)
    unit: str = Field("", max_length=120)


class NewWallet(BaseModel):
    chain: str = Field(..., max_length=16)
    address: str = Field(..., max_length=64)
    scheme: str = Field(..., max_length=120)
    threshold: int | str = Field(..., union_mode="left_to_right")
    signers: list[Signer] = Field(..., max_length=custody.SIGNERS_MAX)
    proposer_may_sign: bool = False
    set_up_by: str = Field(..., max_length=120)
    set_up_on: str = Field(..., max_length=10)
    asset_ids: list[str] = Field(default_factory=list, max_length=custody.LINKS_MAX)
    notes: str = Field("", max_length=2000)


class WalletChange(BaseModel):
    notes: str | None = Field(None, max_length=2000)
    asset_ids: list[str] | None = Field(None, max_length=custody.LINKS_MAX)


class NewMovement(BaseModel):
    kind: str = Field(..., max_length=16)
    asset: str = Field(..., max_length=16)
    amount: str | float = Field(..., union_mode="left_to_right")
    destination: str = Field("", max_length=64)
    order_ref: str = Field("", max_length=200)
    proposed_by: str = Field(..., max_length=120)


class Step(BaseModel):
    signer: str = Field("", max_length=120)
    tx_hash: str = Field("", max_length=80)
    reason: str = Field("", max_length=300)


def switched_on() -> None:
    if not config.CUSTODY_WALLETS:
        raise HTTPException(status_code=403, detail=SWITCHED_OFF)


def bad(exc: custody.CustodyError) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(exc, custody.DuplicateWallet) else 400, detail=str(exc))


def clash() -> HTTPException:
    return HTTPException(status_code=409, detail="Someone changed this record at the same moment. Reload and try again.")


@router.get("/trace/{case_id}/custody")
def list_wallets(case_id: str, user: CurrentUser) -> dict[str, Any]:
    if not config.CUSTODY_WALLETS:
        return {"case_id": case_id, "enabled": False, "count": 0, "wallets": []}
    rows = custody.list_for(user, case_id)
    movements = custody_log.by_wallet(user, case_id)
    for row in rows:
        row["movements"] = movements.get(row["wallet_id"], [])
    audit.record("custody.list", case_id=case_id)
    return {"case_id": case_id, "enabled": True, "count": len(rows), "wallets": rows,
            "chains": {key: chain.name for key, chain in config.CHAINS.items()}}


@router.post("/trace/{case_id}/custody", status_code=201)
def add_wallet(case_id: str, body: NewWallet, user: CurrentUser, http: Request) -> dict[str, Any]:
    switched_on()
    _allow_write(http)
    try:
        made = custody.create(_owner(user), case_id, body.model_dump(), user)
    except custody.CustodyError as exc:
        raise bad(exc) from exc
    audit.record("custody.add", case_id=case_id, detail={
        "wallet_id": made["wallet_id"], "chain": made["chain"], "threshold": made["threshold"],
        "signers": made["signer_count"]})
    return made


@router.patch("/custody/{wallet_id}")
def change_wallet(wallet_id: str, body: WalletChange, user: CurrentUser, http: Request) -> dict[str, Any]:
    switched_on()
    _allow_write(http)
    try:
        updated = custody.update(wallet_id, body.model_dump(exclude_none=True), user)
    except custody.CustodyError as exc:
        raise bad(exc) from exc
    except custody.CustodyConflict as exc:
        raise clash() from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="No custody wallet with that id that you can change.")
    changed = updated.pop("changed")
    if changed:
        audit.record("custody.update", case_id=updated["case_id"], detail={"wallet_id": wallet_id, "changed": changed})
    return updated


@router.post("/custody/{wallet_id}/movements", status_code=201)
def propose_movement(wallet_id: str, body: NewMovement, user: CurrentUser, http: Request) -> dict[str, Any]:
    switched_on()
    _allow_write(http)
    try:
        made = custody_log.propose(wallet_id, body.model_dump(), user)
    except custody.CustodyError as exc:
        raise bad(exc) from exc
    if made is None:
        raise HTTPException(status_code=404, detail="No custody wallet with that id that you can use.")
    audit.record("custody.movement.propose", case_id=made["case_id"], detail={
        "wallet_id": wallet_id, "movement_id": made["movement_id"], "kind": made["kind"]})
    return made


@router.post("/custody/movements/{movement_id}/{step}")
def movement_step(movement_id: str, step: str, body: Step, user: CurrentUser, http: Request) -> dict[str, Any]:
    switched_on()
    if step not in custody_log.STEPS:
        raise HTTPException(status_code=404, detail="No such step.")
    _allow_write(http)
    try:
        moved = custody_log.step(movement_id, step, body.model_dump(), user)
    except custody.CustodyError as exc:
        raise bad(exc) from exc
    except custody.CustodyConflict as exc:
        raise clash() from exc
    if moved is None:
        raise HTTPException(status_code=404, detail="No movement with that id that you can change.")
    audit.record(f"custody.movement.{step}", case_id=moved["case_id"], detail={
        "movement_id": movement_id, "status": moved["status"], "approvals": len(moved["approvals"])})
    return moved
