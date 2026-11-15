"""Telegram public-page lookups (app/telegram_lookup.py): suite feature 4, OSINT slice 4.

For a Telegram username on a case's register: the one public page https://t.me/<username>,
and only what that page shows, kept with its time and SHA-256.

No test touches the network (CLAUDE.md rule 8): _get is replaced, or httpx runs on a
MockTransport or on a fake network (tests/test_http_deadline.py). The pages in tests/fixtures/osint/telegram/ are SYNTHETIC: hand-written
with t.me's class names, and made-up names, numbers and descriptions.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from app import telegram_lookup
from app.domain_lookup import LookupError_
from app.identifiers import IdentifierError
from tests.test_http_deadline import RESPONSE, SlowNetwork

PAGES = Path(__file__).parent / "fixtures" / "osint" / "telegram"


def page(name: str) -> bytes:
    return (PAGES / f"{name}.html").read_bytes()


@pytest.fixture
def served(monkeypatch):
    """t.me answers with one synthetic page; every URL asked for is listed."""
    calls: list[str] = []
    answer = {"status": 200, "body": page("channel")}

    def fake(url):
        calls.append(url)
        return answer["status"], answer["body"]

    monkeypatch.setattr(telegram_lookup, "_get", fake)
    return calls, answer


# -- what the page shows ---------------------------------------------------------------------------
def test_a_channel_page_gives_its_title_type_count_and_description():
    shown = telegram_lookup.parse_page(page("channel"))
    assert shown == {"exists": True, "title": "Sample Signals & Tips", "type": "channel", "count_text": "12 345 subscribers",
                     "description": "Made-up channel for tests. Daily offers here.", "badges": []}


def test_a_verified_badge_is_read_and_kept_out_of_the_title():
    shown = telegram_lookup.parse_page(page("verified_channel"))
    assert shown["title"] == "Sample Official News" and shown["badges"] == ["verified"] and shown["type"] == "channel"


def test_scam_and_fake_badges_and_a_group_member_line():
    shown = telegram_lookup.parse_page(page("scam_group"))
    assert shown["title"] == "Sample Recovery Desk" and shown["badges"] == ["fake", "scam"]
    assert shown["type"] == "group" and shown["count_text"] == "2 345 members, 67 online"


def test_a_bot_page_keeps_its_users_line_but_not_its_own_username():
    shown = telegram_lookup.parse_page(page("bot"))
    assert (shown["type"], shown["count_text"], shown["title"]) == ("bot", "4 321 monthly users", "Sample Wallet Bot")


def test_a_user_page_says_account_and_has_no_count():
    shown = telegram_lookup.parse_page(page("user"))
    assert (shown["type"], shown["count_text"], shown["description"]) == ("account", "", "")


def test_missing_parts_are_empty_and_an_unstated_type_stays_unstated():
    shown = telegram_lookup.parse_page(page("bare"))
    assert shown == {"exists": True, "title": "Sample Bare Page", "type": "", "count_text": "", "description": "",
                     "badges": []}


def test_a_page_showing_no_account_says_so_and_keeps_nothing_from_its_text():
    shown = telegram_lookup.parse_page(page("not_found"))
    assert shown["exists"] is False and shown["title"] == shown["description"] == ""


@pytest.mark.parametrize("body", [b"", b"<html><body>Rate limited</body></html>", b'{"ok": false}', b"\xff\xfe<<<"])
def test_an_answer_that_is_not_a_preview_page_raises(body):
    with pytest.raises(ValueError):
        telegram_lookup.parse_page(body)


def test_broken_markup_and_long_text_are_read_safely():
    body = ('<div class="tgme_page"><div class="tgme_page_title"><span>Sample\n\u200b' + "x" * 500
            + '</div></i></span><div class="tgme_page_description">\u202eevil</p>').encode()
    shown = telegram_lookup.parse_page(body)
    assert len(shown["title"]) <= telegram_lookup.TITLE_MAX and shown["title"].endswith("…")
    assert "\n" not in shown["title"] and "\u202e" not in shown["description"]


# -- one lookup --------------------------------------------------------------------------------------
def test_only_the_one_t_me_page_is_asked_for_and_kept_with_its_hash(served):
    calls, _ = served
    found = telegram_lookup.look_up("@Sample_Signals")
    assert calls == ["https://t.me/sample_signals"]
    assert found["queried"] == "sample_signals" and found["kind"] == "telegram" and found["page_note"] == ""
    [record] = found["records"]
    assert record["sha256"] == hashlib.sha256(page("channel")).hexdigest() and record["bytes"] == len(page("channel"))
    assert (record["source"], record["provider"], record["status"]) == ("telegram-page", "t.me", 200)
    assert record["fetched_at"] and record["body"]


def test_a_page_with_no_account_is_a_result_with_a_note(served):
    _, answer = served
    answer["body"] = page("not_found")
    found = telegram_lookup.look_up("sample_nobody")
    assert found["page"]["exists"] is False and "showed no public channel" in found["page_note"]


@pytest.mark.parametrize("status,words", [(302, "not followed"), (404, "answered 404"), (429, "answered 429")])
def test_another_status_is_kept_and_nothing_is_read(served, status, words):
    _, answer = served
    answer["status"], answer["body"] = status, page("channel")
    found = telegram_lookup.look_up("sample_signals")
    assert found["page"] is None and words in found["page_note"] and found["records"][0]["status"] == status


def test_an_answer_that_is_not_a_preview_page_is_a_note(served):
    _, answer = served
    answer["body"] = b"<html><body>Please wait</body></html>"
    found = telegram_lookup.look_up("sample_signals")
    assert found["page"] is None and "not a public preview page" in found["page_note"]


@pytest.mark.parametrize("handle", ["abcd", "a" * 33, "1sample", "_sample", "sample_", "sam ple", "sam-ple",
                                    "sample/../x", "sample#x", "joinchat", "addstickers",
                                    "https://evil.example/sample", "sample@evil.example", "ｓａｍｐｌｅ"])
def test_a_bad_username_is_refused_before_any_request(served, handle):
    calls, _ = served
    with pytest.raises(IdentifierError):
        telegram_lookup.look_up(handle)
    assert calls == []


@pytest.mark.parametrize("handle", ["sampl", "a" * 32, "t.me/Sample_Agent", "https://t.me/sample_agent", "@sample_9"])
def test_a_username_by_telegram_s_rules_is_accepted(served, handle):
    telegram_lookup.look_up(handle)
    assert served[0][0].startswith("https://t.me/") and served[0][0].count("/") == 3


def test_t_me_unreachable_stops_the_lookup_with_a_reason(monkeypatch):
    def down(url):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(telegram_lookup, "_get", down)
    with pytest.raises(LookupError_, match="could not be reached"):
        telegram_lookup.look_up("sample_signals")


# -- the HTTP client ---------------------------------------------------------------------------------
def _transport(monkeypatch, handler):
    seen: list[httpx.Request] = []

    def record(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(telegram_lookup, "_transport", httpx.MockTransport(record))
    return seen


def test_a_redirect_is_never_followed(monkeypatch):
    seen = _transport(monkeypatch, lambda r: httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"}))
    found = telegram_lookup.look_up("sample_signals")
    assert [str(r.url) for r in seen] == ["https://t.me/sample_signals"] and found["page"] is None


def test_no_cookie_or_key_is_sent(monkeypatch):
    seen = _transport(monkeypatch, lambda r: httpx.Response(200, content=page("channel")))
    assert telegram_lookup.look_up("sample_signals")["page"]["title"] == "Sample Signals & Tips"
    assert "cookie" not in seen[0].headers and "authorization" not in seen[0].headers


def test_an_oversized_page_is_refused_and_not_kept(monkeypatch):
    _transport(monkeypatch, lambda r: httpx.Response(200, content=b"x" * (telegram_lookup.BODY_MAX + 1)))
    with pytest.raises(LookupError_, match="more than 256 kB"):
        telegram_lookup.look_up("sample_signals")


def test_a_slow_page_stops_at_the_deadline(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(telegram_lookup, "_clock", lambda: now[0])

    def chunks():
        for _ in range(3):
            now[0] += 10  # each piece takes 10 seconds
            yield b"<div>"

    _transport(monkeypatch, lambda r: httpx.Response(200, content=chunks()))
    with pytest.raises(LookupError_, match="longer than 15 seconds"):
        telegram_lookup.look_up("sample_signals")


def test_a_server_sending_just_inside_each_read_timeout_cannot_hold_the_lookup(monkeypatch):
    """Each piece comes after 7 s, inside the 8 s read timeout: the reads are cut at 15 s in all,
    not checked only once a slow read has returned (which let a lookup run to about 23 s)."""
    now = [0.0]
    monkeypatch.setattr(telegram_lookup, "_clock", lambda: now[0])
    net = SlowNetwork(now, [RESPONSE] + [b"<"] * 10, gap_s=7.0)
    monkeypatch.setattr(telegram_lookup, "_network", net)
    with pytest.raises(LookupError_, match="longer than 15 seconds"):
        telegram_lookup.look_up("sample_signals")
    assert now[0] <= telegram_lookup.DEADLINE_S + 1e-9
    assert all(t is not None and t <= telegram_lookup.TIMEOUT_S for _, t in net.waits)


def test_a_page_through_the_capped_transport_is_read_as_usual(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(telegram_lookup, "_clock", lambda: now[0])
    body = page("channel")
    head = f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n\r\n".encode()
    monkeypatch.setattr(telegram_lookup, "_network", SlowNetwork(now, [head, body], gap_s=0.5))
    found = telegram_lookup.look_up("sample_signals")
    assert found["page"]["title"] == "Sample Signals & Tips"
    assert found["records"][0]["sha256"] == hashlib.sha256(body).hexdigest()
