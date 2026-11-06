"""What a watch posts to Slack, Discord or Google Chat (watchlist._deliver).

It used to post the ten oldest alerts of a check in a tight loop, so ten
dust transfers before a cash-out meant the channel never heard of it; a 429
was swallowed, nothing said a post had failed, and the one mixed payload
went to every host: Google Chat refuses unknown fields, and Slack and
Discord rendered third-party label text with mentions and links live
(r2-g2-watchlist-alerts-0-1, r2-g2-watchlist-alerts-0-8).
"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import create_engine, select

from app import models, ownership, watchlist
from test_watchlist import ALICE, BINANCE_14, STRANGER, WALLET, FakeChain, later, owner, tx

SLACK = "https://hooks.slack.com/services/T000/B000/secret"
DISCORD = "https://discord.com/api/webhooks/1/abc"
GCHAT = "https://chat.googleapis.com/v1/spaces/X/messages?key=k&token=t"


@pytest.fixture
def chain(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'h.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(watchlist, "_pause", lambda seconds: None)
    return FakeChain()


def hooked(chain, hook=SLACK):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH", webhook_url=hook)
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)  # baseline at block 100
    return w


def last_error(w):
    return watchlist.list_watches(owner(ALICE))[0]["last_error"]


def test_the_exchange_alert_is_the_first_post_and_the_rest_is_one_digest(chain):
    w = hooked(chain)
    dust = [tx(101 + i, STRANGER, 0.0001, ts=later(i)) for i in range(10)]
    cash_out = tx(111, BINANCE_14, 25.0, ts=later(11))
    more_dust = [tx(112 + i, STRANGER, 0.0001, ts=later(12 + i)) for i in range(30)]
    chain.transfers = [tx(100, STRANGER), *dust, cash_out, *more_dust]
    sent = []
    out = watchlist.check_watch(w.id, source=chain, post=lambda url, payload: sent.append(payload))
    assert out[0]["kind"] == "exchange"  # ranked: where the money went, then how much
    assert len(sent) <= 4
    assert "Binance" in sent[0]["text"] and "25 ETH" in sent[0]["text"]
    assert "40 other movements" in sent[1]["text"]


def test_each_post_says_when_the_transfer_happened(chain):
    w = hooked(chain)
    chain.transfers = [tx(100, STRANGER), tx(101, BINANCE_14, 2.0, ts=1_900_000_000)]
    sent = []
    watchlist.check_watch(w.id, source=chain, post=lambda url, payload: sent.append(payload))
    assert "2030-03-17 17:46 UTC" in sent[0]["text"]


class Hook:
    """A webhook host answering from a script of responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.bodies = []

    def handler(self, request):
        import json
        self.bodies.append(json.loads(request.content))
        return self.responses.pop(0) if self.responses else httpx.Response(200)

    def install(self, monkeypatch):
        monkeypatch.setattr(watchlist, "_http", lambda: httpx.Client(transport=httpx.MockTransport(self.handler)))


def test_a_429_is_retried_once_after_retry_after(chain, monkeypatch):
    hook = Hook(httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200))
    hook.install(monkeypatch)
    slept = []
    monkeypatch.setattr(watchlist, "_pause", slept.append)
    w = hooked(chain)
    chain.transfers = [tx(100, STRANGER), tx(101, BINANCE_14, 2.0, ts=later())]
    watchlist.check_watch(w.id, source=chain)
    assert len(hook.bodies) == 2 and slept == [1.0]
    assert last_error(w) is None


def test_a_long_retry_after_stops_delivery_and_says_so(chain, monkeypatch):
    hook = Hook(httpx.Response(429, headers={"Retry-After": "60"}))
    hook.install(monkeypatch)
    w = hooked(chain)
    chain.transfers = [tx(100, STRANGER), tx(101, BINANCE_14, 2.0, ts=later()), tx(102, BINANCE_14, 3.0, ts=later())]
    watchlist.check_watch(w.id, source=chain)
    assert len(hook.bodies) == 1
    assert last_error(w).startswith("Webhook:") and "429" in last_error(w) and "in the app" in last_error(w)


def test_a_failed_post_is_shown_on_the_watch(chain, monkeypatch):
    Hook(httpx.Response(404)).install(monkeypatch)
    w = hooked(chain)
    chain.transfers = [tx(100, STRANGER), tx(101, BINANCE_14, 2.0, ts=later())]
    watchlist.check_watch(w.id, source=chain)
    assert "404" in last_error(w)
    with models.session() as s:
        assert s.scalars(select(models.Alert)).first() is not None  # stored either way


def test_a_discord_retry_after_in_the_body_is_honoured(chain, monkeypatch):
    hook = Hook(httpx.Response(429, json={"retry_after": 0.4}), httpx.Response(204))
    hook.install(monkeypatch)
    slept = []
    monkeypatch.setattr(watchlist, "_pause", slept.append)
    w = hooked(chain, DISCORD)
    chain.transfers = [tx(100, STRANGER), tx(101, BINANCE_14, 2.0, ts=later())]
    watchlist.check_watch(w.id, source=chain)
    assert len(hook.bodies) == 2 and slept == [0.4]


POISON = "<https://phish.example|Binance deposit> <!channel> @everyone <users/all>"


def poisoned(chain, monkeypatch, hook_url):
    hook = Hook()
    hook.install(monkeypatch)
    monkeypatch.setattr(watchlist, "_classify", lambda *a, **k: ("exchange", POISON))
    w = hooked(chain, hook_url)
    chain.transfers = [tx(100, STRANGER), tx(101, STRANGER, 2.0, ts=later())]
    watchlist.check_watch(w.id, source=chain)
    (body,) = hook.bodies
    return body


def test_slack_gets_text_only_and_markup_in_labels_is_escaped(chain, monkeypatch):
    body = poisoned(chain, monkeypatch, SLACK)
    assert set(body) == {"text"}
    assert "&lt;!channel&gt;" in body["text"] and "<!channel>" not in body["text"]
    assert "<https://phish" not in body["text"]  # no disguised link
    assert "etherscan.io/tx/" in body["text"]  # our own link still works


def test_discord_gets_content_with_mentions_switched_off(chain, monkeypatch):
    body = poisoned(chain, monkeypatch, DISCORD)
    assert set(body) == {"content", "allowed_mentions"}
    assert body["allowed_mentions"] == {"parse": []}
    assert "\\@everyone" in body["content"] and len(body["content"]) <= 1900


def test_google_chat_gets_only_text(chain, monkeypatch):
    body = poisoned(chain, monkeypatch, GCHAT)
    assert set(body) == {"text"}
    text = body["text"].replace("<https://etherscan.io", "")
    assert "<" not in text and ">" not in text


def test_a_url_in_a_label_is_defanged(chain, monkeypatch):
    body = poisoned(chain, monkeypatch, SLACK)
    assert "https://phish.example" not in body["text"] and "phish.example" in body["text"]


def test_pruning_never_drops_an_unread_exchange_alert(chain, monkeypatch):
    monkeypatch.setattr(watchlist, "MAX_ALERTS_PER_WATCH", 30)
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(101, BINANCE_14, 9.0)]
    watchlist.check_watch(w.id, source=chain)
    block = 102
    for _ in range(5):  # 100 newer movements
        chain.transfers = [tx(block + i, STRANGER) for i in range(20)]
        block += 20
        watchlist.check_watch(w.id, source=chain)
    kinds = [a["kind"] for a in watchlist.list_alerts(owner(ALICE), limit=500)]
    assert "exchange" in kinds and len(kinds) == 30


def test_the_internal_alert_record_is_never_sent(chain, monkeypatch):
    hook = Hook()
    hook.install(monkeypatch)
    w = hooked(chain)
    chain.transfers = [tx(100, STRANGER), tx(101, BINANCE_14, 2.0, ts=later())]
    watchlist.check_watch(w.id, source=chain)
    assert "alert" not in hook.bodies[0] and "content" not in hook.bodies[0]
    assert ownership.owner_hash(ALICE) not in str(hook.bodies)


def test_unread_exchange_alerts_come_first_in_the_list(chain):
    # Alerts of one check share a created_at, so dust sent after a cash-out
    # sorted above it; two checks of dust pushed it out of GET /alerts.
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(101 + i, STRANGER, 0.001) for i in range(20)] + [tx(121, BINANCE_14, 5.0)] + \
        [tx(122 + i, STRANGER, 0.001) for i in range(20)]
    watchlist.check_watch(w.id, source=chain)
    for start in (142, 182, 222):
        chain.transfers = [tx(start + i, STRANGER, 0.001) for i in range(40)]
        watchlist.check_watch(w.id, source=chain)
    listed = watchlist.list_alerts(owner(ALICE), limit=30)
    assert listed[0]["kind"] == "exchange"
    watchlist.mark_read(owner(ALICE), [listed[0]["alert_id"]])
    assert watchlist.list_alerts(owner(ALICE), limit=30)[0]["kind"] == "moved"  # read: back in time order
