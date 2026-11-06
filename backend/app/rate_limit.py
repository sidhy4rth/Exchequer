"""Per-client limit on how many traces can be started.

A trace spends the deployment's free-tier provider quota, and before this
anyone could start them back to back. TRACE_MAX_RUNNING already caps how many
run at once; this caps how many one client may start per hour. In memory,
per process: a restart forgets the counts, which is acceptable for a limit
whose job is to stop a loop, not to bill anyone.

Behind a host's proxy every request arrives from the proxy, so the client
is read from the proxy's headers -- but only when EXCHEQUER_TRUST_PROXY is
set (the Docker image sets it). Without a proxy in front, those headers are
whatever the client chose to send.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from . import config


def client_ip(headers: dict[str, str] | object, peer: str | None) -> str:
    """The caller's address: the proxy's view of it when trusted, else the peer."""
    if config.TRUST_PROXY_HEADERS and config.PROXY_CLIENT_FIRST:
        # Render: the proxy writes the address it saw first. Ignore X-Real-IP,
        # which Render does not set, so a client could choose it.
        forwarded = headers.get("x-forwarded-for")  # type: ignore[union-attr]
        if forwarded:
            return forwarded.split(",")[0].strip()
    elif config.TRUST_PROXY_HEADERS:
        real = headers.get("x-real-ip")  # type: ignore[union-attr]
        if real:
            return real.strip()
        forwarded = headers.get("x-forwarded-for")  # type: ignore[union-attr]
        if forwarded:
            # The proxy appends the address it saw; anything to the left of it
            # came from the client and could be invented.
            return forwarded.split(",")[-1].strip()
    return peer or "unknown"


class SlidingWindowLimiter:
    # Past PRUNE_AT keys, clients whose hits have all expired are forgotten
    # (at most once a minute); MAX_KEYS is a hard ceiling on memory, since
    # the keys come from headers a client may invent.
    PRUNE_AT = 10_000
    MAX_KEYS = 50_000

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._next_prune = float("-inf")

    def _prune(self, now: float) -> None:
        """Forget idle clients. Called with the lock held."""
        if len(self._hits) > self.PRUNE_AT and now >= self._next_prune:
            self._next_prune = now + 60
            cutoff = now - self.window
            for stale in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
                del self._hits[stale]
        while len(self._hits) > self.MAX_KEYS:  # oldest-seen first
            del self._hits[next(iter(self._hits))]

    def check(self, key: str, now: float | None = None, cost: int = 1) -> float | None:
        """Record `cost` hits for `key`. None if allowed, else seconds until it would be.

        A cost above one (a batch of traces) is all or nothing."""
        if self.limit <= 0:
            return None
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if cost > self.limit:
                return float(self.window)
            if len(hits) + cost > self.limit:
                return max(1.0, hits[len(hits) + cost - self.limit - 1] + self.window - now)
            hits.extend([now] * cost)
            self._prune(now)
            return None

    def refund(self, key: str, cost: int = 1) -> None:
        """Take back the newest `cost` hits for `key`: a later check refused
        the request this one let through, so nothing was spent."""
        with self._lock:
            hits = self._hits.get(key)
            for _ in range(min(cost, len(hits) if hits else 0)):
                hits.pop()

    def remaining(self, key: str, now: float | None = None) -> int:
        if self.limit <= 0:
            return 10**6
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.get(key)  # asking about a client never adds it
            if hits is None:
                return self.limit
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if not hits:
                del self._hits[key]
            return max(0, self.limit - len(hits))

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


traces = SlidingWindowLimiter(config.TRACES_PER_HOUR_PER_CLIENT, 3600)
# A watch is re-read on a schedule for as long as it exists (watchlist.py).
watches = SlidingWindowLimiter(config.WATCHES_PER_HOUR_PER_CLIENT, 3600)
# Every freeze-request create or update is a database write (routes/requests.py).
request_writes = SlidingWindowLimiter(config.REQUEST_WRITES_PER_HOUR_PER_CLIENT, 3600)

# Ceilings over every client, under one key. The per-client limits above trust
# the address the proxy headers report, which a client may be able to set;
# these cannot be dodged that way, so they bound the quota whatever the headers say.
TOTAL = "all"
traces_total = SlidingWindowLimiter(config.TRACES_PER_HOUR_TOTAL, 3600)
watches_total = SlidingWindowLimiter(config.WATCHES_PER_HOUR_TOTAL, 3600)


def charge(per_client: SlidingWindowLimiter, total: SlidingWindowLimiter, client: str,
           cost: int = 1) -> tuple[float, str] | None:
    """Charge `cost` to the client's limit and to the site-wide one, all or
    nothing. None if allowed; else (seconds to wait, "client" or "site")."""
    wait = per_client.check(client, cost=cost)
    if wait is not None:
        return wait, "client"
    wait = total.check(TOTAL, cost=cost)
    if wait is not None:
        per_client.refund(client, cost)
        return wait, "site"
    return None
