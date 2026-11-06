"""What a case may say about a failed provider read: one fixed sentence per kind.

Exception text can quote a provider's response body -- an HTML error page, the
state of a quota or a key -- and a case is stored, shown and signed. So a case
carries only `public_reason(exc)`; the detail goes to the log, redacted
(log_safety). The seed's own failure is answered the same way in pipeline.py.
"""
from __future__ import annotations

from .api_budget import TraceStopped
from .etherscan_client import EtherscanError, EtherscanRateLimitError, ProviderQuotaError


def public_reason(exc: BaseException) -> str:
    if isinstance(exc, TraceStopped):
        return exc.reason
    if isinstance(exc, ProviderQuotaError):
        return "the provider's quota is used up"
    if isinstance(exc, EtherscanRateLimitError):
        return "the provider kept refusing requests"
    if isinstance(exc, EtherscanError):
        return "the provider reported an error"
    return "an unexpected error"
