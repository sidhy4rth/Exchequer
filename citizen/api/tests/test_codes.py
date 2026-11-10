"""Tracking codes and references (_lib/codes.py): shown once, stored only as
a salted scrypt hash, compared in constant time."""
from __future__ import annotations

import hashlib
import hmac
import re

from _lib import codes


def test_a_code_is_twelve_unambiguous_characters_in_three_groups():
    seen = {codes.new_code() for _ in range(200)}
    assert len(seen) == 200
    for code in seen:
        assert re.fullmatch(r"[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}", code)
        assert not set(code) & set("01OIL")


def test_a_code_reads_the_same_typed_in_lower_case_or_without_dashes():
    assert codes.normalise(" abcd-efgh 2345 ") == "ABCDEFGH2345"
    assert codes.normalise("x" * 200) == ""  # too long to be a code: nothing to compare


def test_only_a_salted_scrypt_hash_is_kept(monkeypatch):
    calls = []
    real = hashlib.scrypt

    def spy(password, **kw):
        calls.append(kw)
        return real(password, **kw)

    monkeypatch.setattr(codes.hashlib, "scrypt", spy)
    code = codes.new_code()
    salt, digest = codes.hash_code(code)
    salt2, digest2 = codes.hash_code(code)
    assert calls and calls[0]["n"] >= 2 ** 14 and calls[0]["r"] == 8
    assert salt != salt2 and digest != digest2  # a fresh salt each time
    assert codes.normalise(code) not in digest and len(digest) == 64
    assert codes.verify(code.lower().replace("-", ""), salt, digest)
    assert not codes.verify("2222-2222-2222", salt, digest)
    assert not codes.verify("", salt, digest)


def test_the_comparison_is_constant_time(monkeypatch):
    used = []
    real = hmac.compare_digest
    monkeypatch.setattr(codes.hmac, "compare_digest", lambda a, b: used.append(1) or real(a, b))
    salt, digest = codes.hash_code("ABCD-EFGH-JKMN")
    codes.verify("ABCD-EFGH-JKMN", salt, digest)
    assert used


def test_references_and_session_tokens_are_random():
    refs = {codes.new_reference() for _ in range(100)}
    assert len(refs) == 100 and all(re.fullmatch(r"EXQ-[2-9A-HJ-NP-Z]{8}", r) for r in refs)
    token = codes.new_token()
    assert len(token) >= 40 and codes.token_hash(token) == hashlib.sha256(token.encode()).hexdigest()
