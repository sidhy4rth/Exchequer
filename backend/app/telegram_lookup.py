"""A Telegram username's public page (suite feature 4, OSINT slice 4).

For a Telegram username on a case's identifier register (identifiers.py), fetch the
one public preview page https://t.me/<username> -- the page anyone sees without
Telegram or a login -- and keep what that page itself shows: whether it shows an
account at all, its display title, what kind of account the page says it is
(channel, group, bot, or "account" for a user's own), the subscriber or member count as written, the
description, and a verified, scam or fake badge when the markup carries one.

What this is not: no login, no API key, no Telegram API, no messages, no link on
the page is followed. A public page is never an identity: anyone can name a channel
anything, and only Telegram can say who runs an account.

Safety, as domain_lookup.py: the server never fetches a URL an officer typed. The
only request is GET https://t.me/<username>, after username() has accepted the name
(5 to 32 letters, digits or _, starting with a letter; never one of t.me's own
paths). Redirects are never followed; the answer must arrive within DEADLINE_S and
be at most BODY_MAX. The response is kept with where it came from, when, its HTTP
status and the SHA-256 of its body as received (domain_lookup._record), so a shown
fact can be checked against the bytes it came from. Tests replace _get or set
_transport; their pages (tests/fixtures/osint/telegram/) are synthetic.
"""
from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from typing import Any

import httpx

from . import identifiers
from .display_text import one_line
from .domain_lookup import LookupError_, _record

PAGE_URL = "https://t.me/"
TIMEOUT_S = 8.0  # for one read
DEADLINE_S = 15.0  # for the whole page, however slowly it arrives
BODY_MAX = 256 * 1024  # a t.me preview page is about 11 kB
USER_AGENT = "Exchequer case tool (reads a Telegram username's public t.me page for an investigation)"
TITLE_MAX, COUNT_MAX, DESCRIPTION_MAX = 128, 160, 1000
_transport: httpx.BaseTransport | None = None  # tests set an httpx.MockTransport
_clock = time.monotonic  # tests set a clock that a slow server moves on

# Telegram's username rules: 5 to 32 of a-z, 0-9 and _, starting with a letter, not ending with _.
_USERNAME = re.compile(r"[a-z][a-z0-9_]{3,30}[a-z0-9]")
# t.me's own pages (Telegram's deep links), which are not usernames.
_TME_PATHS = frozenset({"joinchat", "addstickers", "addemoji", "addtheme", "addlist", "share", "proxy", "socks",
                        "setlanguage", "confirmphone", "login", "invoice", "boost", "giftcode", "contact"})
_BADGES = ("verified", "scam", "fake")
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"})
_FIELDS = {"tgme_page_title": "title", "tgme_page_extra": "extra", "tgme_page_description": "description",
           "tgme_page_action": "action", "tgme_page_context_link": "context"}


def username(raw: str) -> str:
    """The username t.me is asked about, or IdentifierError before any request is made."""
    text = identifiers.telegram(raw)  # the register's own check and normalising: no @, no link, lower case
    if not _USERNAME.fullmatch(text):
        raise identifiers.IdentifierError("t.me only has pages for usernames of 5 to 32 letters, digits or _, "
                                          "starting with a letter and not ending with _; this one is not looked up.")
    if text in _TME_PATHS:
        raise identifiers.IdentifierError("That is one of t.me's own pages, not a username; it is not looked up.")
    return text


def _get(url: str) -> tuple[int, bytes]:
    """GET `url` and give back (status, body). Never follows a redirect, sends no cookie,
    refuses more than BODY_MAX and stops at DEADLINE_S even while bytes still arrive."""
    started = _clock()
    with httpx.Client(timeout=TIMEOUT_S, follow_redirects=False, transport=_transport,
                      headers={"User-Agent": USER_AGENT, "Accept": "text/html", "Accept-Language": "en"}) as client:
        with client.stream("GET", url) as response:
            body = b""
            for chunk in response.iter_bytes():
                if _clock() - started > DEADLINE_S:
                    raise LookupError_(f"t.me took longer than {DEADLINE_S:.0f} seconds, so the lookup stopped.")
                body += chunk
                if len(body) > BODY_MAX:
                    raise LookupError_(f"t.me sent more than {BODY_MAX // 1024} kB, which is not a preview page; "
                                       "nothing was kept.")
            return response.status_code, body


# -- reading the page --------------------------------------------------------------------------------
class _Page(HTMLParser):
    """Collects the text of the page's few named parts. Text inside a badge in the title is
    not title text; it only sets the badge. Anything else on the page is ignored."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None, bool]] = []  # (tag, field its text goes to, inside a badge)
        self.text: dict[str, list[str]] = {"title": [], "description": [], "action": [], "context": []}
        self.extras: list[list[str]] = []
        self.badges: set[str] = set()
        self.preview = False  # a tgme_page block was seen: this is a t.me preview page

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = " ".join(v or "" for k, v in attrs if k == "class").split()
        field, badge = (self.stack[-1][1], self.stack[-1][2]) if self.stack else (None, False)
        self.preview = self.preview or "tgme_page" in classes
        for name in classes:
            if name in _FIELDS:
                field = _FIELDS[name]
                if field == "extra":
                    self.extras.append([])
        if field == "title":
            hit = [b for b in _BADGES if any(b in name.lower() for name in classes)]
            if hit:
                self.badges.update(hit)
                badge = True
        if tag in _VOID:
            if field and not badge and tag == "br":
                self._add(field, " ")
            return
        self.stack.append((tag, field, badge))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):  # close back to the matching tag; a stray one is ignored
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1][1] and not self.stack[-1][2]:
            self._add(self.stack[-1][1], data)

    def _add(self, field: str, data: str) -> None:
        if field == "extra":
            if self.extras:
                self.extras[-1].append(data)
        else:
            self.text[field].append(data)


def _clean(parts: list[str], limit: int) -> str:
    text = re.sub(r"\s+", " ", one_line("".join(parts))).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _kind(extras: list[str], action: str, context: str) -> str:
    """What the page's own words say the account is; empty when they do not say."""
    words, action, context = " ".join(extras).lower(), action.lower(), context.lower()
    if "start bot" in action or "monthly user" in words:
        return "bot"
    if "preview channel" in context or "subscriber" in words:
        return "channel"
    if "preview group" in context or "join group" in action or "member" in words:
        return "group"
    if "send message" in action:
        return "account"  # a user's own account: the page offers to message it
    return ""


def parse_page(body: bytes) -> dict[str, Any]:
    """What the t.me page shows. A page with no title shows no account. ValueError when the
    answer is not a t.me preview page at all."""
    page = _Page()
    page.feed(body.decode("utf-8", errors="replace"))
    page.close()
    if not page.preview:
        raise ValueError("not a t.me preview page")
    title = _clean(page.text["title"], TITLE_MAX)
    if not title:
        return {"exists": False, "title": "", "type": "", "count_text": "", "description": "", "badges": []}
    extras = [_clean(e, COUNT_MAX) for e in page.extras]
    counts = [e for e in extras if e and not e.startswith("@")]  # a user's or bot's extra line is its @username
    return {
        "exists": True,
        "title": title,
        "type": _kind(extras, _clean(page.text["action"], 64), _clean(page.text["context"], 64)),
        "count_text": _clean([" · ".join(counts)], COUNT_MAX),
        "description": _clean(page.text["description"], DESCRIPTION_MAX),
        "badges": sorted(page.badges),
    }


# -- one lookup ----------------------------------------------------------------------------------
def look_up(name: str) -> dict[str, Any]:
    """What https://t.me/<name> shows, with the response kept. Raises LookupError_ only when
    nothing was received; a page showing no account, or another status, is a result."""
    handle = username(name)
    url = PAGE_URL + handle
    try:
        status, body = _get(url)
    except httpx.HTTPError as exc:
        raise LookupError_(f"t.me could not be reached ({type(exc).__name__}); try again later.") from exc
    page, note = None, ""
    if status == 200:
        try:
            page = parse_page(body)
        except ValueError:
            note = "t.me's answer was not a public preview page, so nothing was read from it."
        else:
            if not page["exists"]:
                note = "t.me showed no public channel, group, user or bot under this username."
    elif 300 <= status < 400:
        note = f"t.me answered {status}, pointing elsewhere; that was not followed, so nothing was read."
    else:
        note = f"t.me answered {status}, so nothing was read."
    return {"kind": "telegram", "queried": handle, "page": page, "page_note": note,
            "records": [_record("telegram-page", url, status, body)]}
