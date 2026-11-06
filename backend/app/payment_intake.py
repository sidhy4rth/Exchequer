"""Transaction-first intake (R1): start a trace from the victim's payments.

An address-only trace follows a wallet's whole recent history, so "where the
victim's money went" can turn out to be other people's money (problem M1). A
complaint names more than an address: the victim paid an amount, in a
transaction, at a time. Given those payment hashes, this module

* reads each one from the chain, as an incoming transfer to the reported
  address in the asset being traced, so a typo, the wrong chain or the wrong
  asset stops the trace with a plain error instead of a confident wrong answer;
* returns the payments as the case contract records them (contracts/case_v2.py);
* gives the moment the first payment arrived, which the pipeline uses as the
  start of the time window on the reported wallet (`seed_window`): money it
  sent before the victim paid cannot be the victim's.

It reads with the chain client's existing `get_incoming_transactions`, so no new
provider call is needed. The cost of that: a payment older than the newest
TX_INTAKE_LOOKUP_LIMIT incoming transfers of a very busy wallet is not found,
and the error says so.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# EVM and Tron transaction ids are both 32 bytes: 64 hex characters, with or
# without 0x. Checked when the request is read, so a typo is refused before
# the trace is admitted or any provider is asked.
_HASH = re.compile(r"(0x)?[0-9a-f]{64}")


class PaymentRef(BaseModel):
    """One payment named in a complaint: its hash and who found it."""

    tx_hash: str = Field(..., max_length=100)
    # "victim": the hash came with the complaint. "officer_search": the officer
    # found it by searching the reported wallet for the amount and date.
    # As stated by the requester; Exchequer does not check it.
    found_by: Literal["victim", "officer_search"] = "victim"

    @field_validator("tx_hash")
    @classmethod
    def _hash_shape(cls, value: str) -> str:
        value = value.strip().lower()
        if not _HASH.fullmatch(value):
            raise ValueError("A transaction hash is 64 hexadecimal characters, with or without 0x.")
        return value


class PaymentError(ValueError):
    """A payment that cannot start a trace: the message says why, for the officer."""


def normalize_hash(tx_hash: str) -> str:
    """Hashes compare without case or a 0x prefix (Tron's have none)."""
    value = tx_hash.strip().lower()
    return value[2:] if value.startswith("0x") else value


def resolve_payments(
    client: Any,
    address: str,
    refs: list[PaymentRef],
    *,
    chain_key: str,
    asset: str,
    limit: int,
) -> list[dict[str, Any]]:
    """The payments, read from the chain, oldest first.

    Raises PaymentError for a hash that is listed twice or is not an incoming
    `asset` transfer to `address` among its newest `limit` incoming transfers.
    """
    seen: set[str] = set()
    for ref in refs:
        key = normalize_hash(ref.tx_hash)
        if key in seen:
            raise PaymentError(f"Payment {ref.tx_hash} is listed twice.")
        seen.add(key)

    incoming = client.get_incoming_transactions(address, limit=limit)
    # One transaction can carry several transfers into the wallet (a multisend,
    # a contract paying out in pieces, several Transfer logs), so every row of
    # a hash is kept. Identical rows are not merged: within one read they are
    # separate legs, and merging would undercount two equal transfers. A row
    # with no hash can never be a named payment, so it is skipped rather than
    # matched by an empty key.
    by_hash: dict[str, list[Any]] = {}
    for tx in incoming:
        key = normalize_hash(tx.hash or "")
        if key and not getattr(tx, "is_error", False):
            by_hash.setdefault(key, []).append(tx)

    payments = []
    for ref in refs:
        rows = by_hash.get(normalize_hash(ref.tx_hash)) if normalize_hash(ref.tx_hash) else None
        if not rows:
            raise PaymentError(
                f"Payment {ref.tx_hash} is not an incoming {asset} transfer to {address} "
                f"on {chain_key} among its latest {len(incoming)} incoming transfers. "
                "Check the chain, the asset and the reported address; if they are right, the "
                "payment may be older than this wallet's recent activity."
            )
        # A fixed order, so the record does not depend on the provider's.
        rows = sorted(rows, key=lambda t: (bool(getattr(t, "internal", False)), t.from_address or "",
                                           -t.value_wei))
        for leg, tx in enumerate(rows):
            payment = {
                "tx_hash": tx.hash,
                "chain": chain_key,
                "asset": asset,
                "amount": round(tx.value_native, 6),
                "from": tx.from_address,
                "to": tx.to_address,
                "block": tx.block_number,
                "timestamp": tx.timestamp,
                "found_by": ref.found_by,
            }
            # Only on a hash with several legs, so a one-transfer payment's
            # record is what it always was.
            if len(rows) > 1:
                payment["leg"] = leg
            payments.append(payment)
    payments.sort(key=lambda p: (p["timestamp"], p["tx_hash"], p.get("leg", 0)))
    return payments


def _amount(value: float) -> str:
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def leg_warnings(payments: list[dict[str, Any]]) -> list[str]:
    """One sentence per payment hash that arrived as several transfers, for the
    case's warnings. Names no address: the senders are the complaint's
    particulars, and the case record already holds them."""
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for p in payments:
        by_hash.setdefault(p["tx_hash"], []).append(p)
    out = []
    for tx_hash, legs in by_hash.items():
        if len(legs) < 2:
            continue
        asset = legs[0]["asset"]
        senders = {p["from"] for p in legs}
        counted = "both are" if len(legs) == 2 else f"all {len(legs)} are"
        out.append(
            f"Payment {tx_hash[:6]}…{tx_hash[-4:]} arrived as {len(legs)} transfers into the reported "
            f"wallet ({' + '.join(_amount(p['amount']) for p in legs)} {asset})"
            + (f", from {len(senders)} different senders" if len(senders) > 1 else "")
            + f"; {counted} counted in the reported amount."
        )
    return out


def intake_record(payments: list[dict[str, Any]], ncrp_ack: str | None) -> dict[str, Any]:
    """The case contract's `intake` for a payment-mode trace."""
    return {"mode": "payment", "payments": payments, "ncrp_ack": ncrp_ack}


def reported_amount(payments: list[dict[str, Any]]) -> float:
    return round(sum(p["amount"] for p in payments), 6)


def window_anchor(payments: list[dict[str, Any]]) -> tuple[int, int | None]:
    """When, and in which block, the first payment arrived: the trace reads the
    wallet from here on. The block lets a busy wallet be read forward from the
    payment (graph_builder); it is None when the provider gives none (Tron's
    TRC-20 rows), and the read is then by time."""
    blocks = [p["block"] for p in payments if p.get("block")]
    return min(p["timestamp"] for p in payments), (min(blocks) if blocks else None)


def window_start(payments: list[dict[str, Any]]) -> int:
    """When the first payment arrived: the trace reads the wallet from here on."""
    return window_anchor(payments)[0]
