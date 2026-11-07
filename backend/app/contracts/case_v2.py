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
  tracing method. Pro-rata always; FIFO and LIBR when R4's flag is on.
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
    """One transfer of a payment the victim made, read from the chain by its
    hash (R1). A hash that carried several transfers into the reported wallet
    has one entry per transfer, numbered by `leg`."""

    tx_hash: str
    chain: str
    asset: str
    amount: float
    # Null unless read by the browser that traced the case (case_privacy.py).
    from_address: str | None = Field(alias="from")
    to: str
    block: int | None = None
    timestamp: int | None = None
    # "victim": the hash came with the complaint. "officer_search": the officer
    # found it by searching the recipient wallet for the amount and date.
    found_by: Literal["victim", "officer_search"] = "victim"
    # Which transfer of the hash this is, from 0; only on a hash with several.
    leg: int | None = None
    # The sender's label, when a label file names it (an exchange wallet: the
    # victim withdrew from an exchange; a router or other contract).
    payer_label: str | None = None
    # Whether the sender is the victim's own wallet given with the complaint;
    # None when no wallet was given.
    payer_is_victim: bool | None = None


class Intake(_Strict):
    mode: Literal["payment", "address"]
    payments: list[Payment] = []
    ncrp_ack: str | None = None
    # The victim's own paying wallet, when the complaint gives it.
    victim_address: str | None = None


class Attribution(_Strict):
    # deposit_label: a deposit address a checked label file names as the
    #   exchange's (never from a live explorer tag: see _attribution).
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
    """Amount of the traced funds reaching the exchange, per method (R4).

    The working for FIFO and LIBR (each wallet's figures) is in the
    ``tracing_methods`` field beside ``prorata``; see app/tracing_methods.py.
    """

    fifo: float | None = None
    prorata: float | None = None
    libr: float | None = None
    # The smallest figure available: what a letter states (request_letters
    # ._letter_amount), never above the victim's reported payments or, on a
    # follow-on, the traced share of what the swaps returned.
    conservative: float | None = None


class Transfer(_Strict):
    hash: str | None
    # Null unless read by the browser that traced the case (case_privacy.py).
    from_address: str | None = Field(alias="from")
    to: str
    value_native: float
    timestamp: int | None
    internal: bool = False
    block: int | None = None
    # Position of a token transfer's event in its transaction. None in a trace
    # by design: no provider's transfer list returns it, and a receipt per
    # transfer would double a trace's cost. Identify a transfer by hash, from,
    # to and value; verify_case (R18) may fill it from the cited receipts.
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


def _says_deposit(label: str | None) -> bool:
    from ..exchange_matcher import is_deposit_label  # here, so the contract module stays light to import
    return is_deposit_label(label)


def _attribution(result: dict[str, Any]) -> dict[str, Any] | None:
    address = result.get("exchange_address")
    if not result.get("exchange") or not address:
        return None
    match = next((m for m in result.get("matches") or [] if m.get("address") == address), {})
    wallet_type = match.get("wallet_type")
    inferred = bool(result.get("attribution_inferred")) or wallet_type == INFERRED_DEPOSIT

    live = result.get("live_tags") or {}
    live_addresses = {f.get("address") for f in live.get("found") or []}
    if inferred:
        source = "inference"
    elif address in live_addresses:
        source = "live_tag"
    else:
        source = "label_file"

    if inferred:
        kind = "deposit_inferred"
    elif wallet_type == DEPOSIT_WALLET and source == "label_file" and _says_deposit(match.get("label")):
        kind = "deposit_label"  # the same test as report.attribution_kind
    else:
        # The exchange's own wallet -- or an explorer's tag, whatever it says:
        # a tag reading "Deposit" is TronScan's word, not a checked label, so
        # it never supports a request for the customer (report.attribution_kind
        # calls it explorer_tag; the letter asks the exchange to confirm first).
        kind = "exchange_wallet"

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
    def figure(method: dict[str, Any] | None) -> float | None:
        method = method or {}
        return method.get("estimated") if method.get("status") == "estimated" else None

    methods = result.get("tracing_methods") or {}  # R4, when EXCHEQUER_TRACING_METHODS is on
    found = {"fifo": figure(methods.get("fifo")), "prorata": figure(result.get("prorata")),
             "libr": figure(methods.get("libr"))}
    figures = [v for v in found.values() if v is not None]
    return {**found, "conservative": min(figures) if figures else None}


def _transfer(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row.setdefault("block", row.pop("block_number", None))
    row.setdefault("log_index", None)
    return row
