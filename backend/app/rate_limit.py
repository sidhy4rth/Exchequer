"""Per-client limit on how many traces can be started.

A trace spends the deployment's free-tier provider quota, and before this
anyone could start them back to back. TRACE_MAX_RUNNING already caps how many
run at once; this caps how many one client may start per hour. In memory,
per process: a restart forgets the counts, which is acceptable for a limit
whose job is to stop a loop, not to bill anyone.

Behind Railway's proxy every request arrives from the proxy, so the client
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
    if config.TRUST_PROXY_HEADERS:
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
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> float | None:
        """Record a hit for `key`. None if allowed, else seconds until it would be."""
        if self.limit <= 0:
            return None
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1.0, hits[0] + self.window - now)
            hits.append(now)
            if len(self._hits) > 10_000:  # forget idle clients
                for stale in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale]
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


traces = SlidingWindowLimiter(config.TRACES_PER_HOUR_PER_CLIENT, 3600)
