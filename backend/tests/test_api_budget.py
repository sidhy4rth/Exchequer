"""Tests for the shared request pacer and response cache.

These are the two pieces that decide how long a trace takes on a free tier, so
what matters is that they behave predictably under threads: the cache must not
serve a stale entry past its TTL or lose one to a concurrent write, and the
pacer must widen when the provider refuses and never drop below its floor.
"""
from __future__ import annotations

import threading
import time

import pytest

from app.api_budget import (
    ResponseCache,
    SharedPacer,
    budget_stats,
    get_cache,
    get_pacer,
    reset,
)


# --- ResponseCache ----------------------------------------------------------
def test_cache_returns_stored_value():
    cache = ResponseCache()
    cache.put(("txlist", "0xabc"), [1, 2, 3])
    hit, value = cache.get(("txlist", "0xabc"))
    assert hit is True
    assert value == [1, 2, 3]


def test_cache_miss_is_distinguishable_from_a_cached_none():
    """A provider may legitimately answer None; that must not read as a miss."""
    cache = ResponseCache()
    cache.put("k", None)
    assert cache.get("k") == (True, None)
    assert cache.get("absent") == (False, None)


def test_cache_caches_empty_results():
    """"No transactions here" is an answer, and re-asking it costs a full second."""
    cache = ResponseCache()
    cache.put("k", [])
    hit, value = cache.get("k")
    assert hit is True and value == []


def test_cache_expires_after_ttl():
    cache = ResponseCache(ttl_seconds=0.05)
    cache.put("k", "v")
    assert cache.get("k")[0] is True
    time.sleep(0.08)
    assert cache.get("k")[0] is False


def test_cache_evicts_least_recently_used():
    cache = ResponseCache(max_entries=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")          # 'a' is now the most recently used
    cache.put("c", 3)       # evicts 'b', not 'a'
    assert cache.get("a")[0] is True
    assert cache.get("b")[0] is False
    assert cache.get("c")[0] is True


def test_cache_reports_hit_rate():
    cache = ResponseCache()
    cache.put("k", "v")
    cache.get("k")
    cache.get("missing")
    stats = cache.stats()
    assert stats["hits"] == 1 and stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


def test_cache_is_thread_safe():
    """Concurrent writers must not lose entries or corrupt the LRU order."""
    cache = ResponseCache(max_entries=1000)

    def write(start: int):
        for i in range(start, start + 100):
            cache.put(i, i * 2)

    threads = [threading.Thread(target=write, args=(n * 100,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert cache.stats()["entries"] == 600
    for i in range(600):
        assert cache.get(i) == (True, i * 2)


# --- ResponseCache on disk --------------------------------------------------
def test_a_disk_backed_cache_survives_a_new_instance(tmp_path):
    """The point of the disk layer: a restart must not forget the responses."""
    path = tmp_path / "cache.db"
    first = ResponseCache(path=path)
    key = (("action", "txlist"), ("address", "0xabc"))
    first.put(key, [{"hash": "0x1"}], meta={"sha256": "ab", "retrieved_at": "t", "bytes": 3})
    first.close()

    second = ResponseCache(path=path)
    hit, value = second.get(key)
    assert hit is True and value == [{"hash": "0x1"}]
    # The evidence record for a hit carries the original retrieval, not a new one.
    assert second.meta(key) == {"sha256": "ab", "retrieved_at": "t", "bytes": 3}
    assert second.stats()["hits_from_disk"] == 1
    assert second.stats()["persistent"] is True
    second.close()


def test_a_disk_entry_expires_on_the_same_clock(tmp_path):
    """An entry written before a restart is exactly as old afterwards."""
    path = tmp_path / "cache.db"
    first = ResponseCache(ttl_seconds=0.05, path=path)
    first.put("k", "v")
    first.close()
    time.sleep(0.08)
    second = ResponseCache(ttl_seconds=0.05, path=path)
    assert second.get("k") == (False, None)
    second.close()


def test_a_value_that_cannot_be_written_to_disk_still_caches_in_memory(tmp_path):
    cache = ResponseCache(path=tmp_path / "cache.db")
    cache.put("k", object())  # not JSON
    assert cache.get("k")[0] is True
    assert cache.stats()["entries_on_disk"] == 0
    cache.close()


def test_clear_empties_the_disk_too(tmp_path):
    path = tmp_path / "cache.db"
    cache = ResponseCache(path=path)
    cache.put("k", 1)
    cache.clear()
    cache.close()
    assert ResponseCache(path=path).get("k") == (False, None)


def test_without_a_path_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache = ResponseCache()
    cache.put("k", 1)
    assert cache.stats()["persistent"] is False
    assert list(tmp_path.iterdir()) == []


# --- SharedPacer ------------------------------------------------------------
def test_pacer_spaces_requests():
    pacer = SharedPacer(interval=0.05)
    pacer.wait()                       # first call returns immediately
    start = time.monotonic()
    pacer.wait()
    assert time.monotonic() - start >= 0.04


def test_pacer_widens_on_refusal():
    pacer = SharedPacer(interval=0.1, max_interval=1.0, widen_factor=2.0)
    assert pacer.penalize() == pytest.approx(0.2)
    assert pacer.penalize() == pytest.approx(0.4)


def test_pacer_widening_is_capped():
    """A run of refusals must not stall a trace indefinitely."""
    pacer = SharedPacer(interval=0.1, max_interval=0.3, widen_factor=2.0)
    for _ in range(10):
        pacer.penalize()
    assert pacer.interval == pytest.approx(0.3)


def test_pacer_narrows_on_success_but_not_below_the_floor():
    pacer = SharedPacer(interval=0.5, min_interval=0.5, max_interval=2.0)
    pacer.penalize()
    assert pacer.interval > 0.5
    for _ in range(500):
        pacer.reward()
    assert pacer.interval == pytest.approx(0.5)


def test_pacer_serializes_across_threads():
    """Six threads at a 0.05s interval must take at least five intervals."""
    pacer = SharedPacer(interval=0.05)
    start = time.monotonic()
    threads = [threading.Thread(target=pacer.wait) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert time.monotonic() - start >= 0.05 * 5
    assert pacer.stats()["requests_paced"] == 6


# --- registries -------------------------------------------------------------
def test_registry_returns_one_instance_per_scope():
    """A client is built per trace; the pacer it shares must not be."""
    reset()
    first = get_pacer("etherscan:key", lambda: SharedPacer(interval=0.5))
    second = get_pacer("etherscan:key", lambda: SharedPacer(interval=0.5))
    other = get_pacer("etherscan:other", lambda: SharedPacer(interval=0.5))
    assert first is second
    assert first is not other


def test_budget_stats_reports_every_scope():
    reset()
    get_pacer("p", lambda: SharedPacer(interval=0.5))
    get_cache("c", lambda: ResponseCache())
    stats = budget_stats()
    assert "p" in stats["pacers"]
    assert "c" in stats["caches"]


def test_budget_stats_never_show_the_api_key():
    """/health is public and lists every scope by name."""
    from app.etherscan_client import EtherscanClient

    reset()
    key = "SECRETKEYQWERTYUIOPASDFGHJKLZXCVBN"  # no hex digits: a digest cannot collide
    EtherscanClient(api_key=key, chain_id=1, min_interval=0.0).close()
    names = " ".join(list(budget_stats()["pacers"]) + list(budget_stats()["caches"]))
    assert "etherscan:" in names
    for start in range(len(key) - 3):
        assert key[start:start + 4] not in names


def test_the_disk_cache_drops_expired_rows_while_running_and_shrinks(tmp_path, monkeypatch):
    import sqlite3
    import time as _time

    from app.api_budget import ResponseCache

    path = tmp_path / "cache.db"
    cache = ResponseCache(ttl_seconds=60, path=path)
    monkeypatch.setattr(ResponseCache, "PRUNE_EVERY_PUTS", 50)
    blob = "x" * 20_000
    clock = [1_000_000.0]
    monkeypatch.setattr(_time, "time", lambda: clock[0])
    for i in range(49):
        cache.put(("old", i), blob)
    grown = path.stat().st_size
    clock[0] += 3600  # all of those have expired
    cache.put(("new", 0), blob)  # the 50th write prunes
    rows = sqlite3.connect(path).execute("SELECT COUNT(*) FROM responses").fetchone()[0]
    assert rows == 1
    assert path.stat().st_size < grown / 4


def test_an_old_bloated_cache_file_is_compacted_at_open(tmp_path):
    import sqlite3

    from app.api_budget import ResponseCache

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)  # made the old way: no auto_vacuum
    db.execute("CREATE TABLE responses (key TEXT PRIMARY KEY, stored_at REAL NOT NULL, value TEXT NOT NULL, meta TEXT)")
    db.executemany("INSERT INTO responses VALUES (?, 0, ?, NULL)", [(str(i), "x" * 20_000) for i in range(100)])
    db.commit()
    db.close()
    before = path.stat().st_size
    ResponseCache(ttl_seconds=60, path=path).close()
    assert path.stat().st_size < before / 10
    assert sqlite3.connect(path).execute("PRAGMA auto_vacuum").fetchone()[0] == 2


# --- a cached row must be what was stored (r1-providers-11) ------------------------
def _tamper(path, column: str, value: str) -> None:
    import sqlite3

    db = sqlite3.connect(str(path))
    db.execute(f"UPDATE responses SET {column} = ?", (value,))
    db.commit()
    db.close()


def test_an_edited_disk_row_is_dropped_not_served(tmp_path):
    path = tmp_path / "cache.db"
    first = ResponseCache(path=path)
    key = (("action", "txlist"), ("address", "0xabc"))
    first.put(key, [{"to": "0xreal"}], meta={"sha256": "ab", "retrieved_at": "t", "bytes": 3})
    first.close()
    _tamper(path, "value", '[{"to": "0xdeposit"}]')

    second = ResponseCache(path=path)
    assert second.get(key) == (False, None)
    assert second.stats()["integrity_drops"] == 1
    assert second.stats()["entries_on_disk"] == 0  # the row is gone
    second.close()


def test_an_edited_provider_hash_is_dropped_too(tmp_path):
    path = tmp_path / "cache.db"
    first = ResponseCache(path=path)
    first.put("k", [1], meta={"sha256": "ab", "retrieved_at": "t", "bytes": 3})
    first.close()
    _tamper(path, "meta", '{"sha256": "cd", "retrieved_at": "t", "bytes": 3}')
    second = ResponseCache(path=path)
    assert second.get("k") == (False, None)
    second.close()


def test_a_row_from_before_the_check_is_a_miss(tmp_path):
    import sqlite3

    path = tmp_path / "cache.db"
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE responses (key TEXT PRIMARY KEY, stored_at REAL NOT NULL, value TEXT NOT NULL, meta TEXT)")
    db.execute("INSERT INTO responses VALUES (?, ?, ?, ?)", ('"k"', time.time(), "[1]", None))
    db.commit()
    db.close()
    cache = ResponseCache(path=path)
    assert cache.get("k") == (False, None)
    cache.put("k", [2])
    assert ResponseCache(path=path).get("k") == (True, [2])
    cache.close()


def test_get_with_meta_returns_both_under_one_look(tmp_path):
    cache = ResponseCache(max_entries=1, path=tmp_path / "cache.db")
    cache.put("a", 1, meta={"sha256": "ab", "retrieved_at": "t", "bytes": 1})
    cache.put("b", 2)  # evicts "a" from memory; the disk still has it
    assert cache.get_with_meta("a") == (True, 1, {"sha256": "ab", "retrieved_at": "t", "bytes": 1})
    assert cache.get_with_meta("missing") == (False, None, None)
    cache.close()


def test_an_edit_that_recomputes_a_plain_hash_is_still_dropped(tmp_path, monkeypatch):
    # The code is public: anyone who can write the cache file can recompute a
    # plain SHA-256 over an edited row. With the signing seed in the
    # environment (not on the disk beside the cache), the row check is keyed.
    import base64
    import hashlib
    import sqlite3

    monkeypatch.setenv("EXCHEQUER_SIGNING_KEY", base64.b64encode(bytes(range(32))).decode())
    path = tmp_path / "cache.db"
    first = ResponseCache(path=path)
    meta = {"sha256": "ab", "retrieved_at": "t", "bytes": 3}
    first.put("k", [{"to": "0xreal"}], meta=meta)
    first.close()

    db = sqlite3.connect(str(path))
    value, meta_text = '[{"to": "0xdeposit"}]', db.execute("SELECT meta FROM responses").fetchone()[0]
    forged = hashlib.sha256(f"{value}\n{meta_text}".encode()).hexdigest()
    db.execute("UPDATE responses SET value = ?, value_sha256 = ?", (value, forged))
    db.commit()
    db.close()

    second = ResponseCache(path=path)
    assert second.get("k") == (False, None)
    assert second.stats()["integrity_drops"] == 1
    second.close()


def test_rows_written_under_another_signing_seed_are_misses(tmp_path, monkeypatch):
    import base64

    path = tmp_path / "cache.db"
    monkeypatch.setenv("EXCHEQUER_SIGNING_KEY", base64.b64encode(bytes(range(32))).decode())
    first = ResponseCache(path=path)
    first.put("k", [1])
    first.close()
    assert ResponseCache(path=path).get("k") == (True, [1])
    monkeypatch.setenv("EXCHEQUER_SIGNING_KEY", base64.b64encode(bytes(range(1, 33))).decode())
    assert ResponseCache(path=path).get("k") == (False, None)


# --- a row is bound to its key and its times (r1-providers-11, round 2) ----------
# The row check covered only the value and meta text, so a genuine row copied
# onto another key passed: the verifier moved TronScan's "Binance-Hot 3" tag
# row onto an innocent address, and it was served for that address.
SEED_ENV = "EXCHEQUER_SIGNING_KEY"


def _seeded(monkeypatch) -> None:
    import base64

    monkeypatch.setenv(SEED_ENV, base64.b64encode(bytes(range(32))).decode())


def _copy_row(path, source_key: str, target_key: str) -> None:
    import sqlite3

    db = sqlite3.connect(str(path))
    row = db.execute("SELECT stored_at, value, meta, expires_at, value_sha256 FROM responses WHERE key = ?",
                     (source_key,)).fetchone()
    db.execute("INSERT OR REPLACE INTO responses (key, stored_at, value, meta, expires_at, value_sha256) "
               "VALUES (?, ?, ?, ?, ?, ?)", (target_key, *row))
    db.commit()
    db.close()


@pytest.mark.parametrize("keyed", [True, False])
def test_a_genuine_row_moved_onto_another_key_is_dropped(tmp_path, monkeypatch, keyed):
    if keyed:
        _seeded(monkeypatch)
    else:
        monkeypatch.delenv(SEED_ENV, raising=False)
    path = tmp_path / "cache.db"
    first = ResponseCache(path=path)
    binance, innocent = ("tronscan-account", "TBinanceHotWallet"), ("tronscan-account", "TInnocentPerson")
    first.put(binance, {"tag": "Binance-Hot 3"}, meta={"sha256": "aa", "retrieved_at": "t", "bytes": 3})
    first.close()
    _copy_row(path, ResponseCache._disk_key(binance), ResponseCache._disk_key(innocent))

    second = ResponseCache(path=path)
    assert second.get(innocent) == (False, None)
    assert second.stats()["integrity_drops"] == 1
    assert second.get(binance) == (True, {"tag": "Binance-Hot 3"})  # the genuine row still serves
    second.close()


@pytest.mark.parametrize("column", ["stored_at", "expires_at"])
def test_a_row_whose_times_were_changed_is_dropped(tmp_path, monkeypatch, column):
    # Moving stored_at or expires_at forward would keep an old answer alive
    # past its time-to-live, or make it look newer than it is.
    import sqlite3

    _seeded(monkeypatch)
    path = tmp_path / "cache.db"
    first = ResponseCache(path=path)
    first.put("k", [1], meta={"sha256": "ab", "retrieved_at": "t", "bytes": 3})
    first.close()
    db = sqlite3.connect(str(path))
    db.execute(f"UPDATE responses SET {column} = {column} + 60")
    db.commit()
    db.close()

    second = ResponseCache(path=path)
    assert second.get("k") == (False, None)
    assert second.stats()["integrity_drops"] == 1
    second.close()


def test_a_row_checked_under_the_old_scheme_is_a_miss_and_is_fetched_again(tmp_path, monkeypatch):
    # Rows written before the key and times were bound carry an HMAC over the
    # value and meta alone. They read as misses (and are deleted), never as a
    # crash, and the next answer is stored under the new scheme.
    import hashlib
    import hmac
    import sqlite3

    from app.api_budget import _row_key

    _seeded(monkeypatch)
    path = tmp_path / "cache.db"
    first = ResponseCache(path=path)
    first.put("k", [1], meta={"sha256": "ab", "retrieved_at": "t", "bytes": 3})
    first.close()
    db = sqlite3.connect(str(path))
    value, meta_text = db.execute("SELECT value, meta FROM responses").fetchone()
    old = hmac.new(_row_key(), f"{value}\n{meta_text}".encode(), hashlib.sha256).hexdigest()
    db.execute("UPDATE responses SET value_sha256 = ?", (old,))
    db.commit()
    db.close()

    second = ResponseCache(path=path)
    assert second.get("k") == (False, None)
    assert second.stats()["entries_on_disk"] == 0
    second.put("k", [2])
    second.close()
    assert ResponseCache(path=path).get("k") == (True, [2])
