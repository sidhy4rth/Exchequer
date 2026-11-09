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

import contextlib
import contextvars
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from contextvars import ContextVar
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Hashable

logger = logging.getLogger(__name__)

# The interval a refusal widens to when pacing was disabled entirely. Multiplying
# zero by any factor is still zero, so a client configured with no spacing -- the
# tests, or a deployment trusting a paid plan -- could otherwise be refused
# forever without ever slowing down.
MIN_PENALTY_INTERVAL = 0.05


# Set by fresh_reads(): the watchlist must see transfers newer than the cache.
_fresh: ContextVar[bool] = ContextVar("fresh_reads", default=False)


@contextmanager
def fresh_reads():
    """Skip cached answers in this context (their replacements are still cached).

    A trace is happy with a day-old answer -- history only grows at the end.
    The watchlist exists to notice the end growing, so it must not be."""
    token = _fresh.set(True)
    try:
        yield
    finally:
        _fresh.reset(token)


def _row_key() -> bytes:
    """The key the disk rows are checked with: derived from the report-signing
    seed when it comes from the environment, so nothing on the disk beside the
    cache holds it. Without one it is empty, and the check catches corruption
    and careless edits only -- but then the signing key is itself a file on
    that disk, and whoever can write the cache can read it."""
    from .signing import _seed_bytes

    seed = os.getenv("EXCHEQUER_SIGNING_KEY", "").strip()
    raw = _seed_bytes(seed) if seed else None
    return hmac.new(raw, b"exchequer provider-cache rows v1", hashlib.sha256).digest() if raw else b""


class ResponseTooLarge(Exception):
    """A provider's body passed the size cap while it was being read."""

    def __init__(self, limit: int, reason: str | None = None) -> None:
        super().__init__(reason or f"response larger than {limit} bytes")
        self.limit = limit


# Decoded bytes one decompression step may produce: the peak is the cap plus this.
_DECODE_STEP = 256 * 1024


def _decoder(encoding: str) -> Any:
    """A bounded decoder for a Content-Encoding, None for an uncompressed body."""
    import zlib

    name = encoding.strip().lower()
    if name in ("", "identity"):
        return None
    if name in ("gzip", "x-gzip"):
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if name == "deflate":
        return zlib.decompressobj()
    raise ResponseTooLarge(0, f"response in an encoding Exchequer did not ask for ({name[:40]})")


def read_capped(client: Any, method: str, url: str, max_bytes: int | None = None, **kwargs: Any) -> Any:
    """`client.request(method, url, **kwargs)`, read to at most `max_bytes`.

    httpx buffers a whole body before anyone looks at it, and no provider
    promises a size: one page of 200 transactions with large calldata was 52 MB.
    This streams the body and stops with ResponseTooLarge past the cap (by
    Content-Length at once when the server states one). The returned response
    holds the decoded body, so `.json()`, `.text` and `.content` work as before.

    It asks for an uncompressed body. A server that compresses anyway is
    decoded here, never more than the cap at a time: httpx inflated each
    whole raw chunk before the cap saw it, so 69 kB of gzipped zeros peaked
    at 131 MB in one read (r1-providers-1).
    """
    import zlib

    import httpx

    from . import config

    limit = max_bytes or config.PROVIDER_MAX_RESPONSE_BYTES
    kwargs["headers"] = {**dict(kwargs.get("headers") or {}), "Accept-Encoding": "identity"}
    with client.stream(method, url, **kwargs) as response:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise ResponseTooLarge(limit)
        decoder = _decoder(response.headers.get("content-encoding", ""))
        chunks, size, wire = [], 0, 0

        def take(piece: bytes) -> None:
            nonlocal size
            size += len(piece)
            if size > limit:
                raise ResponseTooLarge(limit)
            if piece:
                chunks.append(piece)

        if response.is_stream_consumed:
            # An in-memory body (a test transport): httpx read it already.
            take(response.content)
            decoder = None
        try:
            for raw in (() if response.is_stream_consumed else response.iter_raw()):
                wire += len(raw)
                if wire > limit:
                    raise ResponseTooLarge(limit)
                if decoder is None:
                    take(raw)
                    continue
                data = raw
                while data:  # at most what is left under the cap, one step at a time
                    take(decoder.decompress(data, min(limit - size + 1, _DECODE_STEP)))
                    data = decoder.unconsumed_tail
            if decoder is not None:
                take(decoder.flush())
        except zlib.error as exc:
            raise ResponseTooLarge(0, f"compressed response could not be read: {exc}") from exc
    # The body is already decoded: drop the headers that describe the wire form.
    headers = [(k, v) for k, v in response.headers.multi_items()
               if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
    return httpx.Response(response.status_code, headers=headers, content=b"".join(chunks),
                          request=response.request)


class ResponseCache:
    """Thread-safe TTL + LRU cache for provider responses, optionally on disk.

    Keys are whatever the caller can hash -- in practice a normalized tuple of
    request parameters with the API key excluded, so two different credentials
    asking the same question share one entry.

    On-chain history is append-only, so a stale entry can only ever be missing
    the newest transactions, never wrong about the old ones. That is what makes
    a TTL acceptable here at all -- for a closed block range. A question about
    the chain's tip (the newest page, a balance, "nothing here yet") is a
    moving target, so `put` takes a TTL per entry and the caller gives those
    minutes or nothing. Every cached answer is recorded in the case's evidence
    manifest with the time it was originally retrieved, so how old the data
    was is never hidden from the report.

    With `path` set, every entry is also written to a SQLite file and read back
    on a miss, so the cache survives a restart. The memory layer is what makes
    a hit cheap; the disk layer is what makes a hosted instance answer the
    demo addresses in seconds after a redeploy instead of re-fetching forty
    responses at two a second. Only JSON-serialisable values go to disk; any
    other value stays in memory alone.

    Both layers are bounded in bytes, not only in entries: an entry is held as
    its JSON text, so its size is known exactly, and the oldest entries go once
    the memory layer passes `max_bytes` or the file passes `max_disk_bytes`. A
    count alone let 2,048 raw pages pin ~0.7 GB on a 512 MB instance. The JSON
    is written outside the locks, and memory and disk have a lock each, so a
    large write never stalls another trace's lookups.
    """

    def __init__(
        self,
        ttl_seconds: float = 600.0,
        max_entries: int = 2048,
        path: "str | Path | None" = None,
        max_bytes: int | None = None,
        max_disk_bytes: int | None = None,
    ) -> None:
        from . import config

        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.max_bytes = max_bytes if max_bytes is not None else config.CACHE_MEMORY_BYTES
        self.max_disk_bytes = max_disk_bytes if max_disk_bytes is not None else config.CACHE_DISK_BYTES
        # key -> (stored_at, JSON text or the value itself, meta, size in bytes, ttl)
        self._entries: OrderedDict[Hashable, tuple[float, Any, dict | None, int, float]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self._db_lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._disk_hits = 0
        self._integrity_drops = 0
        self._row_key = _row_key()
        self.path = Path(path) if path else None
        self._db: sqlite3.Connection | None = None
        self._puts = 0
        self._disk_bytes = 0  # an upper estimate between prunes
        if self.path is not None:
            self._open_disk()

    # -- disk layer ---------------------------------------------------------
    def _open_disk(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(str(self.path), check_same_thread=False)
            # Only takes effect on a new file (or at the next VACUUM): lets the
            # file give back the pages expired rows leave behind.
            db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS responses ("
                "key TEXT PRIMARY KEY, stored_at REAL NOT NULL, "
                "value TEXT NOT NULL, meta TEXT, expires_at REAL)"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(responses)")}
            if "expires_at" not in columns:
                # A file from before per-entry TTLs: its rows may be tip answers
                # held for a day. The cache is disposable; start it again.
                db.execute("ALTER TABLE responses ADD COLUMN expires_at REAL")
                db.execute("DELETE FROM responses")
            db.execute("CREATE INDEX IF NOT EXISTS responses_stored_at ON responses(stored_at)")
            if "value_sha256" not in {row[1] for row in db.execute("PRAGMA table_info(responses)")}:
                # A file from before the check: its rows have no hash, so
                # each reads as a miss and is fetched (and stored) afresh.
                db.execute("ALTER TABLE responses ADD COLUMN value_sha256 TEXT")
            db.commit()
            self._prune_disk(db, at_open=True)
            self._db = db
            logger.info("Provider response cache on disk at %s", self.path)
        except (OSError, sqlite3.Error) as exc:
            # A cache that cannot be persisted is still a cache. Say so and go on.
            logger.warning("Response cache will not persist (%s): %s", self.path, exc)
            self._db = None

    # Expired rows are dropped at open and again every this many writes. A
    # server that stays up otherwise kept every response it ever cached: a
    # 24-hour cache had grown its file to 420 MB.
    PRUNE_EVERY_PUTS = 500

    def _prune_disk(self, db: sqlite3.Connection, at_open: bool = False) -> None:
        """Delete expired rows, then the oldest until the file is under its
        byte cap, and give their space back to the filesystem.

        Deleting alone never shrinks a SQLite file. A file made before
        auto_vacuum was set is compacted once, at open, when most of it is
        free pages; after that the incremental vacuum keeps it in step."""
        try:
            now = time.time()
            db.execute("DELETE FROM responses WHERE (expires_at IS NULL AND stored_at < ?) OR expires_at < ?",
                       (now - self.ttl_seconds, now))
            total = db.execute("SELECT COALESCE(SUM(LENGTH(value)), 0) FROM responses").fetchone()[0]
            if self.max_disk_bytes and total > self.max_disk_bytes:
                rows = db.execute("SELECT key, LENGTH(value) FROM responses ORDER BY stored_at").fetchall()
                doomed = []
                for key, size in rows:
                    if total <= self.max_disk_bytes * 0.9:  # some headroom before the next prune
                        break
                    doomed.append((key,))
                    total -= size
                db.executemany("DELETE FROM responses WHERE key = ?", doomed)
            db.commit()
            self._disk_bytes = int(total)
            mode = db.execute("PRAGMA auto_vacuum").fetchone()[0]
            if mode == 2:
                # Frees one page per step, so it must be read to the end.
                db.execute("PRAGMA incremental_vacuum").fetchall()
                db.commit()
            elif at_open:
                free = db.execute("PRAGMA freelist_count").fetchone()[0]
                pages = db.execute("PRAGMA page_count").fetchone()[0]
                if pages and free * 4 >= pages:
                    db.execute("VACUUM")  # also switches the file to incremental
        except sqlite3.Error as exc:
            logger.warning("Response cache prune failed: %s", exc)

    @staticmethod
    def _disk_key(key: Hashable) -> str:
        return json.dumps(key, sort_keys=True, default=str)

    def _row_sha256(self, disk_key: str, stored_at: float, expires_at: float | None,
                    value_text: str, meta_text: str | None) -> str:
        """HMAC-SHA256 (keyed by _row_key) over the whole row: the key it answers,
        when it was stored and when it expires, the value the trace will use and
        the provider hash the evidence manifest will report for it. So a genuine
        row copied onto another key, or with its times moved, no longer matches;
        and a plain hash anyone could recompute after an edit is not enough.
        The parts are JSON-encoded as a list so no two rows read the same."""
        message = json.dumps([disk_key, stored_at, expires_at, value_text, meta_text])
        return hmac.new(self._row_key, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def _disk_get(self, key: Hashable) -> tuple[float, str, dict | None, float] | None:
        """(age_seconds, JSON text, meta, ttl) for a live row, or None.

        A row that no longer matches the hash written with it was edited,
        corrupted or moved onto another key on disk: it is deleted and treated
        as a miss, so a trace never uses data its evidence manifest does not
        describe. A row from before the current check is deleted the same way."""
        disk_key = self._disk_key(key)
        with self._db_lock:
            if self._db is None:
                return None
            try:
                row = self._db.execute(
                    "SELECT stored_at, value, meta, expires_at, value_sha256 FROM responses WHERE key = ?",
                    (disk_key,),
                ).fetchone()
            except sqlite3.Error as exc:
                logger.warning("Response cache read failed: %s", exc)
                return None
            if row is None:
                return None
            stored_at, value_text, meta_text, expires_at, digest = row
            if (not isinstance(stored_at, float) or not isinstance(expires_at, (float, type(None)))
                    or not isinstance(value_text, str) or not isinstance(meta_text, (str, type(None)))):
                # Only an edit stores other types here: read it as expired.
                return None
            ttl = (expires_at - stored_at) if expires_at is not None else self.ttl_seconds
            if time.time() - stored_at > ttl:
                return None
            expected = self._row_sha256(disk_key, stored_at, expires_at, value_text, meta_text)
            if not isinstance(digest, str) or not hmac.compare_digest(digest, expected):
                # A row checked under the older scheme (value and meta only) lands
                # here too, once: it is dropped and fetched afresh like any other.
                self._integrity_drops += 1
                # Counted, never named: the request text has no place in the log.
                logger.warning("A response cache row did not match its hash and was dropped (%d this run)",
                               self._integrity_drops)
                try:
                    self._db.execute("DELETE FROM responses WHERE key = ?", (disk_key,))
                    self._db.commit()
                except sqlite3.Error as exc:
                    logger.warning("Response cache delete failed: %s", exc)
                return None
        age = time.time() - stored_at
        try:
            return age, value_text, json.loads(meta_text) if meta_text else None, ttl
        except ValueError:
            return None

    def _disk_drop(self, key: Hashable) -> None:
        with self._db_lock:
            if self._db is None:
                return
            try:
                disk_key = self._disk_key(key)
                # Most such keys were never stored: no write, and no commit, for those.
                if self._db.execute("SELECT 1 FROM responses WHERE key = ?", (disk_key,)).fetchone():
                    self._db.execute("DELETE FROM responses WHERE key = ?", (disk_key,))
                    self._db.commit()
            except sqlite3.Error as exc:
                logger.warning("Response cache delete failed: %s", exc)

    def _disk_put(self, key: Hashable, value_text: str, meta_text: str | None, ttl: float) -> None:
        with self._db_lock:
            if self._db is None:
                return
            try:
                now = time.time()
                disk_key, expires_at = self._disk_key(key), now + ttl
                self._db.execute(
                    "INSERT OR REPLACE INTO responses (key, stored_at, value, meta, expires_at, value_sha256) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (disk_key, now, value_text, meta_text, expires_at,
                     self._row_sha256(disk_key, now, expires_at, value_text, meta_text)),
                )
                self._db.commit()
            except sqlite3.Error as exc:
                logger.warning("Response cache write failed: %s", exc)
                return
            self._puts += 1
            self._disk_bytes += len(value_text)
            over = bool(self.max_disk_bytes) and self._disk_bytes > self.max_disk_bytes
            if over or self._puts % self.PRUNE_EVERY_PUTS == 0:
                self._prune_disk(self._db)

    def _disk_count(self) -> int:
        with self._db_lock:
            if self._db is None:
                return 0
            try:
                return int(self._db.execute("SELECT COUNT(*) FROM responses").fetchone()[0])
            except sqlite3.Error:
                return 0

    # -- memory layer -------------------------------------------------------
    def _forget(self, key: Hashable) -> None:
        """Drop one memory entry. Under the lock."""
        old = self._entries.pop(key, None)
        if old is not None:
            self._bytes -= old[3]

    def _remember(self, key: Hashable, stored_at: float, held: Any, meta: dict | None, size: int,
                  ttl: float) -> None:
        """Insert as most recent and evict the oldest past either bound. Under the lock."""
        self._forget(key)
        if size > self.max_bytes:
            return  # larger than the whole budget: disk only
        self._entries[key] = (stored_at, held, meta, size, ttl)
        self._bytes += size
        while self._entries and (len(self._entries) > self.max_entries or self._bytes > self.max_bytes):
            _, evicted = self._entries.popitem(last=False)
            self._bytes -= evicted[3]

    @staticmethod
    def _decode(held: Any) -> Any:
        return json.loads(held) if isinstance(held, str) else held.value

    # -- public -------------------------------------------------------------
    def get(self, key: Hashable) -> tuple[bool, Any]:
        """Return (hit, value). A miss and a cached None are distinguishable.

        Each hit is decoded afresh from the stored JSON, so a caller cannot
        change what the next one reads. Inside `fresh_reads()` every lookup
        misses, so the provider is asked and the answer replaces what was
        cached."""
        hit, value, _meta = self.get_with_meta(key)
        return hit, value

    def get_with_meta(self, key: Hashable) -> tuple[bool, Any, dict | None]:
        """(hit, value, meta) in one look, so a hit is always recorded as
        evidence with its own retrieval metadata: asking get() then meta()
        could lose the entry in between, and the trace would then use data
        its manifest does not list."""
        if _fresh.get():
            return False, None, None
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                stored_at, held, meta, _size, ttl = entry
                if time.monotonic() - stored_at <= ttl:
                    self._entries.move_to_end(key)
                    self._hits += 1
                    return True, self._decode(held), meta
                self._forget(key)
        # Not in memory: the disk may have it from before a restart.
        found = self._disk_get(key)
        with self._lock:
            if found is None:
                self._misses += 1
                return False, None, None
            age, text, meta, ttl = found
            # Promote to memory with its original age, so it expires on the
            # same schedule it would have had the process never restarted.
            self._remember(key, time.monotonic() - age, text, meta, len(text), ttl)
            self._hits += 1
            self._disk_hits += 1
        return True, json.loads(text), meta

    def meta(self, key: Hashable) -> dict | None:
        """The retrieval metadata stored with a live entry (hash, time, size),
        so a cache hit can be recorded as evidence with its original values."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                return entry[2]
        found = self._disk_get(key)
        return found[2] if found else None

    def put(self, key: Hashable, value: Any, meta: dict | None = None, ttl: float | None = None) -> None:
        """Store `value` for `ttl` seconds (the cache's own TTL when None). A TTL
        of 0 stores nothing and drops what an earlier answer left."""
        ttl = self.ttl_seconds if ttl is None else ttl
        if ttl <= 0:
            with self._lock:
                self._forget(key)
            self._disk_drop(key)
            return
        # Serialised before either lock is taken: a large page must not hold up
        # every other lookup while it is written.
        try:
            text: str | None = json.dumps(value)
            meta_text = json.dumps(meta) if meta is not None else None
        except (TypeError, ValueError):
            text = meta_text = None  # not representable on disk; memory still has it
        held = text if text is not None else _Opaque(value)
        size = len(text) if text is not None else 1024
        with self._lock:
            self._remember(key, time.monotonic(), held, meta, size, ttl)
        if text is not None:
            self._disk_put(key, text, meta_text, ttl)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self._hits = 0
            self._misses = 0
            self._disk_hits = 0
        with self._db_lock:
            if self._db is not None:
                try:
                    self._db.execute("DELETE FROM responses")
                    self._db.commit()
                    self._disk_bytes = 0
                except sqlite3.Error as exc:
                    logger.warning("Response cache clear failed: %s", exc)

    def close(self) -> None:
        with self._db_lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            out = {
                "entries": len(self._entries),
                "bytes": self._bytes,
                "max_bytes": self.max_bytes,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total else 0.0,
                "ttl_seconds": self.ttl_seconds,
                # The disk layer: where it is, how much it holds, and how many
                # hits it served that memory could not (after a restart).
                "persistent": self._db is not None,
                "path": str(self.path) if self.path else None,
                "hits_from_disk": self._disk_hits,
                # Disk rows that no longer matched their hash, dropped and re-fetched.
                "integrity_drops": self._integrity_drops,
            }
        out["entries_on_disk"] = self._disk_count()
        return out


class _Opaque:
    """A cached value that is not JSON: kept as the object, in memory only."""

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


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
        self._last_cost = 1.0
        self._lock = threading.Lock()
        self._waits = 0
        self._slept = 0.0
        self._penalties = 0

    @property
    def interval(self) -> float:
        with self._lock:
            return self._interval

    def wait(self, cost: float = 1.0) -> None:
        """Block until the shared schedule permits the next request.

        `cost` weighs the request in units of the interval: a provider that
        meters compute units (NodeReal) spends more of its per-second
        allowance on some methods than others, so the gap after a request is
        `interval * cost`.

        The sleep happens under the lock deliberately. The point of the pacer is
        that requests leave in single file at a known spacing; releasing the lock
        before sleeping would let every waiting thread compute the same "it is my
        turn" instant and fire together, which is the burst the provider refuses.
        """
        with self._lock:
            now = time.monotonic()
            gap = self._interval * self._last_cost
            elapsed = now - self._last_request_at
            if elapsed < gap:
                delay = gap - elapsed
                time.sleep(delay)
                self._slept += delay
            self._last_request_at = time.monotonic()
            self._last_cost = cost
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
    """Everything the /health endpoint needs to explain a slow trace, and
    what each credential has spent of its allowance today."""
    with _registry_lock:
        return {
            "pacers": {name: p.stats() for name, p in _pacers.items()},
            "caches": {name: c.stats() for name, c in _caches.items()},
            "meters": {name: m.stats() for name, m in _meters.items()},
        }


def reset() -> None:
    """Drop all shared state. Used by the tests to keep cases independent."""
    with _registry_lock:
        _pacers.clear()
        for cache in _caches.values():
            cache.close()
        _caches.clear()
        _meters.clear()


# ---------------------------------------------------------------------------
# One credential's allowance per day
#
# A case's budget bounds one trace; it does not stop a burst of traces, watch
# checks and warm-ups from spending a free tier's whole day (Etherscan 100k
# calls, TronGrid 100k per account) or NodeReal's month in hours. A UnitMeter
# counts every network request made with one credential, trace or not, and
# refuses once the UTC day's allowance is spent; one connection may spend
# only a share of it.
#
# The count is kept in the store as well (models.ProviderMeter, one row per
# credential and day): the free host restarts after 15 idle minutes, and a
# count in memory alone began the day again at zero on every wake (the 8 Nov
# check). A meter reads its row when it is made and writes it at most every
# METER_SAVE_SECONDS while it spends, and at shutdown; a restart forgets at
# most those seconds. Connections are stored by a hash, never an address.
# ---------------------------------------------------------------------------
def credential(api_key: str | None) -> str:
    """How a key is named in a meter's scope (and on /health/detail): a digest, never the key."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:8] if api_key else "anon"


def _connection(client: str) -> str:
    """A connection as a meter counts and stores it: a hash, never the address."""
    return hashlib.sha256(b"exchequer-meter-client:" + client.encode()).hexdigest()[:16]


class UnitMeter:
    MAX_CLIENTS = 10_000  # connection keys come from headers; bounded whatever they say
    STORED_CLIENTS = 200  # the heaviest connections whose share is kept in the store

    def __init__(self, provider: str, limit: float, client_share: float = 0.0,
                 clock: Callable[[], float] = time.time, name: str | None = None,
                 watch_share: float = 0.0) -> None:
        self.provider = provider
        self.name = name  # its row in the store; None: memory only
        self.limit = float(limit)  # 0: no limit, counted only
        self.client_share = client_share
        # The most of the day watch checks may spend (0: no cap of their own),
        # so they never use up what traces need; one connection's checks get
        # client_share of that part.
        self.watch_share = watch_share
        self.watch_used = 0.0
        self._watch_by_client: dict[str, float] = {}
        self._clock = clock
        self._lock = threading.Lock()
        self._day = int(clock() // 86400)
        self.used = 0.0
        self.requests = 0
        self.refused = 0
        self._by_client: dict[str, float] = {}
        self._saved_at = clock()
        self._dirty = False
        self._saving = threading.Lock()

    @property
    def day(self) -> int:
        return self._day

    def _roll(self) -> None:
        """A new UTC day starts every count again. Under the lock."""
        day = int(self._clock() // 86400)
        if day != self._day:
            self._day, self.used, self.requests, self.refused = day, 0.0, 0, 0
            self._by_client.clear()
            self.watch_used = 0.0
            self._watch_by_client.clear()

    def _add(self, counts: dict[str, float], who: str, units: float) -> None:
        if who not in counts and len(counts) >= self.MAX_CLIENTS:
            counts.pop(next(iter(counts)))
        counts[who] = counts.get(who, 0.0) + units

    def charge(self, units: float, client: str | None = None, watch: bool = False) -> str | None:
        """Count one request of `units` (`watch`: for a watch check). None if
        allowed; else which allowance refused it -- "site", "client", "watch"
        (watch checks' part) or "watch-client" (one connection's part of it)
        -- and nothing is counted."""
        with self._lock:
            self._roll()
            self._dirty = True
            refused = None
            who = _connection(client) if client else None
            if self.limit and self.used + units > self.limit:
                refused = "site"
            elif who and self.limit and self.client_share and \
                    self._by_client.get(who, 0.0) + units > self.limit * self.client_share:
                refused = "client"
            elif watch and self.limit and self.watch_share:
                part = self.limit * self.watch_share
                if self.watch_used + units > part:
                    refused = "watch"
                elif who and self.client_share and \
                        self._watch_by_client.get(who, 0.0) + units > part * self.client_share:
                    refused = "watch-client"
            if refused is not None:
                self.refused += 1
                return refused
            if who and self.limit and self.client_share:
                self._add(self._by_client, who, units)
                if watch and self.watch_share:
                    self._add(self._watch_by_client, who, units)
            if watch:
                self.watch_used += units
            self.used += units
            self.requests += 1
            return None

    def spent(self, units: float = 1.0) -> bool:
        """Whether a request of `units` would be refused for the whole site now."""
        with self._lock:
            self._roll()
            return bool(self.limit) and self.used + units > self.limit

    def seconds_to_reset(self) -> int:
        now = self._clock()
        return int((int(now // 86400) + 1) * 86400 - now) + 1

    # -- the store ---------------------------------------------------------
    def restore(self, day: int, used: float, requests: int, refused: int, shares: dict[str, Any]) -> None:
        """Take up a stored count for `day`: never less than what this process
        counted. `shares` is snapshot()'s "shares"."""
        with self._lock:
            self._roll()
            if day != self._day:
                return
            self.used = max(self.used, float(used))
            self.requests = max(self.requests, int(requests))
            self.refused = max(self.refused, int(refused))
            try:
                self.watch_used = max(self.watch_used, float(shares.get("watch") or 0.0))
            except (TypeError, ValueError):
                pass
            for key, counts in (("clients", self._by_client), ("watch_clients", self._watch_by_client)):
                stored = shares.get(key)
                for who, units in list(stored.items() if isinstance(stored, dict) else [])[: self.MAX_CLIENTS]:
                    try:
                        counts[who] = max(counts.get(who, 0.0), float(units))
                    except (TypeError, ValueError):
                        continue

    def _heaviest(self, counts: dict[str, float]) -> dict[str, float]:
        return dict(sorted(counts.items(), key=lambda kv: -kv[1])[: self.STORED_CLIENTS])

    def snapshot(self) -> dict[str, Any]:
        """What the store keeps, read under the lock."""
        with self._lock:
            self._roll()
            return {"day": self._day, "used": self.used, "requests": self.requests,
                    "refused": self.refused,
                    "shares": {"clients": self._heaviest(self._by_client), "watch": self.watch_used,
                               "watch_clients": self._heaviest(self._watch_by_client)}}

    def save_if_due(self, force: bool = False) -> None:
        """Write the count to the store if it changed and METER_SAVE_SECONDS
        have passed (or `force`). One thread writes at a time; the others go on."""
        from . import config

        if self.name is None or not config.PERSIST_METERS or not self._dirty:
            return
        if not force and self._clock() - self._saved_at < config.METER_SAVE_SECONDS:
            return
        if not self._saving.acquire(blocking=False):
            return
        try:
            self._dirty = False
            self._saved_at = self._clock()
            if _store_meter(self.name, self.snapshot()):
                # Read back what the store now holds: a count another process
                # wrote, or one this meter could not read when it was made.
                _load_meter(self)
            else:
                self._dirty = True
        finally:
            self._saving.release()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            self._roll()
            resets = datetime.fromtimestamp((self._day + 1) * 86400, tz=timezone.utc)
            return {
                "provider": self.provider,
                "unit": UNIT_NAMES.get(self.provider, "requests"),
                "used": round(self.used, 2),
                "limit": self.limit or None,
                "remaining": round(max(0.0, self.limit - self.used), 2) if self.limit else None,
                "requests": self.requests,
                "refused": self.refused,
                "client_share": self.client_share or None,
                "watch_used": round(self.watch_used, 2),
                "watch_share": self.watch_share or None,
                "connections": len(self._by_client),  # how many, never which
                "resets_at": resets.isoformat().replace("+00:00", "Z"),
            }


_meters: dict[str, UnitMeter] = {}
_meter_store_warned = [False]
METER_KEEP_DAYS = 7  # rows older than this are deleted as new ones are written


def _meter_store_failed(action: str) -> None:
    if not _meter_store_warned[0]:
        _meter_store_warned[0] = True
        logger.warning("Could not %s the provider meter in the case store; counting in memory", action,
                       exc_info=True)


def _load_meter(meter: UnitMeter) -> None:
    from . import config, models

    if meter.name is None or not config.PERSIST_METERS:
        return
    try:
        with models.session() as s:
            row = s.get(models.ProviderMeter, (meter.name, meter.day))
            if row is None:
                return
            stored = (row.day, row.used, row.requests, row.refused, row.clients_json)
    except Exception:  # noqa: BLE001 -- a store not reachable yet: memory only
        _meter_store_failed("read")
        return
    try:
        shares = json.loads(stored[4] or "{}")
    except ValueError:
        shares = {}
    meter.restore(*stored[:4], shares if isinstance(shares, dict) else {})


def _store_meter(name: str, snap: dict[str, Any]) -> bool:
    """Write one meter's row: never lowering a count another process wrote."""
    from sqlalchemy import case, update
    from sqlalchemy.exc import IntegrityError

    from . import models

    table = models.ProviderMeter
    values = {"used": snap["used"], "requests": snap["requests"], "refused": snap["refused"],
              "clients_json": json.dumps(snap["shares"], separators=(",", ":")),
              "updated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds")}

    def larger(column, value):
        return case((column < value, value), else_=column)
    stmt = (update(table).where(table.name == name, table.day == snap["day"])
            .values(used=larger(table.used, values["used"]),
                    requests=larger(table.requests, values["requests"]),
                    refused=larger(table.refused, values["refused"]),
                    clients_json=values["clients_json"], updated_at=values["updated_at"]))
    try:
        for _ in range(2):
            with models.session() as s:
                if s.execute(stmt).rowcount:
                    s.commit()
                    return True
                s.add(table(name=name, day=snap["day"], **values))
                s.query(table).filter(table.day < snap["day"] - METER_KEEP_DAYS).delete()
                try:
                    s.commit()
                    return True
                except IntegrityError:  # another writer made the row first: update it
                    s.rollback()
        return False
    except Exception:  # noqa: BLE001 -- counting goes on in memory
        _meter_store_failed("write")
        return False


def flush_meters() -> None:
    """Write every meter now (at shutdown)."""
    with _registry_lock:
        meters = list(_meters.values())
    for meter in meters:
        meter.save_if_due(force=True)


def period_limits() -> dict[str, float]:
    """Each provider's allowance per UTC day for this site (0 = counted only)."""
    from . import config

    return {"etherscan": config.ETHERSCAN_CALLS_PER_DAY, "nodereal": config.NODEREAL_CU_PER_DAY,
            "trongrid": config.TRONGRID_CALLS_PER_DAY, "tronscan": config.TRONSCAN_CALLS_PER_DAY}


def get_meter(provider: str, api_key_digest: str) -> UnitMeter:
    from . import config

    name = f"{provider}:{api_key_digest}"
    with _registry_lock:
        meter = _meters.get(name)
        if meter is not None:
            return meter
    made = UnitMeter(provider, period_limits().get(provider, 0),
                     client_share=config.PROVIDER_CLIENT_SHARE_PERCENT / 100, name=name,
                     watch_share=config.WATCH_SHARE_PERCENT / 100)
    _load_meter(made)  # outside the registry lock: a database read
    with _registry_lock:
        return _meters.setdefault(name, made)


# ---------------------------------------------------------------------------
# One case's wall clock
#
# Nothing used to bound how long a trace ran: the time budget was optional and
# checked only between fetch batches, never inside a fetch (retries, backoff,
# pagination) or in the reads after the walk. One TraceBudget per case now
# holds a walk deadline and a hard deadline (the walk plus a grace for the
# later reads); every provider client checks it before each attempt and waits
# out its backoff through it, and follow-on traces share it.
# ---------------------------------------------------------------------------
class TraceStopped(Exception):
    """A trace stopped by its own limits. `reason` is a fixed sentence, safe for a report."""

    reason = "the trace was stopped"


class DeadlineReached(TraceStopped):
    reason = "time limit"


class Cancelled(TraceStopped):
    reason = "stop requested by the person who started it"


# How each provider is named in a case, and what one of its units is.
PROVIDER_NAMES = {"etherscan": "Etherscan", "nodereal": "NodeReal", "trongrid": "TronGrid", "tronscan": "TronScan"}
UNIT_NAMES = {"nodereal": "compute units"}


class BudgetSpent(TraceStopped):
    """A provider's request budget refused a request: this case's own share
    ("trace"), or the site's allowance for the period ("site", "client"; see
    UnitMeter). Like the time limit it stops the walk, it does not fail it."""

    def __init__(self, provider: str, scope: str = "trace", limit: float | None = None) -> None:
        self.provider, self.scope = provider, scope
        name = PROVIDER_NAMES.get(provider, provider)
        of = f" ({limit:,.0f} {UNIT_NAMES.get(provider, 'requests')})" if limit else ""
        self.reason = {
            "trace": f"{name} request budget for this trace{of}",
            "site": f"{name} allowance for this site today",
            "client": f"share of today's {name} allowance for this connection",
            "watch": f"part of today's {name} allowance kept for watch checks",
            "watch-client": f"share of today's {name} watch checks for this connection",
        }.get(scope, f"{name} request budget")
        super().__init__(self.reason)


def trace_unit_limits() -> dict[str, float]:
    """The units one case (a trace and its follow-ons) may spend per provider; 0 is no limit."""
    from . import config

    return {"etherscan": config.TRACE_MAX_ETHERSCAN_CALLS, "nodereal": config.TRACE_MAX_NODEREAL_CU,
            "trongrid": config.TRACE_MAX_TRONGRID_CALLS, "tronscan": config.TRACE_MAX_TRONSCAN_CALLS}


# The share of each unit limit the walk may use; the rest is kept for the
# reads after it (receipts, balances, pro-rata windows, the statement).
WALK_UNIT_SHARE = 0.85


class TraceBudget:
    def __init__(self, walk_seconds: float, grace_seconds: float,
                 clock: Callable[[], float] = time.monotonic,
                 limits: dict[str, float] | None = None, client: str | None = None) -> None:
        self.walk_seconds = float(walk_seconds)
        self.grace_seconds = float(grace_seconds)
        self._clock = clock
        self.started = clock()
        self.walk_deadline = self.started + self.walk_seconds
        self.hard_deadline = self.walk_deadline + self.grace_seconds
        self.stopped = False
        # "time", "budget" or "cancel": what stopped the case first.
        self.stopped_by: str | None = None
        self._cancel = threading.Event()
        # Units (requests; compute units on NodeReal) per provider: the case's
        # ceilings, what it has spent and in how many network requests. One
        # case's fetch threads share it, so it is locked.
        self.limits = dict(limits) if limits is not None else trace_unit_limits()
        self.client = client  # the admit() token, for the site's per-connection share
        self.units: dict[str, float] = {}
        self.requests: dict[str, int] = {}
        self.walking = False  # set by run_trace around the walk (WALK_UNIT_SHARE)
        self._refused: set[tuple[str, bool]] = set()
        self._units_lock = threading.Lock()

    def cancel(self) -> None:
        """Stop the trace at its next provider request or backoff (DELETE /trace/jobs/{id})."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @classmethod
    def for_request(cls, requested_seconds: float | None, client: str | None = None) -> TraceBudget:
        """The server's default when none is asked for, never above its maximum."""
        from . import config

        walk = min(requested_seconds or config.TRACE_TIME_BUDGET_DEFAULT, config.TRACE_TIME_BUDGET_MAX)
        return cls(walk, config.TRACE_POST_WALK_SECONDS, client=client)

    def _stop(self, kind: str) -> None:
        self.stopped = True
        self.stopped_by = self.stopped_by or kind

    def charge(self, provider: str, units: float) -> None:
        """Before one network request: the clock, then this case's units.

        Raises BudgetSpent once the request would pass the provider's limit
        (WALK_UNIT_SHARE of it while the walk runs); after one refusal every
        later request to that provider in the same phase is refused too, so
        a case never reads a little more after being cut off."""
        self.check()
        limit = self.limits.get(provider) or 0
        with self._units_lock:
            ceiling = limit * (WALK_UNIT_SHARE if self.walking else 1.0)
            phase = (provider, self.walking)
            if limit and (phase in self._refused or self.units.get(provider, 0.0) + units > ceiling):
                self._refused.add(phase)
                refused = True
            else:
                self.units[provider] = self.units.get(provider, 0.0) + units
                self.requests[provider] = self.requests.get(provider, 0) + 1
                refused = False
        if refused:
            self._stop("budget")
            raise BudgetSpent(provider, limit=limit)

    def refund(self, provider: str, units: float) -> None:
        """Take back a charge whose request was refused further on (UnitMeter)."""
        with self._units_lock:
            self.units[provider] = max(0.0, self.units.get(provider, 0.0) - units)
            self.requests[provider] = max(0, self.requests.get(provider, 0) - 1)

    def usage(self) -> dict[str, dict[str, float]]:
        """{provider: {"requests", "units"}} so far, for one trace's share (`usage_since`)."""
        with self._units_lock:
            return {p: {"requests": self.requests.get(p, 0), "units": self.units.get(p, 0.0)}
                    for p in sorted(set(self.units) | set(self.requests))}

    def usage_since(self, earlier: dict[str, dict[str, float]]) -> dict[str, dict[str, Any]]:
        """What was spent after `earlier` (a `usage()`), with each provider's limit:
        a follow-on shares the case's budget, and each trace reports its own part."""
        out: dict[str, dict[str, Any]] = {}
        for provider, now in self.usage().items():
            before = earlier.get(provider, {})
            requests = now["requests"] - before.get("requests", 0)
            if requests:
                out[provider] = {"requests": requests,
                                 "units": round(now["units"] - before.get("units", 0.0), 2),
                                 "case_limit": self.limits.get(provider) or None,
                                 "unit": UNIT_NAMES.get(provider, "requests")}
        return out

    def remaining(self) -> float:
        return self.hard_deadline - self._clock()

    def walk_over(self) -> bool:
        return self._clock() >= self.walk_deadline

    def walk_remaining(self) -> float:
        """Seconds the walk may still expand, by this budget's own clock."""
        return max(0.0, self.walk_deadline - self._clock())

    def check(self) -> None:
        """Raise Cancelled once a stop was asked for, DeadlineReached once the hard deadline has passed."""
        if self._cancel.is_set():
            self._stop("cancel")
            raise Cancelled()
        if self.remaining() <= 0:
            self._stop("time")
            raise DeadlineReached()

    def timeout(self, default: float) -> float:
        """A request timeout that cannot outlast the case."""
        return max(1.0, min(default, self.remaining()))

    def sleep(self, seconds: float) -> None:
        """A retry backoff that never sleeps past the deadline."""
        if seconds >= self.remaining():
            self._stop("time")
            raise DeadlineReached()
        if self._cancel.wait(seconds):  # a stop ends the wait at once
            self._stop("cancel")
            raise Cancelled()


# Who a read outside any trace is for: (connection, whether it is a watch
# check). Set around a watch check (charged_to), so its reads count against
# that connection's share and against the part of the day kept for watches.
_charged: ContextVar[tuple[str | None, bool]] = ContextVar("charged_to", default=(None, False))


@contextmanager
def charged_to(client: str | None, watch: bool = False):
    """Charge the reads made in this context, outside a trace, to `client`
    (the admit()-style connection key), and as watch checks if `watch`.
    Context does not cross threads: set it on the thread that reads."""
    token = _charged.set((client, watch))
    try:
        yield
    finally:
        _charged.reset(token)


def spend(provider: str, api_key_digest: str, units: float, budget: TraceBudget | None) -> None:
    """The one check every provider client makes before each network attempt
    (retries included; cache hits make none): the case's clock and its units,
    then the credential's allowance for the day -- with or without a case, so
    watch checks and warm-ups count too. Raises a TraceStopped (BudgetSpent
    for either budget) when the request may not be sent."""
    if budget is not None:
        budget.charge(provider, units)
    connection, watch = _charged.get()
    client = budget.client if budget is not None and budget.client else connection
    meter = get_meter(provider, api_key_digest)
    refused = meter.charge(units, client, watch=watch)
    meter.save_if_due()
    if refused is not None:
        from .etherscan_client import AllowanceSpent  # here: that module imports this one

        if budget is not None:
            budget.refund(provider, units)
            budget._stop("budget")
        raise AllowanceSpent(provider, scope=refused)


# The budget a background job runs its trace under, handed to run_trace on the
# job's own thread (routes/jobs.py). Provider clients get theirs explicitly:
# the fetch threads do not inherit context.
_current: contextvars.ContextVar[TraceBudget | None] = contextvars.ContextVar("trace_budget", default=None)


def current_budget() -> TraceBudget | None:
    return _current.get()


@contextlib.contextmanager
def using(budget: TraceBudget):
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)
