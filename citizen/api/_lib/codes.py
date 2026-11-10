"""Tracking codes, references and session tokens.

A tracking code is shown once, when the complaint is sent, and only a salted
scrypt hash of it is kept; it is compared in constant time. Twelve letters
and digits with none that look alike (0/O, 1/I/L): about 59 bits, which the
attempt limits (limits.py) put far out of reach of guessing.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
# n=2**14, r=8: about 16 MB and a few tens of milliseconds per check.
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32, "maxmem": 64 * 1024 * 1024}


def _random(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def new_code() -> str:
    code = _random(12)
    return f"{code[:4]}-{code[4:8]}-{code[8:]}"


def new_reference() -> str:
    return "EXQ-" + _random(8)


def normalise(code: str) -> str:
    """Upper case with spaces and dashes taken out; "" for anything not code-sized."""
    text = re.sub(r"[\s-]", "", str(code)).upper()
    return text if 0 < len(text) <= 24 else ""


def hash_code(code: str) -> tuple[str, str]:
    """(salt, hash), both hex."""
    salt = secrets.token_bytes(16)
    return salt.hex(), hashlib.scrypt(normalise(code).encode(), salt=salt, **SCRYPT).hex()


def verify(code: str, salt: str, digest: str) -> bool:
    typed = normalise(code)
    got = hashlib.scrypt(typed.encode(), salt=bytes.fromhex(salt), **SCRYPT).hex()
    return hmac.compare_digest(got, digest) and bool(typed)


def waste_time() -> None:
    """The cost of one check, for an NCRP number with no code: the answer
    then takes as long either way."""
    hashlib.scrypt(b"-", salt=b"0" * 16, **SCRYPT)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
