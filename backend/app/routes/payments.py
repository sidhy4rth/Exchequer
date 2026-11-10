"""POST /payments/search: find the victim's payment by its amount and time
(app/payment_search.py), for a complaint that came without a hash."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .. import api_budget, audit, case_refs, log_safety, payment_search, pipeline
from ..api_budget import BudgetSpent, TraceStopped
from ..auth import CurrentUser
from ..chain_data import ProviderNotConfiguredError
from ..etherscan_client import EtherscanConfigError, EtherscanError, EtherscanRateLimitError, ProviderQuotaError
from ..provider_errors import public_reason
from . import cases

logger = logging.getLogger(__name__)
router = APIRouter()

# One read of one wallet: far less than a trace's clock.
SEARCH_SECONDS = 60


def _failed(exc: Exception) -> HTTPException:
    """A read that failed, answered as run_trace answers it: a fixed sentence,
    never the provider's own text (provider_errors.py)."""
    # In run_trace's order, narrowest first: a spent quota (ProviderQuotaError) is
    # also a rate limit, and AllowanceSpent is both; waiting seconds helps neither.
    if isinstance(exc, BudgetSpent):
        status = 429 if exc.scope == "client" else 503
    elif isinstance(exc, TraceStopped | ProviderQuotaError | ProviderNotConfiguredError | EtherscanConfigError):
        status = 503
    elif isinstance(exc, EtherscanRateLimitError):
        status = 429
    else:
        status = 502
    logger.warning("Payment search failed: %s", log_safety.redact(str(exc)))
    return HTTPException(status_code=status,
                         detail=f"The wallet could not be searched: {public_reason(exc)}. Try again later.")


@router.post("/payments/search")
def search_payments(body: payment_search.PaymentSearch, http: Request, user: CurrentUser) -> dict[str, Any]:
    """Transfers into `wallet` of exactly `amount` between `from` and `to`.

    Gated like POST /trace: the demo code (access.py), the same hourly
    allowance and running slots (cases.admit), and an audit line. The chain,
    wallet, asset and amount are checked before it is admitted, so a typo
    costs nothing."""
    ref = case_refs.required(user, body.case_ref, "payment search")
    chain, wallet = pipeline.check_request(
        pipeline.TraceRequest(address=body.wallet, chain=body.chain, asset=body.asset))
    asset = (body.asset.strip() or chain.native_symbol).upper()  # as check_request reads an empty one
    decimals = payment_search.decimals_of(chain, asset)
    units = payment_search.base_units(body.amount, decimals)
    if units is None:
        raise HTTPException(status_code=400, detail=f"{asset} on {chain.name} has {decimals} decimal places; "
                                                    "the amount has more.")
    slot = cases.admit(http, user)
    try:
        with api_budget.using(api_budget.TraceBudget.for_request(SEARCH_SECONDS, client=slot)) as budget:
            result = payment_search.search(chain, asset, wallet, units, int(body.start.timestamp()),
                                           int(body.end.timestamp()), budget=budget)
    except (TraceStopped, EtherscanError) as exc:
        raise _failed(exc) from exc
    finally:
        cases.release(slot)
    # What kind of search, never whose: no wallet, amount or time.
    audit.record("payment.search", detail={"chain": chain.key, "asset": asset, "matches": len(result["matches"]),
                                           "scanned": result["scanned"], "complete": result["complete"],
                                           **({"case_ref": case_refs.mask(ref)} if ref else {})})
    return result
