"""What a case may say about a failed provider read: one fixed sentence per kind.

Exception text can quote a provider's response body -- an HTML error page, the
state of a quota or a key -- and a case is stored, shown and signed. So a case
carries only `public_reason(exc)`; the detail goes to the log, redacted
(log_safety). The seed's own failure is answered the same way in pipeline.py.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from .api_budget import TraceStopped
from .etherscan_client import (EtherscanError, EtherscanRateLimitError, ProviderQuotaError, ProviderResponseError,
                               ProviderUnavailableError)

logger = logging.getLogger(__name__)


def public_reason(exc: BaseException) -> str:
    if isinstance(exc, TraceStopped):
        return exc.reason
    if isinstance(exc, ProviderQuotaError):
        return "the provider's quota is used up"
    if isinstance(exc, EtherscanRateLimitError):
        return "the provider kept refusing requests"
    if isinstance(exc, ProviderResponseError):
        return "the provider sent a response Exchequer could not read"
    if isinstance(exc, EtherscanError):
        return "the provider reported an error"
    return "an unexpected error"


def error_name(exc: BaseException) -> str:
    """The class name to show for `exc` where one is shown (the warm-up's
    status): a client out of retries raises its provider's
    ProviderUnavailableError subclass, shown as the provider's own error
    (EtherscanError, NoderealError, TronError) as it was before that subclass
    existed. Anything else is its own name."""
    if isinstance(exc, ProviderUnavailableError):
        for cls in type(exc).__mro__[1:]:
            if issubclass(cls, EtherscanError) and not issubclass(cls, ProviderUnavailableError):
                return cls.__name__
    return type(exc).__name__


def failure_kind(exc: BaseException) -> str:
    """What kind of failure `exc` is, as a case records it (`prorata.read_failure`):
    "rate_limit" (the provider kept refusing), "no_answer" (server errors or no
    response, every retry), "quota", "stopped" (the case's own time or request
    limit), "bad_response", "provider_error" or "error". In public_reason's order."""
    if isinstance(exc, TraceStopped):
        return "stopped"
    if isinstance(exc, ProviderQuotaError):
        return "quota"
    if isinstance(exc, EtherscanRateLimitError):
        return "rate_limit"
    if isinstance(exc, ProviderUnavailableError):
        return "rate_limit" if exc.rate_limited else "no_answer"
    if isinstance(exc, ProviderResponseError):
        return "bad_response"
    if isinstance(exc, EtherscanError):
        return "provider_error"
    return "error"


# One more read of a window that failed for a passing reason, after this
# pause. The client has already retried with backoff (about 7.5 s on
# Etherscan); the re-read is made only while the case has the pause and this
# much more to spare, for the read's own retries and timeouts, so it never
# runs the case into its deadline.
REREAD_PAUSE_SECONDS = 10.0
REREAD_HEADROOM_SECONDS = 30.0


def read_again_once(read: Callable[..., Any], budget: Any = None) -> Callable[..., Any]:
    """`read`, made once more after REREAD_PAUSE_SECONDS when it fails with a
    rate limit or no answer (failure_kind). Any other failure, or a second
    one, is raised as it came; a read that succeeds first time is returned
    untouched."""
    def again(*args: Any) -> Any:
        pause = REREAD_PAUSE_SECONDS
        try:
            return read(*args)
        except Exception as exc:
            if failure_kind(exc) not in ("rate_limit", "no_answer"):
                raise
            if budget is not None and budget.remaining() < pause + REREAD_HEADROOM_SECONDS:
                raise
            logger.warning("Window read failed (%s); reading it once more in %.0fs", failure_kind(exc), pause)
            if budget is not None:
                budget.sleep(pause)  # never past the case's deadline
            else:
                time.sleep(pause)
        return read(*args)
    return again
