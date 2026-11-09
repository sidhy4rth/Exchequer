"""Webhook URLs sealed at rest.

A Slack, Discord or Google Chat webhook URL is a bearer credential: whoever
holds it can post into the channel, and a forged "sent to exchange wallet"
in a police channel names an innocent address. With EXCHEQUER_WEBHOOK_KEY
set, a stored URL is "v1:" plus a Fernet token (AES with an HMAC) under a
key derived from that secret, which lives only in the host's environment:
the database, its branches and any copy of it hold no usable URL. Without
the key, URLs are stored as given and the server says so at startup.

Changing or losing the key makes every sealed URL unreadable; the watch then
says its webhook needs re-entering, and its alerts stay in the app.
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from . import config

logger = logging.getLogger(__name__)

PREFIX = "v1:"


def _fernet() -> Fernet | None:
    secret = config.WEBHOOK_KEY
    if not secret:
        return None
    # Any secret works, Render's generated base64 included: the key is derived.
    key = base64.urlsafe_b64encode(hashlib.sha256(b"exchequer-webhook-key:" + secret.encode()).digest())
    return Fernet(key)


def sealing() -> bool:
    return bool(config.WEBHOOK_KEY)


def seal(url: str | None) -> str | None:
    """What to store for `url`: sealed when a key is set, else as given."""
    if not url:
        return None
    fernet = _fernet()
    if fernet is None:
        return url
    return PREFIX + fernet.encrypt(url.encode()).decode()


def is_sealed(stored: str | None) -> bool:
    return bool(stored) and stored.startswith(PREFIX)


def reveal(stored: str | None) -> str | None:
    """The URL a stored value stands for; None if it cannot be read (sealed
    under another key, or no key set now)."""
    if not stored:
        return None
    if not is_sealed(stored):
        return stored  # stored before sealing, or with no key set
    fernet = _fernet()
    if fernet is None:
        return None
    try:
        return fernet.decrypt(stored[len(PREFIX):].encode()).decode()
    except (InvalidToken, ValueError):
        return None


def warn_if_unsealed() -> None:
    if not sealing():
        logger.warning("EXCHEQUER_WEBHOOK_KEY is not set: watch webhook URLs are stored unsealed")
