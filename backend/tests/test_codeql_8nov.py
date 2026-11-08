"""The three CodeQL alerts on PR #55 that were real or worth tightening (8 Nov)."""
from __future__ import annotations

import logging
import time

from fastapi.testclient import TestClient

from app import tron_tags
from app.main import app


def test_a_long_run_of_digits_in_a_tag_does_not_backtrack():
    """py/redos: (?:...|\\d+|...)* backtracked exponentially on '1111…1!'."""
    started = time.perf_counter()
    assert tron_tags.QUALIFIERS.match("-Hot 12") is not None
    assert tron_tags.QUALIFIERS.match("1" * 40 + "!") is None
    assert time.perf_counter() - started < 0.5


def test_a_path_outside_the_frontend_is_never_served():
    client = TestClient(app)
    for path in ("/../../../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/..%2f..%2fREADME.md"):
        response = client.get(path, headers={"accept": "text/html", "sec-fetch-mode": "navigate"})
        assert "root:" not in response.text and "# Exchequer" not in response.text


def test_a_cache_row_that_fails_its_check_is_logged_by_a_hash_of_its_key(tmp_path, caplog):
    """py/clear-text-logging: the key never held a credential, but the log line
    needs only something to match rows by, not the request itself."""
    from app.api_budget import ResponseCache
    from test_api_budget import _tamper

    path = tmp_path / "cache.db"
    first = ResponseCache(path=path)
    key = (("action", "txlist"), ("address", "0x" + "ab" * 20))
    first.put(key, [{"to": "0xreal"}], meta={"sha256": "ab", "retrieved_at": "t", "bytes": 3})
    first.close()
    _tamper(path, "value", '[{"to": "0xdeposit"}]')
    with caplog.at_level(logging.WARNING, logger="app.api_budget"):
        assert ResponseCache(path=path).get(key) == (False, None)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "does not match its hash" in text and "txlist" not in text and "abab" not in text
