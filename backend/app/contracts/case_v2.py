"""The case contract, version 2: what a trace result promises its readers.

A trace result is a dict produced by `pipeline.run_trace` (Lane A) and read by
the report, the letters and the evidence exports (Lane B) and by the case store
and the interface (Lane C). Version 1 was whatever the pipeline happened to
return. Version 2 adds the fields the other lanes need to build on, and nothing
in version 1 is renamed or removed, so every existing reader keeps working.

What version 2 adds (docs/contracts/case.md has the full description):

* ``contract_version``: always 2.
* ``intake``: how the trace started. ``mode`` is ``"address"`` today; R1 adds
  ``"payment"``, where the trace starts from the victim's payment transactions.
* ``reported_amount``: the victim's reported amount. None for an address-only
  trace, which follows the wallet's history, not one payment.
* ``attribution``: what the exchange address *is*, as separate facts:
  ``kind`` (a customer deposit address or the exchange's own wallet) and
  ``source`` (the label file, an inference, or a live explorer tag).
* ``estimates``: how much of the funds reached the exchange, one figure per
  tracing method. Only pro-rata exists until R4.
* ``block`` and ``log_index`` on every transfer, so each can be cited and
  re-read later.

Readers call ``read_case(result)`` and never parse the raw dict for these
fields. A case stored before this contract existed is upgraded on read.
"""
from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = 2

# The exchange matcher's wallet types (exchange_labels*.json, deposit_inference,
# tron_tags) collapse to the one question a request letter turns on: can the
# exchange tie this address to a customer account?
INFERRED_DEPOSIT = "inferred_deposit"   # app.exchange_matcher.INFERRED_DEPOSIT
DEPOSIT_WALLET = "deposit_wallet"

AttributionKind = Literal["deposit_label", "deposit_inferred", "exchange_wallet"]
AttributionSource = Literal["label_file", "inference", "live_tag"]


class _Strict(BaseModel):
    """The v2 parts are exact: an unexpected key is a bug, not a feature."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Payment(_Strict):
    """One payment the victim made, read from the chain by its hash (R1)."""

    tx_hash: str
    chain: str
    asset: str
    amount: float
    from_address: str = Field(alias="from")
    to: str
    block: int | None = None
    timestamp: int | None = None
    # "victim": the hash came with the complaint. "officer_search": the officer
    # found it by searching the recipient wallet for the amount and date.
    found_by: Literal["victim", "officer_search"] = "victim"


class Intake(_Strict):
    mode: Literal["payment", "address"]
    payments: list[Payment] = []
    ncrp_ack: str | None = None


class Attribution(_Strict):
    # deposit_label: a deposit address an explorer labels as the exchange's.
    # deposit_inferred: an unlabelled address whose outflows sweep to one
    #   exchange wallet (deposit_inference.py).
    # exchange_wallet: the exchange's own wallet (hot, cold, contract, or a
    #   label that does not say which). It belongs to no customer.
    kind: AttributionKind
    # Where the attribution came from; independent of the kind.
    source: AttributionSource
    exchange: str
    address: str
    label: str | None = None
    # The matcher's own type, kept so nothing is lost by the collapse above.
    wallet_type: str | None = None
    depth: int | None = None


class Estimates(_Strict):
    """Amount of the traced funds reaching the exchange, per method (R4)."""

    fifo: float | None = None
    prorata: float | None = None
    libr: float | None = None
    # The smallest figure available: what a letter states.
    conservative: float | None = None


class Transfer(_Strict):
    hash: str | None
    from_address: str = Field(alias="from")
    to: str
    value_native: float
    timestamp: int | None
    internal: bool = False
    block: int | None = None
    # Position of a token transfer's event in its transaction. None where the
    # provider client does not read it yet (follow-up to A-0).
    log_index: int | None = None


class CaseV2(BaseModel):
    """A trace result under contract v2.

    Only the v2 fields are typed here; every v1 field passes through untouched
    (``extra="allow"``), because v1 is not this contract's to change.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    contract_version: Literal[2]
    intake: Intake
    reported_amount: float | None
    attribution: Attribution | None
    estimates: Estimates
    transfers: list[Transfer]


# ---------------------------------------------------------------------------
# Upgrading a result to v2
# ---------------------------------------------------------------------------
def upgrade(result: dict[str, Any]) -> dict[str, Any]:
    """A copy of `result` with every v2 field present.

    Adds fields only: no v1 field is changed or removed. Safe on a result that
    is already v2 (the fields it has are kept), on a stored case from before
    the contract, and on each follow-on trace inside it.
    """
    out = copy.deepcopy(result)
    out["contract_version"] = CONTRACT_VERSION
    out.setdefault("intake", {"mode": "address", "payments": [], "ncrp_ack": None})
    out.setdefault("reported_amount", None)
    out["attribution"] = out.get("attribution") or _attribution(out)
    out.setdefault("estimates", _estimates(out))
    out["transfers"] = [_transfer(t) for t in out.get("transfers") or []]
    for follow in out.get("follow_ons") or []:
        if isinstance(follow.get("result"), dict):
            follow["result"] = upgrade(follow["result"])
    return out


def read_case(result: dict[str, Any]) -> CaseV2:
    """The way every other lane reads a trace result."""
    return CaseV2.model_validate(upgrade(result))


def _attribution(result: dict[str, Any]) -> dict[str, Any] | None:
    address = result.get("exchange_address")
    if not result.get("exchange") or not address:
        return None
    match = next((m for m in result.get("matches") or [] if m.get("address") == address), {})
    wallet_type = match.get("wallet_type")
    inferred = bool(result.get("attribution_inferred")) or wallet_type == INFERRED_DEPOSIT

    if inferred:
        kind = "deposit_inferred"
    elif wallet_type == DEPOSIT_WALLET:
        kind = "deposit_label"
    else:
        kind = "exchange_wallet"

    live = result.get("live_tags") or {}
    live_addresses = {f.get("address") for f in live.get("found") or []}
    if inferred:
        source = "inference"
    elif address in live_addresses:
        source = "live_tag"
    else:
        source = "label_file"

    return {
        "kind": kind,
        "source": source,
        "exchange": result["exchange"],
        "address": address,
        "label": result.get("exchange_label"),
        "wallet_type": wallet_type,
        "depth": match.get("depth"),
    }


def _estimates(result: dict[str, Any]) -> dict[str, Any]:
    prorata = result.get("prorata") or {}
    value = prorata.get("estimated") if prorata.get("status") == "estimated" else None
    figures = [v for v in (value,) if v is not None]
    return {
        "fifo": None,
        "prorata": value,
        "libr": None,
        "conservative": min(figures) if figures else None,
    }


def _transfer(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row.setdefault("block", row.pop("block_number", None))
    row.setdefault("log_index", None)
    return row
