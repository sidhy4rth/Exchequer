"""Keep secrets and complaint particulars out of the logs.

httpx logs every request at INFO, URL and all, and two of the providers carry
the key in the URL: Etherscan as `?apikey=…`, NodeReal as the last path
segment. With the root logger at INFO that put both keys in the platform's
log viewer on every request. So httpx is turned down to WARNING, and every
handler -- the root's, uvicorn's own (which do not propagate to the root)
and the access log -- carries a filter that, before anything is written:

* removes the configured secrets by value (provider keys, tokens, the demo
  code, the signing seed, the database password) and anything shaped like a
  secret (apikey=, a NodeReal URL, a bearer token, a header httpx refused);
* masks wallet addresses and transaction hashes to their first 6 and last 4
  characters: enough to match one against the case on screen;
* redacts a traceback too, and on a public host cuts it to one line -- type,
  message, and where (EXCHEQUER_LOG_TRACEBACKS=1 brings the full one back);
* drops query strings and ids from access lines: a case or job id is the key
  that reads the case. Audit lines keep the case id (audit.py) on purpose.

A thread or the process dying of an uncaught exception is logged through the
same filters rather than printed straight to stderr.
"""
from __future__ import annotations

import copy
import logging
import os
import re
import sys
import threading
import traceback
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import config

_APP_DIR = str(Path(__file__).resolve().parent)

# Secrets by shape: apikey=… in a query string (Etherscan, TronScan's v1
# style), the key segment of a NodeReal endpoint, a header value httpx
# refused (it prints the value: "Illegal header value b'<key> '"), a key or
# code written as a header, and bearer tokens.
_PATTERNS = (
    (re.compile(r"(?i)(api[_-]?key=)[^&\s\"']+"), r"\1<redacted>"),
    (re.compile(r"(nodereal\.io/v1/)[A-Za-z0-9]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(illegal header (?:value|name) b)(['\"]).*?\2"), r"\1'<redacted>'"),
    (re.compile(r"(?i)(tron-pro-api-key|x-exchequer-demo-code|x-exchequer-demo-pass)(['\"]?\s*[:=]\s*['\"]?)"
                r"[^\s'\",}]+"), r"\1\2<redacted>"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1<redacted>"),
    # An officer's session cookie (accounts.py), wherever a header is printed.
    (re.compile(r"(exchequer_session=)[^;\s\"']+"), r"\1<redacted>"),
)
# Complaint particulars: hashes first, so a hash is never read as an address.
_MASKS = (
    re.compile(r"\b0x[0-9a-fA-F]{64}\b"),
    re.compile(r"\b0x[0-9a-fA-F]{40}\b"),
    re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b"),
)
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_PROVIDER_KEYS = ("ETHERSCAN_API_KEY", "NODEREAL_API_KEY", "TRONGRID_API_KEY", "TRONSCAN_API_KEY")


def _mask(match: re.Match[str]) -> str:
    value = match.group(0)
    return f"{value[:6]}…{value[-4:]}"


@lru_cache(maxsize=4)
def _db_password(url: str) -> str | None:
    if not url:
        return None
    try:
        from sqlalchemy.engine import make_url
        return make_url(url).password
    except Exception:  # noqa: BLE001 -- an odd URL fails elsewhere, loudly
        return None


def _secret_values() -> tuple[str, ...]:
    """Every configured secret, raw and stripped, longest first. Read on each
    call, so a key set after startup is covered too. Values under 8
    characters are skipped: they would mask ordinary words."""
    values: list[str | None] = [getattr(config, name, None) for name in _PROVIDER_KEYS]
    values += [os.getenv(name) for name in _PROVIDER_KEYS]
    values += [config.HEALTH_TOKEN, config.BACKUP_TOKEN, config.BOOTSTRAP_TOKEN, config.DEMO_CODE,
               os.getenv("EXCHEQUER_SIGNING_KEY"), _db_password(config.DATABASE_URL)]
    found = {v.strip() for v in values if v and len(v.strip()) >= 8}
    return tuple(sorted(found, key=len, reverse=True))


_compiled: tuple[tuple[str, ...], re.Pattern[str] | None] = ((), None)


def _value_pattern() -> re.Pattern[str] | None:
    global _compiled
    values = _secret_values()
    if values != _compiled[0]:
        _compiled = (values, re.compile("|".join(map(re.escape, values))) if values else None)
    return _compiled[1]


def redact(text: str) -> str:
    """The text with secrets removed and addresses and hashes masked."""
    pattern = _value_pattern()
    if pattern is not None:
        text = pattern.sub("<redacted>", text)
    for shape, replacement in _PATTERNS:
        text = shape.sub(replacement, text)
    for mask in _MASKS:
        text = mask.sub(_mask, text)
    return text


def clean_path(path: str) -> str:
    """A request path fit for the access log: no query, no ids, masked addresses."""
    return redact(_UUID.sub("<id>", path.split("?", 1)[0]))


def _full_tracebacks() -> bool:
    raw = os.getenv("EXCHEQUER_LOG_TRACEBACKS", "").strip().lower()
    if raw:
        return raw in ("1", "true", "yes", "on")
    return not config.PUBLIC_HOST


def _short(filename: str) -> str:
    try:
        return str(Path(filename).resolve().relative_to(config.BACKEND_DIR))
    except ValueError:
        return Path(filename).name


def one_line(exc_info: Any) -> str:
    """'Type: message (at file:line in function)', the frame being the
    innermost one in the app's own code."""
    etype, value, tb = exc_info
    frames = traceback.extract_tb(tb) if tb is not None else []
    mine = [f for f in frames if f.filename.startswith(_APP_DIR)]
    where = ""
    if frames:
        frame = (mine or frames)[-1]
        where = f" (at {_short(frame.filename)}:{frame.lineno} in {frame.name})"
    message = redact(str(value)).replace("\n", " ")[:300]
    return f"{etype.__name__}: {message}{where}"


_formatter = logging.Formatter()


class RedactingFilter(logging.Filter):
    """Hands the handler a cleaned copy of the record: other handlers, and
    the code that logged it, keep the original."""

    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        try:
            message = record.getMessage()
        except Exception:  # a malformed record is the logger's problem, not ours
            return True
        cleaned = redact(message)
        has_exc = bool(record.exc_info and record.exc_info[0] is not None)
        if cleaned == message and not has_exc and not record.exc_text and not record.stack_info:
            return True
        out = copy.copy(record)
        out.msg, out.args = cleaned, None
        if has_exc and not _full_tracebacks():
            out.msg = f"{cleaned} [{one_line(record.exc_info)}]"
            out.exc_info = out.exc_text = out.stack_info = None
            return out
        if has_exc:
            out.exc_text = redact(_formatter.formatException(record.exc_info))
        elif record.exc_text:
            out.exc_text = redact(record.exc_text)
        if record.stack_info:
            out.stack_info = redact(record.stack_info) if _full_tracebacks() else None
        return out


class AccessPathFilter(logging.Filter):
    """uvicorn's access lines: only the path is rewritten, since its formatter
    unpacks the five arguments (client, method, path, version, status)."""

    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        args = record.args
        if not (isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str)):
            return True
        cleaned = clean_path(args[2])
        if cleaned == args[2]:
            return True
        out = copy.copy(record)
        out.args = (*args[:2], cleaned, *args[3:])
        return out


_crash_log = logging.getLogger("exchequer.crash")


def _thread_crashed(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread is not None else "?"
    _crash_log.error("Thread %s crashed", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def _process_crashed(etype: type[BaseException], value: BaseException, tb: Any) -> None:
    if issubclass(etype, KeyboardInterrupt):
        sys.__excepthook__(etype, value, tb)
        return
    _crash_log.critical("Uncaught exception", exc_info=(etype, value, tb))


def install() -> None:
    """Quiet the HTTP client loggers and filter every handler there is. Safe
    to call again: uvicorn sets up its loggers before importing the app, and
    lifespan calls this once more at startup."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    loggers = [logging.getLogger()] + [
        lg for lg in list(logging.root.manager.loggerDict.values()) if isinstance(lg, logging.Logger)]
    for logger in loggers:
        for handler in logger.handlers:
            if any(isinstance(f, (RedactingFilter, AccessPathFilter)) for f in handler.filters):
                continue
            handler.addFilter(AccessPathFilter() if logger.name == "uvicorn.access" else RedactingFilter())
    if threading.excepthook is not _thread_crashed:
        threading.excepthook = _thread_crashed
    if sys.excepthook is not _process_crashed:
        sys.excepthook = _process_crashed
