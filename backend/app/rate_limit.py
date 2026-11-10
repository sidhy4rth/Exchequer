"""Per-client limit on how many traces can be started.

A trace spends the deployment's free-tier provider quota, and before this
anyone could start them back to back. TRACE_MAX_RUNNING already caps how many
run at once; this caps how many one client may start per hour. In memory,
per process: a restart forgets the counts, which is acceptable for a limit
whose job is to stop a loop, not to bill anyone.

Behind a host's proxy every request arrives from the proxy, so the client
is read from the proxy's headers -- but only as config.proxy_mode says, and
never from a value the client could have written when the edge says who it
is. Without a proxy in front, those headers are whatever the client chose.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any

from . import config

logger = logging.getLogger(__name__)

PROBE_ME = "x-exchequer-probe-me"


def _key(raw: str | None) -> str | None:
    """A client key from one address: IPv4 as itself, IPv6 by its /64 (one
    subscriber's whole allocation, so rotating within it buys nothing), and
    nothing for a value that is not an address."""
    if not raw:
        return None
    try:
        ip = ipaddress.ip_address(raw.strip()[:64])
        if isinstance(ip, ipaddress.IPv6Address):
            if ip.ipv4_mapped is not None:
                return str(ip.ipv4_mapped)
            return str(ipaddress.ip_network(f"{ip.exploded}/64", strict=False))
        return str(ip)
    except ValueError:
        return None


def _hops(headers: Any) -> list[str]:
    forwarded = headers.get("x-forwarded-for") or ""
    return [h.strip() for h in forwarded.split(",") if h.strip()]


_warned_leftmost = False


def _choose(headers: Any) -> tuple[str | None, str, bool]:
    """(address, which header gave it, whether the client could have chosen it)."""
    if config.TRUST_PROXY_HEADERS and config.PROXY_CLIENT_FIRST:
        if config.CLIENT_IP_HEADER and headers.get(config.CLIENT_IP_HEADER):
            return headers.get(config.CLIENT_IP_HEADER), config.CLIENT_IP_HEADER, False
        hops = _hops(headers)
        if config.PROXY_HOPS:
            if len(hops) < config.PROXY_HOPS:
                return None, "peer", False
            return hops[-config.PROXY_HOPS], f"x-forwarded-for[-{config.PROXY_HOPS}]", False
        # Not measured: the leftmost entry can be forged, but a guessed hop
        # count could key every visitor on one edge address instead.
        return (hops[0] if hops else None), "x-forwarded-for[0]", True
    if config.TRUST_PROXY_HEADERS:
        if headers.get("x-real-ip"):
            return headers.get("x-real-ip"), "x-real-ip", False
        hops = _hops(headers)
        # The proxy appends the address it saw; anything to its left came
        # from the client and could be invented.
        return (hops[-1] if hops else None), "x-forwarded-for[-1]", False
    return None, "peer", False


def client_ip(headers: dict[str, str] | object, peer: str | None) -> str:
    """The caller's key: the proxy's view of its address when trusted, else
    the peer. Always short, whatever the headers held."""
    global _warned_leftmost
    raw, source, choosable = _choose(headers)
    key = _key(raw)
    if key is None:
        return _key(peer) or (peer or "unknown")[:64]
    if choosable and not _warned_leftmost:
        _warned_leftmost = True
        logger.warning("Client addresses come from the leftmost X-Forwarded-For entry, which a "
                       "client can choose: measure with /health/detail and set EXCHEQUER_PROXY_HOPS "
                       "or EXCHEQUER_CLIENT_IP_HEADER")
    return key


def rule() -> str:
    """The rule in force, in words, for the startup log and /health/detail."""
    if config.TRUST_PROXY_HEADERS and config.PROXY_CLIENT_FIRST:
        parts = [config.CLIENT_IP_HEADER] if config.CLIENT_IP_HEADER else []
        parts.append(f"x-forwarded-for, entry {config.PROXY_HOPS} from the right" if config.PROXY_HOPS
                     else "the leftmost x-forwarded-for entry (a client can choose it)")
        return ", else ".join(parts) + ", else the connection's peer"
    if config.TRUST_PROXY_HEADERS:
        return "x-real-ip, else the last x-forwarded-for entry, else the connection's peer"
    return "the connection's peer (no proxy headers trusted)"


# A per-process secret, so the probe can show which values are equal
# without showing any of them.
_PROBE_SECRET = secrets.token_bytes(16)


def _fp(key: str | None) -> str | None:
    return hmac.new(_PROBE_SECRET, key.encode(), hashlib.sha256).hexdigest()[:10] if key else None


def probe(headers: Any, peer: str | None) -> dict[str, Any]:
    """What arrived and what was chosen, for the operator to measure the
    proxy chain after a deploy. No address is shown: each is a fingerprint
    (equal values, equal fingerprints, until a restart), and `is_me` says
    whether it equals the address sent as X-Exchequer-Probe-Me."""
    me = _key(headers.get(PROBE_ME))

    def show(raw: str | None) -> dict[str, Any] | None:
        if raw is None:
            return None
        key = _key(raw)
        return {"fp": _fp(key) or "not an address", "is_me": (key == me) if me else None}

    hops = _hops(headers)
    raw, source, choosable = _choose(headers)
    chosen = client_ip(headers, peer)
    out: dict[str, Any] = {
        "mode": config._proxy_raw or "none",
        "rule": rule(),
        "source": source if _key(raw) else "peer",
        "client_can_choose_key": choosable and _key(raw) is not None,
        "chosen": {"fp": _fp(chosen), "is_me": (chosen == me) if me else None},
        "candidates": {
            "peer": show(peer),
            **{name: show(headers.get(name)) for name in
               ("cf-connecting-ip", "true-client-ip", "x-real-ip", "forwarded")},
            "x-forwarded-for": [show(h) for h in hops],
        },
    }
    if not me:
        out["advice"] = f"Send your public address as {PROBE_ME} to compare."
    elif chosen == me:
        out["advice"] = "The key is your address: the rule is right for this route to the site."
    elif any(_key(h) == me for h in hops):
        k = len(hops) - max(i for i, h in enumerate(hops) if _key(h) == me)
        out["advice"] = (f"Your address is entry {k} from the right of x-forwarded-for: "
                         f"set EXCHEQUER_PROXY_HOPS={k} (and EXCHEQUER_CLIENT_IP_HEADER=none if "
                         "cf-connecting-ip is not you). Check from a second network first.")
    else:
        out["advice"] = "Your address is in no header: keep the current rule and compare again."
    return out


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
# A recheck rereads a case's cited transfers from a second provider (routes/recheck.py).
rechecks = SlidingWindowLimiter(config.RECHECKS_PER_HOUR_PER_CLIENT, 3600)

# Ceilings over every client, under one key. The per-client limits above trust
# the address the proxy headers report, which a client may be able to set;
# these cannot be dodged that way, so they bound the quota whatever the headers say.
TOTAL = "all"
traces_total = SlidingWindowLimiter(config.TRACES_PER_HOUR_TOTAL, 3600)
watches_total = SlidingWindowLimiter(config.WATCHES_PER_HOUR_TOTAL, 3600)
rechecks_total = SlidingWindowLimiter(config.RECHECKS_PER_HOUR_TOTAL, 3600)


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


class GrowingDelay:
    """Sign-in failures slow a key down; they never shut it out for good.

    The first `free` failures cost nothing; after that each one makes the key
    wait twice as long as the last, from `first` up to `cap` seconds. A key
    with no failure for `forget` seconds starts again, and a success clears
    it. A permanent lockout would let anyone lock an officer out by typing
    their e-mail with a wrong password; this only slows the guessing."""

    MAX_KEYS = 50_000

    def __init__(self, free: int, first: float = 1.0, cap: float = 30.0, forget: float = 900.0) -> None:
        self.free, self.first, self.cap, self.forget = free, first, cap, forget
        self._seen: dict[str, tuple[int, float]] = {}  # key -> (failures, time of the last)
        self._lock = threading.Lock()

    def failures(self, key: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            count, last = self._seen.get(key, (0, now))
            return count if now - last < self.forget else 0

    def wait(self, key: str, now: float | None = None) -> float | None:
        """Seconds `key` must still wait before its next try, or None."""
        now = time.monotonic() if now is None else now
        with self._lock:  # one read: a success may drop the key at any moment
            count, last = self._seen.get(key, (0, now))
        if now - last >= self.forget or count <= self.free:
            return None
        left = min(self.cap, self.first * 2 ** (count - self.free - 1)) - (now - last)
        return left if left > 0 else None

    def failed(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        count = self.failures(key, now)
        with self._lock:
            self._seen.pop(key, None)
            self._seen[key] = (count + 1, now)
            while len(self._seen) > self.MAX_KEYS:  # oldest-seen first
                del self._seen[next(iter(self._seen))]

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._seen.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()


# Sign-in (routes/accounts.py): attempts per client, and failures per e-mail
# from one client (keyed "e-mail client"), in 15 minutes; a growing wait
# after repeated failures by a client, by a client for one e-mail, and for
# an e-mail from everywhere. The e-mail-wide wait holds only a client that
# has failed for that e-mail itself, so nobody can shut an officer out by
# failing for them: an officer who has not mistyped is never held by anyone
# else, and one who has is held at most until that failure is forgotten.
login_clients = SlidingWindowLimiter(30, 900)
login_emails = SlidingWindowLimiter(10, 900)
login_client_delay = GrowingDelay(free=5)
login_pair_delay = GrowingDelay(free=3)
login_email_delay = GrowingDelay(free=3)
LOGIN_LIMITS = (login_clients, login_emails, login_client_delay, login_pair_delay, login_email_delay)
