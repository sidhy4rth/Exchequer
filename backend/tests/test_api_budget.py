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
