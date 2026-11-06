"""A case's complaint particulars go only to the browser that traced it.

The case id is the case's reference: it is printed in every letter and
report, and holding it opens the case (ownership.py). That stays true -- an
exchange or Tether that receives a letter must be able to follow its
reference back to the evidence. But a payment-mode trace (R1) also stores the
victim's NCRP acknowledgement number, the wallet each payment came from and,
when the complaint gives it, the victim's own wallet, which the letters
themselves leave as blanks for the officer. Those are returned only to the
owner's browser; any other reader gets the same case
with them empty and `redacted` naming what was withheld.

Only the response is changed, never the stored case.
"""
from __future__ import annotations

import hmac
from typing import Any

PARTICULARS = ["intake.ncrp_ack", "intake.victim_address", "intake.payments[].from"]


def is_owner(stored: str | None, caller: str | None) -> bool:
    return bool(stored and caller) and hmac.compare_digest(stored, caller)


def for_reader(result: dict[str, Any], stored_owner: str | None, caller: str | None) -> dict[str, Any]:
    """The case as `caller` may read it."""
    intake = result.get("intake")
    if not isinstance(intake, dict) or is_owner(stored_owner, caller):
        return result
    payments = [{**p, "from": None} for p in intake.get("payments") or [] if isinstance(p, dict)]
    hidden = {**intake, "ncrp_ack": None, "payments": payments}
    if "victim_address" in intake:
        hidden["victim_address"] = None
    return {**result, "intake": hidden, "redacted": PARTICULARS}
