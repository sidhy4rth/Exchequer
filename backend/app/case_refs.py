"""The case an officer's live work is for: an FIR, NCRP or GD number.

A signed-in officer starts a live trace, a batch, a watch, a payment search
or a recheck only under a case reference, so every provider call they spend
answers to a case (pack misuse: "stalking or profiling a wallet"). Demo
callers are unchanged: they need none, and one they send is dropped, since a
police reference must not be lent to an anonymous trace.

It is kept like the NCRP number: in the body of the request, never in a URL;
with the case in `intake.case_ref`, withheld from every other reader
(case_privacy.py); never in a log line. The audit trail gets it masked.
"""
from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import HTTPException
from pydantic import BeforeValidator

from . import accounts, ownership, rate_limit

_SHAPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 /.\-]{2,39}")
BAD = ("A case reference is the FIR, NCRP or GD number: 3 to 40 letters, digits, spaces, "
       "/ . or -, with at least one digit.")


def shape(value: Any) -> str | None:
    """The reference as entered, its spacing tidied; None when blank."""
    if value is None:
        return None
    if not isinstance(value, str) or "\n" in value:
        raise ValueError(BAD)
    value = " ".join(value.split())
    if not value:
        return None
    if not _SHAPE.fullmatch(value) or not any(c.isdigit() for c in value):
        raise ValueError(BAD)
    return value


def of_row(value: Any) -> str | None:
    """A batch row's own reference (its reference column), when it is one."""
    try:
        return shape(value)
    except ValueError:
        return None


# What a request model's field is annotated with: `case_ref: CaseRef = None`.
CaseRef = Annotated[str | None, BeforeValidator(shape)]


def mask(ref: str | None) -> str | None:
    """What the audit trail keeps: the last three characters, at a fixed length."""
    if not ref:
        return None
    return "****" + (ref[-3:] if len(ref) >= 8 else "")


def required(user: Any, ref: str | None, action: str = "live trace") -> str | None:
    """The reference this caller's action runs under: None for a demo caller,
    else `ref`, refused with a 400 when an officer gave none."""
    if user.demo:
        return None
    if not ref:
        raise HTTPException(status_code=400, detail=(
            f"Enter the case reference (the FIR, NCRP or GD number) this {action} is for. "
            "It is kept with the case, never in links or logs."))
    return ref


def stored(result: dict[str, Any] | None) -> str | None:
    """The reference a stored case was traced under, if any."""
    intake = (result or {}).get("intake")
    return intake.get("case_ref") if isinstance(intake, dict) else None


def known(case: Any, user: Any) -> str | None:
    """The stored case's reference when `user` reads that case in full; else
    None, so an officer never spends under a reference withheld from them."""
    if case is None or user.demo or ownership.reader(case, user) != case.owner_hash:
        return None
    return stored(case.result)


def spender(user: Any, kind: str) -> rate_limit.OfficerCharge | None:
    """The signed-in officer's own allowance for `kind`, as their unit sets it
    (accounts.unit_limits) or the defaults; None for a demo caller."""
    if user.demo or user.officer_id is None:
        return None
    hour, day = rate_limit.officer_caps(kind, accounts.unit_limits(user.unit_id) if user.unit_id else None)
    return rate_limit.OfficerCharge(f"officer-{user.officer_id}", kind, hour, day)


def refused(officer: rate_limit.OfficerCharge | None, refusal: tuple[float, str], cost: int = 1) -> None:
    """Raise the 429 for an officer's own limit; return for any other refusal."""
    wait, who = refusal
    if officer is not None and who in ("hour", "day"):
        raise HTTPException(status_code=429, headers={"Retry-After": str(int(wait))},
                            detail=rate_limit.officer_refusal(officer, who, wait, cost))
