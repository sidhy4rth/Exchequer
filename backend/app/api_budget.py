"""Process-wide API budget: one pacer and one response cache per credential.

Both pieces exist for the same reason, which measurement made plain. On
Etherscan's free tier a trace is not slow because of anything Exchequer
computes -- the graph, the pattern rules and the scoring together take
milliseconds. It is slow because it waits on the provider, and the provider
answers roughly two useful requests per second no matter how hard it is asked.
Pushing harder does not raise that ceiling; it converts successful responses
into "max rate limit reached", each of which costs an exponential backoff and
makes the trace *slower*.

So the only lever that shortens a trace is making fewer requests. Hence:

  ResponseCache
        The same address is asked for repeatedly -- across the two traversal
        directions (both read the provider's one combined transaction list),
        across overlapping traces, and across every re-run of the same demo
        address. None of those repeats need to touch the network. The daily
        quota is nowhere near the constraint (a trace costs ~35 of 100,000
        calls/day), so what the cache saves is *seconds*, not budget.

  SharedPacer
        A client used to be built per trace, each with its own throttle. Two
        traces at once therefore paced independently and together doubled the
        request rate, which is exactly how a free key gets rate-limited. The
        limit is enforced per credential by the provider, so the pacer that
        respects it has to be shared per credential too.

The pacer is adaptive. A fixed interval cannot be right for a limit that is
enforced in bursts: measured against the live free tier, even a nominally safe
2.9 req/s drew rate-limit responses. So it widens on refusal and recovers
slowly on success, settling near whatever the key is actually allowed rather
than at whatever constant was guessed in advance.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Hashable

logger = logging.getLogger(__name__)

# The interval a refusal widens to when pacing was disabled entirely. Multiplying
# zero by any factor is still zero, so a client configured with no spacing -- the
# tests, or a deployment trusting a paid plan -- could otherwise be refused
# forever without ever slowing down.
MIN_PENALTY_INTERVAL = 0.05


class ResponseCache:
    """Thread-safe TTL + LRU cache for provider responses, optionally on disk.

    Keys are whatever the caller can hash -- in practice a normalized tuple of
    request parameters with the API key excluded, so two different credentials
    asking the same question share one entry.

    On-chain history is append-only, so a stale entry can only ever be missing
    the newest transactions, never wrong about the old ones. That is what makes
    a TTL acceptable here at all. Every cached answer is recorded in the case's
    evidence manifest with the time it was originally retrieved, so how old the
    data was is never hidden from the report.

    With `path` set, every entry is also written to a SQLite file and read back
    on a miss, so the cache survives a restart. The memory layer is what makes
    a hit cheap; the disk layer is what makes a hosted instance answer the
    demo addresses in seconds after a redeploy instead of re-fetching forty
    responses at two a second. Only JSON-serialisable values go to disk; any
    other value stays in memory alone.
    """

    def __init__(
        self,
        ttl_seconds: float = 600.0,
        max_entries: int = 2048,
        path: "str | Path | None" = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[Hashable, tuple[float, Any, dict | None]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._disk_hits = 0
        self.path = Path(path) if path else None
        self._db: sqlite3.Connection | None = None
        if self.path is not None:
            self._open_disk()

    # -- disk layer ---------------------------------------------------------
    def _open_disk(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(str(self.path), check_same_thread=False)
            db.execute(
                "CREATE TABLE IF NOT EXISTS responses ("
                "key TEXT PRIMARY KEY, stored_at REAL NOT NULL, "
                "value TEXT NOT NULL, meta TEXT)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS responses_stored_at ON responses(stored_at)")
            # Expired rows are dropped at open rather than on every read.
            db.execute("DELETE FROM responses WHERE stored_at < ?", (time.time() - self.ttl_seconds,))
            db.commit()
            self._db = db
            logger.info("Provider response cache on disk at %s", self.path)
        except (OSError, sqlite3.Error) as exc:
            # A cache that cannot be persisted is still a cache. Say so and go on.
            logger.warning("Response cache will not persist (%s): %s", self.path, exc)
            self._db = None

    @staticmethod
    def _disk_key(key: Hashable) -> str:
        return json.dumps(key, sort_keys=True, default=str)

    def _disk_get(self, key: Hashable) -> tuple[float, Any, dict | None] | None:
        """(age_seconds, value, meta) for a live row, or None. Called under the lock."""
        if self._db is None:
            return None
        try:
            row = self._db.execute(
                "SELECT stored_at, value, meta FROM responses WHERE key = ?", (self._disk_key(key),)
            ).fetchone()
        except sqlite3.Error as exc:
            logger.warning("Response cache read failed: %s", exc)
            return None
        if row is None:
            return None
        stored_at, value_text, meta_text = row
        age = time.time() - stored_at
        if age > self.ttl_seconds:
            return None
        try:
            return age, json.loads(value_text), json.loads(meta_text) if meta_text else None
        except ValueError:
            return None

    def _disk_put(self, key: Hashable, value: Any, meta: dict | None) -> None:
        """Called under the lock."""
        if self._db is None:
            return
        try:
            value_text = json.dumps(value)
            meta_text = json.dumps(meta) if meta is not None else None
        except (TypeError, ValueError):
            return  # not representable on disk; memory still has it
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO responses (key, stored_at, value, meta) VALUES (?, ?, ?, ?)",
                (self._disk_key(key), time.time(), value_text, meta_text),
            )
            self._db.commit()
        except sqlite3.Error as exc:
            logger.warning("Response cache write failed: %s", exc)

    def _disk_count(self) -> int:
        if self._db is None:
            return 0
        try:
            return int(self._db.execute("SELECT COUNT(*) FROM responses").fetchone()[0])
        except sqlite3.Error:
            return 0

    # -- public -------------------------------------------------------------
    def get(self, key: Hashable) -> tuple[bool, Any]:
        """Return (hit, value). A miss and a cached None are distinguishable."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                stored_at, value, _meta = entry
                if time.monotonic() - stored_at <= self.ttl_seconds:
                    self._entries.move_to_end(key)
                    self._hits += 1
                    return True, value
                del self._entries[key]
            # Not in memory: the disk may have it from before a restart.
            found = self._disk_get(key)
            if found is None:
                self._misses += 1
                return False, None
            age, value, meta = found
            # Promote to memory with its original age, so it expires on the
            # same schedule it would have had the process never restarted.
            self._entries[key] = (time.monotonic() - age, value, meta)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            self._hits += 1
            self._disk_hits += 1
            return True, value

    def meta(self, key: Hashable) -> dict | None:
        """The retrieval metadata stored with a live entry (hash, time, size),
        so a cache hit can be recorded as evidence with its original values."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                return entry[2]
            found = self._disk_get(key)
            return found[2] if found else None

    def put(self, key: Hashable, value: Any, meta: dict | None = None) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic(), value, meta)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            self._disk_put(key, value, meta)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._hits = 0
            self._misses = 0
            self._disk_hits = 0
            if self._db is not None:
                try:
                    self._db.execute("DELETE FROM responses")
                    self._db.commit()
                except sqlite3.Error as exc:
                    logger.warning("Response cache clear failed: %s", exc)

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._entries),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total else 0.0,
                "ttl_seconds": self.ttl_seconds,
                # The disk layer: where it is, how much it holds, and how many
                # hits it served that memory could not (after a restart).
                "persistent": self._db is not None,
                "path": str(self.path) if self.path else None,
                "entries_on_disk": self._disk_count(),
                "hits_from_disk": self._disk_hits,
            }


class SharedPacer:
    """Adaptive request pacer shared by every client using one credential.

    `wait()` blocks until the next request may be sent. `penalize()` reports a
    rate-limit refusal and widens the interval; `reward()` reports a success and
    lets it narrow again.

    The interval only ever moves between `min_interval` and `max_interval`, so
    a run of refusals cannot stall a trace indefinitely and a run of successes
    cannot push it back into the range that caused the refusals in the first
    place.
    """

    def __init__(
        self,
        interval: float,
        min_interval: float | None = None,
        max_interval: float | None = None,
        widen_factor: float = 1.5,
        narrow_factor: float = 0.97,
    ) -> None:
        self.initial_interval = interval
        self.min_interval = min_interval if min_interval is not None else interval
        self.max_interval = max_interval if max_interval is not None else interval * 6
        self.widen_factor = widen_factor
        self.narrow_factor = narrow_factor

        self._interval = interval
        self._last_request_at = 0.0
        self._lock = threading.Lock()
        self._waits = 0
        self._slept = 0.0
        self._penalties = 0

    @property
    def interval(self) -> float:
        with self._lock:
            return self._interval

    def wait(self) -> None:
        """Block until the shared schedule permits the next request.

        The sleep happens under the lock deliberately. The point of the pacer is
        that requests leave in single file at a known spacing; releasing the lock
        before sleeping would let every waiting thread compute the same "it is my
        turn" instant and fire together, which is the burst the provider refuses.
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            if elapsed < self._interval:
                delay = self._interval - elapsed
                time.sleep(delay)
                self._slept += delay
            self._last_request_at = time.monotonic()
            self._waits += 1

    def penalize(self) -> float:
        """Record a rate-limit refusal and widen the interval. Returns the new one."""
        with self._lock:
            self._penalties += 1
            previous = self._interval
            widened = max(self._interval, MIN_PENALTY_INTERVAL) * self.widen_factor
            self._interval = min(widened, max(self.max_interval, MIN_PENALTY_INTERVAL))
            if self._interval > previous:
                logger.info(
                    "Rate limited: widening request interval %.3fs -> %.3fs",
                    previous, self._interval,
                )
            return self._interval

    def reward(self) -> None:
        """Record a success and let the interval drift back toward the floor."""
        with self._lock:
            if self._interval > self.min_interval:
                self._interval = max(self._interval * self.narrow_factor, self.min_interval)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "interval": round(self._interval, 3),
                "min_interval": self.min_interval,
                "max_interval": round(self.max_interval, 3),
                "requests_paced": self._waits,
                "seconds_slept": round(self._slept, 2),
                "rate_limit_penalties": self._penalties,
            }


# --- registries -------------------------------------------------------------
# Clients are constructed per trace, so neither the pacer nor the cache can live
# on the instance. They are looked up by a name the caller chooses -- in practice
# the provider plus the credential, because that is the scope the provider
# actually enforces its limit over.
_pacers: dict[str, SharedPacer] = {}
_caches: dict[str, ResponseCache] = {}
_registry_lock = threading.Lock()


def get_pacer(name: str, factory: Callable[[], SharedPacer]) -> SharedPacer:
    with _registry_lock:
        pacer = _pacers.get(name)
        if pacer is None:
            pacer = _pacers[name] = factory()
        return pacer


def get_cache(name: str, factory: Callable[[], ResponseCache]) -> ResponseCache:
    with _registry_lock:
        cache = _caches.get(name)
        if cache is None:
            cache = _caches[name] = factory()
        return cache


def budget_stats() -> dict[str, Any]:
    """Everything the /health endpoint needs to explain a slow trace."""
    with _registry_lock:
        return {
            "pacers": {name: p.stats() for name, p in _pacers.items()},
            "caches": {name: c.stats() for name, c in _caches.items()},
        }


def reset() -> None:
    """Drop all shared state. Used by the tests to keep cases independent."""
    with _registry_lock:
        _pacers.clear()
        for cache in _caches.values():
            cache.close()
        _caches.clear()
