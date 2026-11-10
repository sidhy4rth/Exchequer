"""Officer search: find a victim's payment by its amount and time.

A payment trace starts from the victim's payment hashes (payment_intake.py),
but a victim rarely knows a hash. They know what they paid, roughly when,
and to which wallet. Given those, this module finds that transfer, and
nothing else:

* only transfers INTO the reported wallet, in the asset searched, whose
  amount equals the one entered to the asset's last decimal place, inside a
  window of at most MAX_WINDOW;
* at most MAX_MATCHES of them, each shaped like the payment it can start a
  trace with (found_by "officer_search");
* never the wallet's other transfers. A row that does not match is only
  counted, so the search cannot become a way to browse a wallet's history.

It reads with the same call payment intake makes (`get_incoming_transactions`,
TX_INTAKE_LOOKUP_LIMIT rows). A payment the search finds is then one a trace
from its hash finds too, and that trace's read is a cache hit. The cost is the
intake's: on a very busy wallet a window older than its newest incoming
transfers is not reached, and `complete` is false to say so.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any

from pydantic import BaseModel, Field, model_validator

from . import config
from .case_refs import CaseRef
from .chain_data import open_source
from .etherscan_client import normalize_address
from .input_rules import OneLine

MAX_WINDOW = timedelta(days=7)
MAX_MATCHES = 5


class PaymentSearch(BaseModel):
    chain: OneLine = Field(..., max_length=32)
    asset: OneLine = Field(..., max_length=16)
    wallet: OneLine = Field(..., max_length=128, description="The wallet the victim paid")
    # Sent as a string, every decimal place is kept; a JSON number is a float first.
    amount: Decimal = Field(..., gt=0, allow_inf_nan=False, max_digits=40)
    start: datetime = Field(..., alias="from", description="ISO 8601 with a zone, or Unix seconds")
    end: datetime = Field(..., alias="to")
    case_ref: CaseRef = None  # required of a signed-in officer (case_refs.py)

    @model_validator(mode="after")
    def _window(self) -> PaymentSearch:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Give each time with its zone, like 2026-11-09T14:30:00+05:30, or as Unix seconds.")
        if self.end <= self.start:
            raise ValueError("The window's end ('to') must come after its start ('from').")
        if self.end - self.start > MAX_WINDOW:
            raise ValueError(f"The window is at most {MAX_WINDOW.days} days.")
        return self


def decimals_of(chain: config.Chain, asset: str) -> int:
    token = chain.find_token(asset)
    return token.decimals if token else chain.native_decimals


def base_units(amount: Decimal, decimals: int) -> int | None:
    """`amount` in the asset's smallest unit; None if it is finer than that."""
    with localcontext() as ctx:
        ctx.prec = 100  # past max_digits plus any asset's decimals: never rounded
        units = amount.scaleb(decimals)
    return int(units) if units == units.to_integral_value() else None


def _shown(units: int, decimals: int) -> str:
    """The exact amount as a plain decimal: no float, no exponent."""
    with localcontext() as ctx:
        ctx.prec = 100
        return format(Decimal(units).scaleb(-decimals).normalize(), "f")


def _reached(page: tuple[bool, int | None] | None, start: int) -> bool:
    """Whether a newest-first page read back past `start`: it held the whole
    list, or its oldest record is from before."""
    if page is None:
        return False
    full, oldest = page
    return not full or (oldest is not None and oldest < start)


def _covered(client: Any, wallet: str, rows: list[Any], start: int, limit: int) -> bool:
    """Whether every incoming transfer of the window was read: one unbroken
    newest-first read that reached a transfer from before the window, or held
    the wallet's whole history. Anything less is never claimed:

    * Etherscan reads the signed list and, on the native coin, the
      contract-moved list, each cut at its own page: each must reach back.
    * NodeReal searches only recent blocks (lookback_blocks). After a deep
      search it read back from the wallet's last send, not the stretch from
      there to the lookback, where a payment not yet moved on sits."""
    if hasattr(client, "newest_page_info"):
        internal = client.internal_page_info(wallet) if hasattr(client, "internal_page_info") else None
        return _reached(client.newest_page_info(wallet), start) and (internal is None or _reached(internal, start))
    if wallet in (getattr(client, "deep_searched", None) or {}):
        return False
    if any(0 < t.timestamp < start for t in rows):
        return True
    if hasattr(client, "lookback_blocks"):
        return False
    capped = client.history_capped(wallet) if hasattr(client, "history_capped") else None
    return len(rows) < limit if capped is None else not capped


def search(chain: config.Chain, asset: str, wallet: str, units: int, start: int, end: int,
           budget: Any = None) -> dict[str, Any]:
    """The transfers into `wallet` of exactly `units` between `start` and `end`
    (Unix seconds, both included), oldest first, at most MAX_MATCHES.

    Provider errors propagate (provider_errors.public_reason says them)."""
    target = normalize_address(wallet)
    limit = config.TX_INTAKE_LOOKUP_LIMIT
    with open_source(chain, asset) as client:
        if budget is not None:
            client.budget = budget  # checked before every request the client makes
        if hasattr(client, "allow_deep_search"):  # as run_trace allows it for the reported wallet
            client.allow_deep_search(target)
        rows = client.get_incoming_transactions(target, limit=limit)
        complete = _covered(client, target, rows, start, limit)
    found = sorted((t for t in rows
                    if t.hash and t.to_address == target and not getattr(t, "is_error", False)
                    and t.value_wei == units and start <= t.timestamp <= end),
                   key=lambda t: (t.timestamp, t.hash))
    decimals = decimals_of(chain, asset)
    return {
        "matches": [{"tx_hash": t.hash, "timestamp": t.timestamp, "amount": _shown(t.value_wei, decimals),
                     "from": t.from_address, "to": t.to_address, "chain": chain.key, "asset": asset,
                     "found_by": "officer_search"} for t in found[:MAX_MATCHES]],
        "more_matches": len(found) > MAX_MATCHES,
        "scanned": len(rows),
        "complete": complete,
    }
