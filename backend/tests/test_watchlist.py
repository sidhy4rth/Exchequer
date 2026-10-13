"""The watchlist (app/watchlist.py, app/routes/watches.py)."""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import api_budget, models, ownership, watchlist
from app.etherscan_client import Transaction
from app.main import app

ALICE, BOB = "a" * 32, "b" * 32
WALLET = "0x" + "7" * 40
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"  # in the ETH label file
TORNADO = "0x722122df12d4e14e13ac3b6895a86e84145b6967"     # mixer in the threat file
STRANGER = "0x" + "9" * 40


def tx(block, to, value=1.5, h=None):
    return Transaction(hash=h or f"0x{block:064x}", from_address=WALLET, to_address=to,
                       value_native=value, value_wei=int(value * 1e18), timestamp=1_700_000_000 + block,
                       block_number=block, is_error=False, asset="ETH")


class FakeChain:
    """Stands in for open_source(): returns whatever `transfers` holds now."""

    def __init__(self):
        self.transfers: list[Transaction] = []
        self.fail = False
        self.fresh_flags: list[bool] = []

    def __call__(self, chain, asset):
        fake = self

        @contextmanager
        def client():
            class C:
                def get_outgoing_transactions(self, address, limit=None):
                    fake.fresh_flags.append(api_budget._fresh.get())
                    if fake.fail:
                        raise RuntimeError("provider down")
                    return list(fake.transfers)
            yield C()
        return client()


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'w.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()


@pytest.fixture
def chain(store):
    return FakeChain()


def owner(key):
    return ownership.owner_hash(key)


def test_first_check_sets_a_baseline_and_raises_nothing(chain):
    chain.transfers = [tx(100, STRANGER)]
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    assert watchlist.check_watch(w.id, source=chain) == []
    assert watchlist.list_watches(owner(ALICE))[0]["baseline_set"] is True


def test_new_transfers_become_alerts_ranked_by_destination(chain):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(100, STRANGER), tx(101, BINANCE_14, 3.0), tx(102, TORNADO), tx(103, STRANGER)]
    alerts = watchlist.check_watch(w.id, source=chain)
    kinds = [a["kind"] for a in alerts]
    assert kinds == ["exchange", "risk", "moved"]
    assert "Binance" in alerts[0]["message"] and "3 ETH" in alerts[0]["message"]
    # Nothing new next round.
    assert watchlist.check_watch(w.id, source=chain) == []
    assert chain.fresh_flags and all(chain.fresh_flags)  # never answered from the cache


def test_provider_failure_is_recorded_not_raised(chain):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.fail = True
    assert watchlist.check_watch(w.id, source=chain) == []
    assert "Could not read" in watchlist.list_watches(owner(ALICE))[0]["last_error"]


def test_webhooks_only_to_known_hosts_over_https():
    assert watchlist.validate_webhook("https://hooks.slack.com/services/T/B/x")
    assert watchlist.validate_webhook("https://discord.com/api/webhooks/1/abc")
    for bad in ("http://hooks.slack.com/x", "https://169.254.169.254/latest", "https://localhost/x",
                "https://hooks.slack.com.evil.com/x", "https://user@hooks.slack.com/x",
                "https://hooks.slack.com:8443/x", "file:///etc/passwd"):
        with pytest.raises(watchlist.WatchError):
            watchlist.validate_webhook(bad)


def test_alerts_are_posted_to_the_webhook_and_the_url_is_never_echoed(chain):
    sent = []
    hook = "https://hooks.slack.com/services/T000/B000/secret"
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH", webhook_url=hook)
    summary = watchlist.list_watches(owner(ALICE))[0]
    assert summary["webhook"] == "https://hooks.slack.com/…" and "secret" not in str(summary)
    chain.transfers = []
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(5, BINANCE_14)]
    watchlist.check_watch(w.id, source=chain, post=lambda url, payload: sent.append((url, payload)))
    assert sent and sent[0][0] == hook and "Binance" in sent[0][1]["text"]


def test_watches_and_alerts_belong_to_their_browser(chain):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(9, STRANGER)]
    watchlist.check_watch(w.id, source=chain)
    assert watchlist.list_watches(owner(BOB)) == []
    assert watchlist.list_alerts(owner(BOB)) == []
    assert len(watchlist.list_alerts(owner(ALICE), unread_only=True)) == 1
    assert watchlist.remove_watch(owner(BOB), w.id) is False
    assert watchlist.mark_read(owner(ALICE)) == 1
    assert watchlist.list_alerts(owner(ALICE), unread_only=True) == []


def test_bad_input_and_limits(store, monkeypatch):
    with pytest.raises(watchlist.WatchError):
        watchlist.create_watch(owner(ALICE), "nope", "ethereum", "ETH")
    with pytest.raises(watchlist.WatchError):
        watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "DOGE")
    # Watching the same address twice returns the one watch.
    a = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", None)
    b = watchlist.create_watch(owner(ALICE), WALLET.upper().replace("0X", "0x"), "ethereum", "eth")
    assert a.id == b.id
    monkeypatch.setattr(watchlist, "MAX_WATCHES_PER_OWNER", 1)
    with pytest.raises(watchlist.WatchError):
        watchlist.create_watch(owner(ALICE), STRANGER, "ethereum", "ETH")


def test_routes(store, monkeypatch):
    calls = []
    monkeypatch.setattr(watchlist, "check_watch", lambda wid, **k: calls.append(wid) or [])
    client = TestClient(app)
    h = {ownership.OWNER_HEADER: ALICE}
    assert client.post("/watches", json={"address": WALLET}).status_code == 400  # no owner key
    made = client.post("/watches", json={"address": WALLET, "chain": "ethereum"}, headers=h)
    assert made.status_code == 201
    wid = made.json()["watch_id"]
    assert client.get("/watches", headers=h).json()["count"] == 1
    assert client.get("/watches", headers={ownership.OWNER_HEADER: BOB}).json()["count"] == 0
    assert client.post(f"/watches/{wid}/check", headers=h).status_code == 200
    # check_watch was stubbed, so mark the watch as just checked and try again.
    with models.session() as s:
        s.get(models.Watch, wid).last_checked_at = models.utc_now_iso()
        s.commit()
    assert client.post(f"/watches/{wid}/check", headers=h).status_code == 429
    assert client.post("/watches", json={"address": WALLET, "webhook_url": "https://evil.example/x"},
                       headers=h).status_code == 400
    assert client.delete(f"/watches/{wid}", headers={ownership.OWNER_HEADER: BOB}).status_code == 404
    assert client.delete(f"/watches/{wid}", headers=h).status_code == 200
    assert client.get("/alerts", headers=h).json()["count"] == 0


def test_due_watches_are_the_unchecked_and_the_stale(store):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    assert watchlist.due_watch_ids(600) == [w.id]
    with models.session() as s:
        s.get(models.Watch, w.id).last_checked_at = models.utc_now_iso()
        s.commit()
    assert watchlist.due_watch_ids(600) == []


def test_a_transfer_to_an_inferred_deposit_address_counts_as_an_exchange(chain):
    deposit = "0x" + "d" * 40
    models.save_case("c1", WALLET, {"address": WALLET, "chain": "ethereum",
                                    "inferred_deposits": [{"address": deposit, "exchange": "OKX"}]})
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH", case_id="c1")
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(7, deposit, 2.0)]
    (alert,) = watchlist.check_watch(w.id, source=chain)
    assert alert["kind"] == "exchange" and "probable OKX deposit" in alert["message"]
    assert alert["exchange"] == "OKX" and alert["case_id"] == "c1"
    listed = watchlist.list_alerts(owner(ALICE))[0]
    assert listed["exchange"] == "OKX" and listed["case_id"] == "c1"
