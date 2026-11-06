"""Trace the demo addresses in the background at startup, so they are warm.

On the free tiers a first trace of an address is as slow as the provider
allows -- twenty to forty seconds for the flagship demo -- and every later
trace of the same address is instant because its responses are cached. On a
hosted instance that means whoever opens a demo first after a redeploy pays
the cold cost, and if that is a judge the tool looks slow for a reason that
has nothing to do with the tool.

So, when EXCHEQUER_WARM_CACHE is on, a daemon thread runs each entry of
data/demo_traces.json through the same code path as POST /trace, stores
nothing, and lets the response cache (which persists to disk) fill. It then
sleeps for most of the cache TTL and does it again, so a long-running
instance never lets the demos go cold. A request that arrives while the
warm-up is running shares the credential's rate with it -- the pacer makes
sure neither trips the limit -- so a trace during those first minutes is
slower than usual; /health shows whether the warm-up is still in progress.

Each demo takes one of the server's trace slots, like a live trace, and has
the same time limit. The warm-up never runs where its cache cannot outlive
the instance -- a temporary disk (Render's free plan, wiped at every sleep)
or a cache kept in memory only -- unless EXCHEQUER_WARM_CACHE=force: there
every wake would re-trace every demo for nothing.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from . import config
from .models import utc_now_iso

logger = logging.getLogger(__name__)

DEMO_TRACES_PATH = config.DATA_DIR / "demo_traces.json"

_state: dict[str, Any] = {
    "enabled": False,
    "in_progress": False,
    "runs_completed": 0,
    "last_started_at": None,
    "last_completed_at": None,
    "last_run": [],  # one line per demo: address, seconds, outcome
    "last_error": None,  # why the last run stopped short, if it did
    "skipped": None,  # why the warm-up did not start, when it was asked to
}
_lock = threading.Lock()
_thread: threading.Thread | None = None
_wait = time.sleep  # between runs; tests stop the loop here


def status() -> dict[str, Any]:
    with _lock:
        return {**_state, "alive": _thread is not None and _thread.is_alive()}


def load_demo_requests() -> list[dict[str, Any]]:
    """The demo trace requests; anything in the file that is not one is left out."""
    try:
        seeds = json.loads(DEMO_TRACES_PATH.read_text())
    except (OSError, ValueError) as exc:
        logger.warning("No demo traces to warm (%s): %s", DEMO_TRACES_PATH, exc)
        return []
    if not isinstance(seeds, list):
        logger.warning("No demo traces to warm: %s is not a list", DEMO_TRACES_PATH)
        return []
    kept = [seed for seed in seeds if isinstance(seed, dict)]
    if len(kept) != len(seeds):
        logger.warning("Warm-up: %d entries of %s are not trace requests; skipped",
                       len(seeds) - len(kept), DEMO_TRACES_PATH)
    return kept


def warm_once() -> list[dict[str, Any]]:
    """Run every demo trace once, storing nothing. Returns one record each."""
    # Imported here: the pipeline is heavy to import and main imports this
    # module at startup, so the import waits until a warm-up actually runs.
    from . import pipeline
    from .pipeline import TraceRequest
    from .routes import cases

    records: list[dict[str, Any]] = []
    for seed in load_demo_requests():
        started = time.monotonic()
        record: dict[str, Any] = {"address": None, "direction": None, "max_depth": None}
        try:
            record = {"address": seed.get("address"), "chain": seed.get("chain"),
                      "direction": seed.get("direction"), "max_depth": seed.get("max_depth")}
            request = TraceRequest(**seed)
            # One of the server's trace slots, as a live trace takes: waits
            # while live traces hold them all, rather than running beside them.
            cases._running.acquire()
            try:
                result = pipeline.run_trace(request)
            finally:
                cases._running.release()
            record.update(
                ok=True, seconds=round(time.monotonic() - started, 1),
                exchange=result.get("exchange"),
                from_cache=(result.get("evidence") or {}).get("from_cache"),
                retrieved=(result.get("evidence") or {}).get("retrieved"),
            )
        except Exception as exc:  # noqa: BLE001 -- one cold demo must not stop the rest
            record.update(ok=False, seconds=round(time.monotonic() - started, 1), error=str(exc)[:200])
            logger.warning("Warm-up trace of %s failed: %s", seed.get("address"), exc)
        records.append(record)
        logger.info(
            "Warm-up: %s %s d%s in %ss (%s)", record["address"], record["direction"],
            record["max_depth"], record["seconds"],
            "ok" if record.get("ok") else "failed",
        )
    return records


def _loop(interval: float) -> None:
    while True:
        with _lock:
            _state["in_progress"] = True
            _state["last_started_at"] = utc_now_iso()
        records: list[dict[str, Any]] = []
        error = None
        try:
            records = warm_once()
        except Exception as exc:  # noqa: BLE001 -- the thread must outlive one bad run
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
            logger.exception("Warm-up run failed")
        with _lock:
            _state["in_progress"] = False
            _state["runs_completed"] += 1
            _state["last_completed_at"] = utc_now_iso()
            _state["last_run"] = records
            _state["last_error"] = error
        logger.info("Warm-up complete: %d demo traces; next in %.0f minutes",
                    len(records), interval / 60)
        _wait(interval)


def start_in_background() -> bool:
    """Start the warm-up thread if it is configured on. Returns whether it did."""
    global _thread
    if not config.WARM_CACHE_AT_STARTUP:
        return False
    if not config.WARM_CACHE_FORCED and (config.TEMPORARY_DISK or config.API_CACHE_PATH is None):
        # The cache it fills would not outlive this instance.
        reason = "temporary disk" if config.TEMPORARY_DISK else "provider cache in memory only"
        with _lock:
            _state["skipped"] = reason
        logger.info("Warm-up off: %s (EXCHEQUER_WARM_CACHE=force overrides)", reason)
        return False
    if not load_demo_requests():
        return False
    with _lock:
        _state["enabled"] = True
    # Re-warm at three quarters of the TTL so nothing expires between runs.
    interval = max(config.API_CACHE_TTL_SECONDS * 0.75, 300.0)
    _thread = threading.Thread(target=_loop, args=(interval,), name="warmup", daemon=True)
    _thread.start()
    logger.info("Warming the response cache from %s in the background", DEMO_TRACES_PATH)
    return True
