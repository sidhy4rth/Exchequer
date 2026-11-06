"""Webhook URLs are credentials (app/webhook_vault.py, r2-g2-watchlist-alerts-0-9).

Whoever holds a Slack, Discord or Google Chat webhook URL can post into the
police channel. They were stored in plain text (in the database, its
branches and every snapshot), and could not be cleared without deleting the
watch. Runs against throwaway SQLite files; nothing is posted anywhere.
"""
from __future__ import annotations

import gzip
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import backups, config, models, ownership, watchlist, webhook_vault
from app.main import app
from test_watchlist import ALICE, BINANCE_14, BOB, STRANGER, WALLET, FakeChain, later, owner, tx

HOOK = "https://hooks.slack.com/services/T000/B000/" + "s" * 24


@pytest.fixture
def chain(tmp_path, monkeypatch):
    db = tmp_path / "v.db"
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{db}", future=True))
    monkeypatch.setattr(config, "DB_PATH", db)
    models.init_db()
    monkeypatch.setattr(watchlist, "_pause", lambda seconds: None)
    monkeypatch.setattr(config, "WEBHOOK_KEY", "a long random operator secret")
    return FakeChain()


def raw_hook(watch_id):
    with models.engine().connect() as conn:
        return conn.execute(text("SELECT webhook_url FROM watches WHERE id = :i"), {"i": watch_id}).scalar()


def posted_to(chain, w):
    sent = []
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(100, STRANGER), tx(101, BINANCE_14, 2.0, ts=later())]
    watchlist.check_watch(w.id, source=chain, post=lambda url, payload: sent.append(url))
    return sent


def test_a_webhook_is_not_stored_in_plain_text(chain):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH", webhook_url=HOOK)
    stored = raw_hook(w.id)
    assert stored.startswith("v1:") and "hooks.slack.com" not in stored
    assert posted_to(chain, w) == [HOOK]
    assert watchlist.list_watches(owner(ALICE))[0]["webhook"] == "https://hooks.slack.com/…"


def test_without_a_key_webhooks_still_work(chain, monkeypatch):
    monkeypatch.setattr(config, "WEBHOOK_KEY", "")
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH", webhook_url=HOOK)
    assert raw_hook(w.id) == HOOK
    assert posted_to(chain, w) == [HOOK]


def test_a_hook_can_be_cleared_without_removing_the_watch(chain):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH", webhook_url=HOOK)
    client = TestClient(app)
    assert client.delete(f"/watches/{w.id}/webhook", headers={ownership.OWNER_HEADER: BOB}).status_code == 404
    r = client.delete(f"/watches/{w.id}/webhook", headers={ownership.OWNER_HEADER: ALICE})
    assert r.status_code == 200 and r.json()["webhook"] is None
    assert raw_hook(w.id) is None
    assert watchlist.list_watches(owner(ALICE))[0]["watch_id"] == w.id  # still watching
    assert posted_to(chain, w) == []


def test_a_300_character_hook_fits_the_column_when_sealed(chain):
    long_hook = "https://hooks.slack.com/services/" + "x" * (300 - len("https://hooks.slack.com/services/"))
    sealed = webhook_vault.seal(long_hook)
    assert len(long_hook) == 300 and len(sealed) <= models.Watch.__table__.c.webhook_url.type.length
    assert TestClient(app).post("/watches", json={"address": WALLET, "webhook_url": long_hook + "y"},
                                headers={ownership.OWNER_HEADER: ALICE}).status_code == 422


def test_a_hook_sealed_under_another_key_asks_to_be_re_entered(chain, monkeypatch):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH", webhook_url=HOOK)
    monkeypatch.setattr(config, "WEBHOOK_KEY", "a different secret")
    summary = watchlist.list_watches(owner(ALICE))[0]
    assert summary["webhook"] is None and summary["webhook_unreadable"] is True
    assert posted_to(chain, w) == []  # nothing sent anywhere


def test_legacy_plain_hooks_are_sealed_at_startup(chain):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    with models.engine().begin() as conn:  # what the old code stored
        conn.execute(text("UPDATE watches SET webhook_url = :h WHERE id = :i"), {"h": HOOK, "i": w.id})
    assert watchlist.seal_legacy_hooks() == 1
    assert raw_hook(w.id).startswith("v1:") and webhook_vault.reveal(raw_hook(w.id)) == HOOK
    assert watchlist.seal_legacy_hooks() == 0


def test_a_snapshot_carries_no_webhook_urls(chain, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WEBHOOK_KEY", "")  # even an unsealed one
    watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH", webhook_url=HOOK)
    out = backups.snapshot(tmp_path / "out" / "snap.db.gz")
    data = gzip.decompress(out.read_bytes())
    assert b"hooks.slack.com" not in data
    raw = tmp_path / "restored.db"
    raw.write_bytes(data)
    assert sqlite3.connect(raw).execute("SELECT count(*) FROM watches").fetchone()[0] == 1


def test_the_operator_can_see_whether_hooks_are_sealed(chain, monkeypatch):
    monkeypatch.setattr(config, "HEALTH_TOKEN", "t" * 40)
    detail = TestClient(app).get("/health/detail", headers={"authorization": "Bearer " + "t" * 40}).json()
    assert detail["webhooks_sealed"] is True
