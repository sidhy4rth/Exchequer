"""Keep API keys out of the logs.

httpx logs every request at INFO, URL and all, and two of the providers carry
the key in the URL: Etherscan as `?apikey=…`, NodeReal as the last path
segment. With the root logger at INFO that put both keys in the platform's
log viewer on every request. Two layers, so either alone is enough: httpx is
turned down to WARNING, and every handler scrubs anything that still looks
like a key before it is written.
"""
from __future__ import annotations

import logging
import re

# apikey=… in a query string (Etherscan, TronScan's v1 style), and the key
# segment of a NodeReal endpoint (https://bsc-mainnet.nodereal.io/v1/<key>).
_PATTERNS = (
    (re.compile(r"(?i)(api[_-]?key=)[^&\s\"']+"), r"\1<redacted>"),
    (re.compile(r"(nodereal\.io/v1/)[A-Za-z0-9]+"), r"\1<redacted>"),
)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Rewrites a record's final message with the keys removed."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a malformed record is the logger's problem, not ours
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        return True


def install() -> None:
    """Quiet the HTTP client loggers and scrub every root handler."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
