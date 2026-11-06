"""The watchlist (app/watchlist.py, app/routes/watches.py)."""
from __future__ import annotations

import threading
import time
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


def tx(block, to, value=1.5, h=None, ts=None):
    # Dated in 2023 unless `ts` says otherwise: history from before any watch.
    return Transaction(hash=h or f"0x{block:064x}", from_address=WALLET, to_address=to,
                       value_native=value, value_wei=int(value * 1e18),
                       timestamp=1_700_000_000 + block if ts is None else ts,
                       block_number=block, is_error=False, asset="ETH")


def later(seconds=60):
    """A time after a watch made now: a transfer it must report."""
    return int(time.time()) + seconds


class FakeChain:
    """Stands in for open_source(): returns whatever `transfers` holds now."""

    def __init__(self):
        self.transfers: list[Transaction] = []
        self.by_address: dict[str, list[Transaction]] = {}  # overrides `transfers` per address
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
                    return list(fake.by_address.get(address, fake.transfers))
            yield C()
        return client()


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'w.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    monkeypatch.setattr(watchlist, "chain_head", lambda *a, **k: None)  # never a real provider


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
                "https://hooks.slack.com:8443/x", "file:///etc/passwd", *MALFORMED_HOOKS):
        with pytest.raises(watchlist.WatchError):
            watchlist.validate_webhook(bad)


# urlsplit or .port raise a plain ValueError on these, which the route did
# not catch: a 500 and a traceback instead of a 400.
MALFORMED_HOOKS = ("https://hooks.slack.com:abc/x", "https://[hooks.slack.com/x",
                   "https://hooks.slack.com:99999/x")


def test_a_malformed_webhook_url_is_a_400_not_a_500(store):
    client = TestClient(app, raise_server_exceptions=False)
    for bad in MALFORMED_HOOKS:
        r = client.post("/watches", json={"address": WALLET, "webhook_url": bad},
                        headers={ownership.OWNER_HEADER: ALICE})
        assert r.status_code == 400, bad


def test_alerts_are_posted_to_the_webhook_and_the_url_is_never_echoed(chain):
    sent = []
    hook = "https://hooks.slack.com/services/T000/B000/secret"
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH", webhook_url=hook)
    summary = watchlist.list_watches(owner(ALICE))[0]
    assert summary["webhook"] == "https://hooks.slack.com/…" and "secret" not in str(summary)
    chain.transfers = []
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(5, BINANCE_14, ts=later())]
    watchlist.check_watch(w.id, source=chain, post=lambda url, payload: sent.append((url, payload)))
    assert sent and sent[0][0] == hook and "Binance" in sent[0][1]["text"]


def test_watches_and_alerts_belong_to_their_browser(chain):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(9, STRANGER, ts=later())]
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
    # Alice's own case: only her own and the demo cases may label her alerts.
    models.save_case("c1", WALLET, {"address": WALLET, "chain": "ethereum",
                                    "inferred_deposits": [{"address": deposit, "exchange": "OKX"}]},
                     owner_hash=owner(ALICE))
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH", case_id="c1")
    watchlist.check_watch(w.id, source=chain)
    chain.transfers = [tx(7, deposit, 2.0, ts=later())]
    (alert,) = watchlist.check_watch(w.id, source=chain)
    assert alert["kind"] == "exchange" and "probable OKX deposit" in alert["message"]
    assert alert["exchange"] == "OKX" and alert["case_id"] == "c1"
    listed = watchlist.list_alerts(owner(ALICE))[0]
    assert listed["exchange"] == "OKX" and listed["case_id"] == "c1"


TRON_WALLET = "TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G"


def trc20(seconds, to=STRANGER, value=100.0, at=None):
    # TronGrid's TRC-20 endpoint gives no block number: block_number is 0.
    # Dated in 2025 (before any watch) unless `at` gives the time.
    stamp = 1_760_000_000 + seconds if at is None else at
    return Transaction(hash=f"{stamp:064x}", from_address=TRON_WALLET, to_address=to,
                       value_native=value, value_wei=int(value * 1e6), timestamp=stamp,
                       block_number=0, is_error=False, asset="USDT")


def test_a_tron_usdt_watch_sees_new_transfers_without_block_numbers(chain, monkeypatch):
    monkeypatch.setattr(watchlist, "_classify", lambda *a, **k: ("moved", ""))
    w = watchlist.create_watch(owner(ALICE), TRON_WALLET, "tron", "USDT")
    chain.transfers = [trc20(10)]
    assert watchlist.check_watch(w.id, source=chain) == []  # history
    chain.transfers = [trc20(10), trc20(0, value=250.0, at=later(70))]
    alerts = watchlist.check_watch(w.id, source=chain)
    assert len(alerts) == 1 and "250 USDT" in alerts[0]["message"]
    assert watchlist.check_watch(w.id, source=chain) == []


def test_a_legacy_tron_cursor_reads_from_the_watch_creation_time(chain, monkeypatch):
    # Old code stored block 0 (or a block number) as a Tron cursor. Reading
    # from "newest seen" then swallowed the first transfer; reading from 0
    # would flood. Now it reads from when the watch was set.
    monkeypatch.setattr(watchlist, "_classify", lambda *a, **k: ("moved", ""))
    w = watchlist.create_watch(owner(ALICE), TRON_WALLET, "tron", "USDT")
    with models.session() as s:
        s.get(models.Watch, w.id).last_seen_block = 0
        s.commit()
    chain.transfers = [trc20(i) for i in range(1, 30)]
    assert watchlist.check_watch(w.id, source=chain) == []
    chain.transfers.append(trc20(0, at=later(99)))
    assert len(watchlist.check_watch(w.id, source=chain)) == 1


def test_a_busy_watch_keeps_only_its_newest_alerts(chain, monkeypatch):
    # Every check can store a page of alerts and nothing ever removed them:
    # a watch on a wallet that moves all day filled the free database.
    monkeypatch.setattr(watchlist, "MAX_ALERTS_PER_WATCH", 30)
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)  # baseline
    block = 101
    for _ in range(4):  # 4 checks x 20 new transfers = 80 alerts offered
        chain.transfers = [tx(block + i, STRANGER) for i in range(20)]
        block += 20
        watchlist.check_watch(w.id, source=chain)
    from sqlalchemy import func, select
    with models.session() as s:
        stored = s.scalars(select(models.Alert.tx_time).where(models.Alert.watch_id == w.id)).all()
        assert s.scalar(select(func.count()).select_from(models.Alert)) == 30
    # The newest survive.
    assert max(stored) == max(t.timestamp for t in chain.transfers)


class ScriptedChain:
    """A source whose answer, and when it gives it, each test thread decides."""

    def __init__(self, answer):
        self.answer = answer  # (thread name) -> list of transfers, after any waiting

    def __call__(self, chain, asset):
        fake = self

        @contextmanager
        def client():
            class C:
                def get_outgoing_transactions(self, address, limit=None):
                    import threading
                    return fake.answer(threading.current_thread().name)
            yield C()
        return client()


def stored_alerts(watch_id):
    from sqlalchemy import select
    with models.session() as s:
        return list(s.scalars(select(models.Alert.tx_hash).where(models.Alert.watch_id == watch_id)))


def cursor_of(watch_id):
    with models.session() as s:
        return s.get(models.Watch, watch_id).last_seen_block


def test_overlapping_checks_store_and_post_each_alert_once(chain):
    # The watcher's round and a "Check now" (or two instances during a
    # deploy) read the same cursor and the same new transfer at once.
    import threading
    hook = "https://hooks.slack.com/services/T000/B000/secret"
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH", webhook_url=hook)
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)  # baseline at 100
    both_read = threading.Barrier(2, timeout=5)

    def answer(_name):
        both_read.wait()
        return [tx(100, STRANGER), tx(101, BINANCE_14)]
    source, posts = ScriptedChain(answer), []
    threads = [threading.Thread(target=watchlist.check_watch, args=(w.id,),
                                kwargs={"source": source, "post": lambda url, body: posts.append(body)})
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert stored_alerts(w.id) == [tx(101, BINANCE_14).hash]
    assert len(posts) == 1
    assert cursor_of(w.id) == 101


def test_a_slow_check_never_moves_the_cursor_back(chain):
    import threading
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    watchlist.check_watch(w.id, source=chain)  # baseline at 100
    slow_reading, fast_done = threading.Event(), threading.Event()

    def answer(name):
        if name == "slow":
            slow_reading.set()
            fast_done.wait(5)
            return [tx(b, STRANGER) for b in (100, 120, 150)]
        return [tx(b, STRANGER) for b in (100, 120, 150, 200)]
    source, slow_result = ScriptedChain(answer), []
    slow = threading.Thread(target=lambda: slow_result.extend(watchlist.check_watch(w.id, source=source)),
                            name="slow")
    slow.start()
    assert slow_reading.wait(5)
    fast = watchlist.check_watch(w.id, source=source)
    fast_done.set()
    slow.join(10)
    assert [a["tx_hash"] for a in fast] == [tx(b, STRANGER).hash for b in (120, 150, 200)]
    assert slow_result == []  # the cursor moved past what it read: it stores nothing
    assert cursor_of(w.id) == 200
    assert sorted(stored_alerts(w.id)) == sorted(tx(b, STRANGER).hash for b in (120, 150, 200))


# ---------------------------------------------------------------------------
# One watch failing must not stop the others (r2-g2-watchlist-alerts-0-7), and
# third-party label text is cleaned and cut to its column before it is stored
# (r2-g2-postgres-prod-divergence-6-3): Postgres enforces VARCHAR(200) and
# refuses NUL, SQLite does neither.
# ---------------------------------------------------------------------------
OTHER_WALLET = "0x" + "8" * 40


def _two_baselined_watches(chain, monkeypatch):
    a = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    b = watchlist.create_watch(owner(BOB), OTHER_WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER)]
    for w in (a, b):
        watchlist.check_watch(w.id, source=chain)
    with models.session() as s:  # A is first in the queue
        s.get(models.Watch, a.id).last_checked_at = "2026-01-01T00:00:00+00:00"
        s.get(models.Watch, b.id).last_checked_at = "2026-01-01T00:00:01+00:00"
        s.commit()
    real = watchlist.check_watch
    monkeypatch.setattr(watchlist, "check_watch", lambda wid, **k: real(wid, source=chain))
    # An app shutdown earlier in the run sets the watcher's stop flag.
    monkeypatch.setattr(watchlist, "_stop", threading.Event())
    return a, b


def _alerts_of(watch_id):
    from sqlalchemy import select
    with models.session() as s:
        return list(s.scalars(select(models.Alert).where(models.Alert.watch_id == watch_id)))


def test_one_failing_watch_does_not_stop_the_round(chain, monkeypatch):
    a, b = _two_baselined_watches(chain, monkeypatch)
    poisoned = "0x" + "e" * 40
    real_classify = watchlist._classify

    def classify(chain_key, to, *args, **kwargs):
        if to == poisoned:
            raise RuntimeError("bad label row")
        return real_classify(chain_key, to, *args, **kwargs)
    monkeypatch.setattr(watchlist, "_classify", classify)
    chain.by_address = {WALLET: [tx(200, poisoned)], OTHER_WALLET: [tx(201, STRANGER)]}
    watchlist._round(0)
    assert len(_alerts_of(b.id)) >= 1  # B was reached and its alerts stored
    summary = {w["watch_id"]: w for w in watchlist.list_watches(owner(ALICE))}[a.id]
    assert summary["last_error"] and "Could not store" in summary["last_error"]


def test_a_watch_whose_check_raises_outright_does_not_stop_the_round(chain, monkeypatch):
    a, b = _two_baselined_watches(chain, monkeypatch)
    inner = watchlist.check_watch
    seen = []

    def check(wid, **k):
        seen.append(wid)
        if wid == a.id:
            raise RuntimeError("unsupported chain")
        return inner(wid, **k)
    monkeypatch.setattr(watchlist, "check_watch", check)
    watchlist._round(0)
    assert seen == [a.id, b.id]


def test_a_failed_store_moves_the_watch_to_the_back_and_starts_the_cooldown(chain, monkeypatch):
    a, b = _two_baselined_watches(chain, monkeypatch)
    real_finish = watchlist._finish_check
    calls = {"n": 0}

    def finish(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("value too long for type character varying(200)")
        return real_finish(*args, **kwargs)
    monkeypatch.setattr(watchlist, "_finish_check", finish)
    with models.session() as s:
        cursor = s.get(models.Watch, a.id).last_seen_block
    chain.transfers = [tx(300, STRANGER)]
    assert watchlist.check_watch(a.id) == []
    assert watchlist.due_watch_ids(0) == [b.id, a.id]
    monkeypatch.setattr(watchlist, "check_watch", lambda wid, **k: [])
    r = TestClient(app).post(f"/watches/{a.id}/check", headers={ownership.OWNER_HEADER: ALICE})
    assert r.status_code == 429
    # The cursor did not move, so the next round tries the same transfer again.
    with models.session() as s:
        assert s.get(models.Watch, a.id).last_seen_block == cursor


def test_a_long_or_control_char_label_is_cleaned_and_cut(chain, monkeypatch):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(1, STRANGER)]
    watchlist.check_watch(w.id, source=chain)
    label = "X" * 300 + "\x00\n<!channel>‮"
    monkeypatch.setattr(watchlist, "_classify", lambda *a, **k: ("exchange", label))
    chain.transfers = [tx(7, STRANGER, h="0xab\x00cd")]
    watchlist.check_watch(w.id, source=chain)
    (alert,) = _alerts_of(w.id)
    limit = models.Alert.__table__.c.counterparty_label.type.length
    assert len(alert.counterparty_label) <= limit
    for text in (alert.counterparty_label, alert.message, alert.tx_hash):
        assert not any(ch in text for ch in "\x00\n‮")
    assert len(alert.tx_hash) <= models.Alert.__table__.c.tx_hash.type.length


# ---------------------------------------------------------------------------
# The baseline is when the watch was set, not the first read that worked
# (r2-g2-watchlist-alerts-0-2). With the watcher off the first read is the
# first Check now, maybe hours later; after a provider outage it is the first
# good read; on Tron an empty history used to store cursor 0 and start again.
# ---------------------------------------------------------------------------
class FullPageChain(FakeChain):
    """A fake whose newest page was full, its oldest record at `oldest`."""

    def __init__(self, oldest):
        super().__init__()
        self.oldest = oldest

    def __call__(self, chain, asset):
        fake = self

        @contextmanager
        def client():
            class C:
                def get_outgoing_transactions(self, address, limit=None):
                    return list(fake.transfers)

                def newest_page_info(self, address):
                    return True, fake.oldest
            yield C()
        return client()


def test_a_cash_out_between_watch_and_first_check_is_alerted(chain):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.transfers = [tx(100, STRANGER), tx(200, BINANCE_14, 25.0, ts=later(600))]
    (alert,) = watchlist.check_watch(w.id, source=chain)
    assert alert["kind"] == "exchange" and "25 ETH" in alert["message"]
    assert watchlist.check_watch(w.id, source=chain) == []


def test_after_a_provider_failure_the_first_good_read_still_alerts_moves_since_the_watch(chain):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    chain.fail = True
    watchlist.check_watch(w.id, source=chain)
    chain.fail = False
    chain.transfers = [tx(100, STRANGER), tx(150, STRANGER, ts=later(300))]
    assert len(watchlist.check_watch(w.id, source=chain)) == 1


def test_a_tron_watch_on_a_wallet_with_no_history_alerts_its_first_cash_out(chain, monkeypatch):
    monkeypatch.setattr(watchlist, "_classify", lambda *a, **k: ("moved", ""))
    w = watchlist.create_watch(owner(ALICE), TRON_WALLET, "tron", "USDT")
    assert watchlist.check_watch(w.id, source=chain) == []  # nothing sent yet
    with models.session() as s:
        assert s.get(models.Watch, w.id).last_seen_block >= 1_000_000_000  # a time, never 0
    chain.transfers = [trc20(0, at=later(60))]
    assert len(watchlist.check_watch(w.id, source=chain)) == 1


def test_an_empty_first_read_then_old_history_raises_nothing(chain):
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    assert watchlist.check_watch(w.id, source=chain) == []  # transiently empty
    chain.transfers = [tx(b, BINANCE_14) for b in range(1, 51)]  # all from 2023
    assert watchlist.check_watch(w.id, source=chain) == []
    with models.session() as s:
        assert s.get(models.Watch, w.id).last_seen_block == 50


def test_a_full_first_page_newer_than_the_watch_says_some_may_be_missing(store):
    full = FullPageChain(oldest=later(5))
    w = watchlist.create_watch(owner(ALICE), WALLET, "ethereum", "ETH")
    full.transfers = [tx(300, STRANGER, ts=later(10))]
    kinds = sorted(a["kind"] for a in watchlist.check_watch(w.id, source=full))
    assert kinds == ["more", "moved"]
    more = [a for a in watchlist.list_alerts(owner(ALICE)) if a["kind"] == "more"]
    assert len(more) == 1 and "re-trace" in more[0]["message"]


def test_a_watch_made_through_the_route_starts_at_the_chain_head(store, monkeypatch):
    monkeypatch.setattr(watchlist, "chain_head", lambda chain, asset: 12_345)
    made = TestClient(app).post("/watches", json={"address": WALLET, "chain": "ethereum"},
                                headers={ownership.OWNER_HEADER: ALICE}).json()
    assert made["baseline_set"] is True
    fake = FakeChain()
    fake.transfers = [tx(12_345, STRANGER, ts=later(-30)), tx(12_346, STRANGER, ts=later(-20))]
    assert len(watchlist.check_watch(made["watch_id"], source=fake)) == 1


def test_the_chain_head_is_one_read_under_a_short_deadline():
    class Source:
        def __init__(self, fail=False):
            self.fail, self.budgets = fail, []

        def __call__(self, chain, asset):
            src = self

            @contextmanager
            def client():
                class C:
                    budget = None

                    def head_block(self):
                        src.budgets.append(self.budget)
                        if src.fail:
                            raise RuntimeError("down")
                        return 777
                yield C()
            return client()
    ok = Source()
    assert watchlist.chain_head("ethereum", "ETH", source=ok) == 777
    assert ok.budgets[0] is not None and ok.budgets[0].remaining() <= watchlist.HEAD_READ_SECONDS
    assert watchlist.chain_head("ethereum", "ETH", source=Source(fail=True)) is None
    assert watchlist.chain_head("tron", "USDT", source=ok) is None  # a Tron cursor is a time


def test_etherscan_reads_the_head_block_in_one_request():
    import httpx

    from app.etherscan_client import EtherscanClient
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x10d4f"})
    client = EtherscanClient(api_key="k", chain_id=1, min_interval=0.0,
                             client=httpx.Client(transport=httpx.MockTransport(handler)))

    @contextmanager
    def source(chain, asset):
        yield client
    assert watchlist.chain_head("ethereum", "ETH", source=source) == 0x10D4F
    assert len(seen) == 1 and seen[0]["module"] == "proxy" and seen[0]["action"] == "eth_blockNumber"
